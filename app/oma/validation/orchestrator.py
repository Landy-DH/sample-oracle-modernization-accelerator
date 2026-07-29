"""
검증 오케스트레이터 모듈

검증 전체 플로우를 제어한다:
  1. 테스트 케이스(JSON) 로드
  2. Java Validator(브리지)로 소스/타겟 실행 (배치)
  3. 결과 비교 (Comparator)
  4. 리포트 생성 (Reporter)

의존성(bridge/comparator/reporter)은 주입 가능해 테스트가 용이하다.
개별 TC 로드 실패는 건너뛰고 계속한다 (전체 중단 방지).

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - ValidationOrchestrator.validate_all: TC 로드→검증→비교→리포트
  - load_test_cases(디렉토리 순회), run_id 생성은 호출측 주입
2026-07-29 | Claude | 성능 리포트용 tc_meta 매핑 주입
  - _build_tc_meta: tc_id -> {sql_id,namespace,mapper} (tc_id 파싱 회피)
  - generate_all_reports에 tc_meta 전달 → sql_id별 시간 격차 집계
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from oma.validation.comparator import ResultComparator
from oma.validation.java_bridge import JavaValidationBridge
from oma.validation.reporter import ValidationReporter
from oma.utils.exceptions import ValidationError

logger = logging.getLogger(__name__)


class ValidationOrchestrator:
    """
    검증 오케스트레이터

    Attributes:
        bridge: JavaValidationBridge (Java 검증 실행)
        comparator: ResultComparator (결과 비교)
        reporter: ValidationReporter (리포트 생성)
    """

    def __init__(
        self,
        bridge: JavaValidationBridge,
        comparator: ResultComparator,
        reporter: ValidationReporter,
    ) -> None:
        """
        초기화 (의존성 주입)

        Args:
            bridge: Java 검증 브리지
            comparator: 결과 비교기
            reporter: 리포트 생성기
        """
        self.bridge = bridge
        self.comparator = comparator
        self.reporter = reporter

    def validate_all(self, testcase_dir: str) -> Dict[str, Any]:
        """
        디렉토리의 모든 TC를 검증하고 리포트를 생성한다.

        Args:
            testcase_dir: TC JSON 파일 디렉토리

        Returns:
            요약 통계 dict (reporter.build_summary 결과)
        """
        test_cases = self.load_test_cases(testcase_dir)
        if not test_cases:
            logger.warning("검증할 테스트 케이스가 없습니다: %s", testcase_dir)
            return self.reporter.generate_all_reports([])

        logger.info("검증 시작: TC %d개", len(test_cases))

        # 성능 리포트에서 tc_id를 sql_id로 그룹핑하기 위한 메타 매핑 (tc 파싱 없이 원본 사용)
        tc_meta = self._build_tc_meta(test_cases)

        # 1) Java 검증 (배치)
        java_results = self.bridge.validate_batch(test_cases)

        # 2) 결과 비교
        comparisons = [self.comparator.compare(r) for r in java_results]

        # 3) 리포트 생성
        summary = self.reporter.generate_all_reports(comparisons, tc_meta)
        return summary

    @staticmethod
    def _build_tc_meta(test_cases: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
        """
        TC 리스트에서 tc_id -> {sql_id, namespace, mapper} 매핑을 만든다.

        성능 리포트가 tc_id를 sql_id로 집계할 때 tc_id 문자열을 파싱하지 않고
        원본 TC 필드를 그대로 쓰기 위함 (mapper/sql_id에 언더스코어가 섞여 파싱 불가).

        Args:
            test_cases: TC dict 리스트

        Returns:
            tc_id -> 메타 dict
        """
        meta: Dict[str, Dict[str, str]] = {}
        for tc in test_cases:
            tc_id = tc.get("test_case_id")
            if not tc_id:
                continue
            meta[tc_id] = {
                "sql_id": tc.get("sql_id", ""),
                "namespace": tc.get("namespace", ""),
                "mapper": tc.get("mapper", ""),
            }
        return meta

    def load_test_cases(self, testcase_dir: str) -> List[Dict[str, Any]]:
        """
        디렉토리에서 TC JSON 파일들을 로드한다 (개별 실패는 건너뜀).

        Args:
            testcase_dir: TC 디렉토리

        Returns:
            TC dict 리스트 (파일명 정렬 순)

        Raises:
            ValidationError: 디렉토리가 없을 때
        """
        if not os.path.isdir(testcase_dir):
            raise ValidationError(
                "테스트 케이스 디렉토리를 찾을 수 없습니다", {"dir": testcase_dir}
            )

        test_cases: List[Dict[str, Any]] = []
        for fname in sorted(os.listdir(testcase_dir)):
            if not fname.endswith(".json"):
                continue
            path = os.path.join(testcase_dir, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    test_cases.append(json.load(f))
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("TC 로드 실패 (건너뜀): %s - %s", fname, e)

        return test_cases

    @classmethod
    def from_config(
        cls,
        config: Any,
        source_credentials: Dict[str, Any],
        target_credentials: Dict[str, Any],
        run_id: str = "",
    ) -> "ValidationOrchestrator":
        """
        Config 기반으로 오케스트레이터를 구성한다.

        Args:
            config: Config 객체
            source_credentials: 소스 DB 접속 정보
            target_credentials: 타겟 DB 접속 정보
            run_id: 실행 식별자

        Returns:
            ValidationOrchestrator
        """
        bridge = JavaValidationBridge.from_config(
            config, source_credentials, target_credentials
        )
        report_dir = config.get("REPORT_DIR")
        return cls(
            bridge=bridge,
            comparator=ResultComparator(),
            reporter=ValidationReporter(report_dir, run_id=run_id),
        )
