"""
변환 통합 모듈 (Converter)

Fragment(매퍼 조각) 하나를 받아 다음을 통합 수행한다:
  1) SqlAnalyzer로 크기/복잡도/전략 분석
  2) manual_review 전략이면 LLM 호출 없이 스킵(사유 기록)
  3) 그 외에는 LLM(invoke_json)으로 Oracle→PostgreSQL 변환
  4) TestCaseGenerator로 동적 SQL 테스트 케이스 생성
  5) ConversionResult로 통합

딕셔너리는 조각에서 참조될 가능성이 있는 컬럼만 추려(subset) 프롬프트에 실어
토큰을 절약한다. 이 추림은 딕셔너리 컬럼명이 조각 텍스트에 단어로 등장하는지의
단순 문자열 감지로 하며(SQL 파싱 아님), 오검출은 LLM이 무시하도록 허용한다.

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - Converter 구현: convert(fragment) → ConversionResult
  - analyzer/LLM/TC 생성 통합, 딕셔너리 subset 압축, 에러 시 원본 유지

2026-07-28 | OMA Team | 비실행 조각(resultMap/sql) TC 미생성
  - 원인: 모든 조각에 TC를 생성해 <resultMap>/<sql> 조각도 TC가 생김.
    이들은 MyBatis MappedStatement로 등록되지 않아(실행 statement 아님)
    검증 시 "Mapped Statements collection does not contain value" 오류로
    무조건 실패 → 통과율/실패건수를 왜곡(E유형 오생성).
  - 수정: 실행 가능한 statement_type(select/insert/update/delete)만 TC 생성.
    resultMap/sql은 include로 select 안에서 함께 검증되므로 단독 TC 불필요.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from oma.converter.llm_client import LLMClient
from oma.converter.prompts import build_conversion_prompt, build_system_prompt
from oma.converter.sql_analyzer import STRATEGY_MANUAL_REVIEW, SqlAnalyzer
from oma.dictionary.loader import DictionaryLoader
from oma.fragmenter.splitter import Fragment
from oma.testcase.generator import TestCaseGenerator
from oma.utils.exceptions import LLMError

logger = logging.getLogger(__name__)

# 딕셔너리 subset이 이 개수를 넘으면 프롬프트 과대 → 경고
_MAX_SUBSET_COLUMNS = 400

# 검증기가 단독 실행할 수 있는 statement 태그. resultMap/sql 등은 MyBatis
# MappedStatement로 등록되지 않으므로 TC 생성 대상에서 제외한다.
_EXECUTABLE_TYPES = frozenset({"select", "insert", "update", "delete"})


@dataclass
class ConversionResult:
    """단일 조각 변환 결과"""

    mapper_name: str
    sql_id: str
    status: str  # 'success' | 'partial' | 'skipped' | 'failed'
    strategy: str
    original_sql: str
    converted_sql: str
    analysis: Dict[str, Any] = field(default_factory=dict)
    type_casts: List[Dict[str, Any]] = field(default_factory=list)
    syntax_changes: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    test_cases: List[Dict[str, Any]] = field(default_factory=list)
    param_mappings: List[Dict[str, Any]] = field(default_factory=list)
    manual_review_required: bool = False
    error: Optional[str] = None


class Converter:
    """
    조각 변환 통합기

    Attributes:
        llm_client: LLMClient (변환 호출)
        loader: DictionaryLoader (컬럼 타입/샘플)
        analyzer: SqlAnalyzer
        tc_generator: TestCaseGenerator
    """

    def __init__(
        self,
        llm_client: LLMClient,
        loader: DictionaryLoader,
        analyzer: SqlAnalyzer,
        tc_generator: Optional[TestCaseGenerator] = None,
        source_type: str = "oracle",
        target_type: str = "postgres",
    ) -> None:
        """
        초기화 (의존성 주입)

        Args:
            llm_client: LLM 클라이언트
            loader: 딕셔너리 로더
            analyzer: SQL 분석기
            tc_generator: 테스트 케이스 생성기 (없으면 loader로 생성)
            source_type: 소스 DB 타입 (oracle/epas) - 방언 프롬프트 선택
            target_type: 타겟 DB 타입 (postgres/mysql) - 방언 프롬프트 선택
        """
        self.llm_client = llm_client
        self.loader = loader
        self.analyzer = analyzer
        self.tc_generator = tc_generator or TestCaseGenerator(loader)
        self.source_type = source_type
        self.target_type = target_type
        # 방언별 시스템 프롬프트를 1회 구성해 재사용
        self._system_prompt = build_system_prompt(source_type, target_type)

    def convert(self, fragment: Fragment) -> ConversionResult:
        """
        조각 하나를 변환한다.

        Args:
            fragment: 변환 대상 Fragment

        Returns:
            ConversionResult
        """
        analysis = self.analyzer.analyze(fragment.content)
        strategy = analysis["strategy"]

        # 매우 크고 복잡 → LLM 호출 없이 수동 검토로 스킵
        if strategy == STRATEGY_MANUAL_REVIEW:
            logger.warning(
                "수동 검토 대상 (스킵): %s/%s (%d자, 복잡도 %s)",
                fragment.mapper_name, fragment.sql_id,
                analysis["char_count"], analysis["complexity_level"],
            )
            return ConversionResult(
                mapper_name=fragment.mapper_name,
                sql_id=fragment.sql_id,
                status="skipped",
                strategy=strategy,
                original_sql=fragment.content,
                converted_sql=fragment.content,
                analysis=analysis,
                manual_review_required=True,
                warnings=[{
                    "severity": "high",
                    "type": "complex_query",
                    "issue": "SQL이 너무 크고 복잡하여 자동 변환에서 제외됨",
                    "suggestion": "쿼리 리팩터링 또는 수동 변환 검토 필요",
                }],
            )

        # LLM 변환 (param_mappings로 TC 샘플값을 정확히 하기 위해 먼저 호출)
        try:
            llm_result = self._invoke_llm(fragment)
        except LLMError as e:
            logger.error("LLM 변환 실패: %s/%s - %s",
                         fragment.mapper_name, fragment.sql_id, e)
            # 실패해도 매핑 없이 TC는 생성 (폴백)
            return ConversionResult(
                mapper_name=fragment.mapper_name,
                sql_id=fragment.sql_id,
                status="failed",
                strategy=strategy,
                original_sql=fragment.content,
                converted_sql=fragment.content,  # 실패 시 원본 유지
                analysis=analysis,
                test_cases=self._generate_test_cases(fragment, {}),
                manual_review_required=True,
                error=str(e),
            )

        converted_sql = llm_result.get("converted_sql") or fragment.content
        status = llm_result.get("conversion_status", "success")
        warnings = llm_result.get("warnings", []) or []
        manual = bool(llm_result.get("manual_review_required", False))

        # LLM이 추론한 param→column 매핑으로 TC 생성 (실제 딕셔너리 샘플값 사용)
        param_columns = self._extract_param_columns(llm_result)
        test_cases = self._generate_test_cases(fragment, param_columns)

        return ConversionResult(
            mapper_name=fragment.mapper_name,
            sql_id=fragment.sql_id,
            status=status,
            strategy=strategy,
            original_sql=fragment.content,
            converted_sql=converted_sql,
            analysis=analysis,
            type_casts=llm_result.get("type_casts", []) or [],
            syntax_changes=llm_result.get("syntax_changes", []) or [],
            warnings=warnings,
            test_cases=test_cases,
            param_mappings=llm_result.get("param_mappings", []) or [],
            manual_review_required=manual or bool(warnings),
        )

    def _invoke_llm(self, fragment: Fragment) -> Dict[str, Any]:
        """
        LLM에 변환을 요청하고 JSON 결과를 반환한다.

        Args:
            fragment: 대상 조각

        Returns:
            LLM JSON 응답 dict

        Raises:
            LLMError: 호출/파싱 실패 시
        """
        subset = self.build_dictionary_subset(fragment.content)
        prompt = build_conversion_prompt(fragment.content, subset)
        return self.llm_client.invoke_json(prompt, system=self._system_prompt)

    def build_dictionary_subset(self, fragment_content: str) -> Dict[str, Any]:
        """
        조각에서 참조될 가능성이 있는 컬럼만 딕셔너리에서 추린다.

        정확도를 위해 2단계 문자열 감지를 쓴다 (SQL 파싱 아님):
          1) 조각에 실제 등장하는 테이블명 집합을 구한다.
          2) 그 테이블에 속하면서 컬럼명도 조각에 등장하는 컬럼만 담는다.
        조각에서 테이블을 하나도 찾지 못하면(드묾) 컬럼명 단독 매칭으로 폴백한다.
        오검출은 LLM이 무시하도록 허용하며, 과대 시 상한으로 자른다.

        Args:
            fragment_content: 조각 XML

        Returns:
            {"table.column": {data_type, cast_hint, sample_value}} subset
        """
        dictionary = self.loader.load()
        haystack = fragment_content.upper()

        # 1) 조각에 등장하는 테이블명 집합 (딕셔너리 테이블명 기준)
        tables_present = {
            entry.get("table", "").upper()
            for entry in dictionary.values()
            if entry.get("table") and entry["table"].upper() in haystack
        }

        subset: Dict[str, Any] = {}
        truncated = False
        for key, entry in dictionary.items():
            column = entry.get("column", "")
            table = entry.get("table", "")
            if not column:
                continue

            if tables_present:
                # 테이블이 조각에 있고, 컬럼명도 조각에 등장해야 채택
                if table.upper() not in tables_present:
                    continue
                if column.upper() not in haystack:
                    continue
            else:
                # 폴백: 테이블 식별 실패 시 컬럼명 단독 매칭
                if column.upper() not in haystack:
                    continue

            subset[key] = {
                "data_type": entry.get("data_type"),
                "cast_hint": entry.get("cast_hint"),
                "sample_value": entry.get("sample_value"),
            }
            if len(subset) >= _MAX_SUBSET_COLUMNS:
                truncated = True
                break

        if truncated:
            logger.warning(
                "딕셔너리 subset 상한(%d) 도달 — 일부 컬럼 생략",
                _MAX_SUBSET_COLUMNS,
            )
        return subset

    def _extract_param_columns(
        self, llm_result: Dict[str, Any]
    ) -> Dict[str, str]:
        """
        LLM의 param_mappings에서 {param: table.column} 매핑을 추출한다.

        column이 null인(추론 실패) 항목은 제외한다. TestCaseGenerator가 이 매핑으로
        딕셔너리 샘플값을 조회해 현실적인 TC 파라미터를 만든다.

        Args:
            llm_result: LLM invoke_json 결과

        Returns:
            {param: "table.column"} 매핑
        """
        mappings = llm_result.get("param_mappings") or []
        result: Dict[str, str] = {}
        for m in mappings:
            param = m.get("param")
            column = m.get("column")
            if param and column:
                result[param] = column
        return result

    def _generate_test_cases(
        self, fragment: Fragment, param_columns: Dict[str, str]
    ) -> List[Dict[str, Any]]:
        """
        조각의 동적 SQL 테스트 케이스를 생성해 dict 리스트로 반환한다.

        Args:
            fragment: 대상 조각
            param_columns: LLM이 추론한 {param: table.column} 매핑 (샘플값 조회용)

        Returns:
            TC dict 리스트 (동적 SQL 없으면 기본 1개 이하). 비실행 조각은 빈 리스트.
        """
        # 실행 불가능한 조각(resultMap/sql 등)은 검증 대상이 아니므로 TC 미생성
        stype = (fragment.statement_type or "").lower()
        if stype not in _EXECUTABLE_TYPES:
            logger.debug(
                "비실행 조각 TC 생략: %s/%s (%s)",
                fragment.mapper_name, fragment.sql_id, stype,
            )
            return []
        try:
            tcs = self.tc_generator.generate(
                fragment.mapper_name, fragment.sql_id, fragment.content,
                param_columns=param_columns,
                namespace=fragment.namespace,
            )
        except Exception as e:  # TC 생성 실패는 변환을 막지 않음
            logger.warning("TC 생성 실패 (건너뜀): %s/%s - %s",
                           fragment.mapper_name, fragment.sql_id, e)
            return []
        return [TestCaseGenerator.to_dict(tc) for tc in tcs]
