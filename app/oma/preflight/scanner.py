"""
사전 검증(Pre-flight) 스캐너

변환/검증을 시작하기 전에 매퍼를 스캔해, 자동 처리가 불가능하거나 사전 설정이
필요한 항목을 검출한다. "돌려보기 전에는 모르는" 이슈들을 미리 리포트해서,
사용자가 설정(특수변수 값, 타입 별칭, OGNL 처리 방침)을 채우도록 돕는다.

검출 항목:
  1. ognl_methods    - OGNL 정적 메서드 호출 (@Class@method) — 클래스 필요/치환 대상
  2. dollar_variables- ${} 동적 변수 — 런타임 주입, 값 지정 필요
  3. unknown_type_aliases - resultType/parameterType의 미지 별칭(camelMap 등)
  4. parse_errors    - 엄격 XML 파서로 파싱 불가 (이스케이프 안 된 < 등)
  5. procedure_calls - CALL/EXEC 등 프로시저 (검증 스킵 대상)

파싱은 lxml, 토큰 검출은 str 스캔(정규식 금지 — 15-coding-guidelines.md).
파싱 실패 파일도 "텍스트 스캔"으로 최대한 항목을 뽑아 리포트한다.

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - MapperScanner: scan_dir → PreflightReport, 5개 카테고리 검출
  - 미지 타입 별칭 판별(빌트인 별칭 제외), 설정 템플릿 생성
"""

import logging
import os
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List

from lxml import etree

logger = logging.getLogger(__name__)

# MyBatis 빌트인 타입 별칭 (이건 미지 별칭에서 제외) + 정규 클래스로 간주할 접두어
_BUILTIN_ALIASES = frozenset({
    "string", "byte", "long", "short", "int", "integer", "double", "float",
    "boolean", "date", "decimal", "bigdecimal", "biginteger", "object",
    "map", "hashmap", "list", "arraylist", "collection", "iterator",
    "_int", "_integer", "_long", "_short", "_byte", "_double", "_float",
    "_boolean", "resultset",
})
# 완전한 클래스명(FQCN)으로 간주하는 판단: 점(.)이 포함되면 실제 클래스 → 미지 별칭 아님
# 프로시저 감지 접두어
_PROCEDURE_PREFIXES = ("CALL ", "EXEC ", "EXECUTE ", "{CALL ")
# statement 태그
_STATEMENT_TAGS = frozenset({"select", "insert", "update", "delete"})


@dataclass
class PreflightReport:
    """사전 검증 결과"""

    mapper_count: int = 0
    parsed_ok: int = 0
    ognl_methods: Dict[str, int] = field(default_factory=dict)
    dollar_variables: Dict[str, int] = field(default_factory=dict)
    unknown_type_aliases: Dict[str, int] = field(default_factory=dict)
    parse_errors: List[Dict[str, Any]] = field(default_factory=list)
    procedure_calls: List[str] = field(default_factory=list)


class MapperScanner:
    """
    매퍼 사전 검증 스캐너

    Attributes:
        exclude_dirs: 스캔 제외 디렉토리명 집합
    """

    def __init__(self, exclude_dirs: frozenset = frozenset()) -> None:
        """
        초기화

        Args:
            exclude_dirs: 스캔 제외 디렉토리명 (백업/파이프라인 등)
        """
        self.exclude_dirs = exclude_dirs

    @staticmethod
    def _make_parser() -> "etree.XMLParser":
        """매퍼 파싱용 파서 (외부 DTD 차단, CDATA 보존)."""
        return etree.XMLParser(
            no_network=True, load_dtd=False, resolve_entities=False,
            strip_cdata=False,
        )

    def scan_dir(self, mapper_dir: str) -> PreflightReport:
        """
        디렉토리 내 모든 매퍼를 스캔해 리포트를 만든다.

        Args:
            mapper_dir: 매퍼 디렉토리

        Returns:
            PreflightReport
        """
        report = PreflightReport()
        ognl_counter: Counter = Counter()
        dollar_counter: Counter = Counter()
        alias_counter: Counter = Counter()

        for path in self._iter_mapper_files(mapper_dir):
            report.mapper_count += 1
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            # 토큰 기반 검출은 파싱 성공 여부와 무관하게 수행
            self._scan_ognl(content, ognl_counter)
            self._scan_dollar(content, dollar_counter)
            self._scan_procedures(content, path, mapper_dir, report)

            # 타입 별칭/파싱은 lxml 파싱 시도
            try:
                tree = etree.parse(path, self._make_parser())
                report.parsed_ok += 1
                self._scan_aliases(tree, alias_counter)
            except etree.XMLSyntaxError as e:
                report.parse_errors.append({
                    "file": os.path.relpath(path, mapper_dir),
                    "error": str(e).splitlines()[0] if str(e) else repr(e),
                })

        report.ognl_methods = dict(ognl_counter.most_common())
        report.dollar_variables = dict(dollar_counter.most_common())
        report.unknown_type_aliases = dict(alias_counter.most_common())
        return report

    def _iter_mapper_files(self, mapper_dir: str):
        """매퍼 XML 파일 경로를 순회한다 (._ 및 제외 디렉토리 스킵)."""
        for dirpath, dirs, files in os.walk(mapper_dir):
            dirs[:] = [d for d in dirs if d not in self.exclude_dirs]
            for fname in files:
                if not fname.endswith(".xml") or fname.startswith("._"):
                    continue
                path = os.path.join(dirpath, fname)
                if self._looks_like_mapper(path):
                    yield path

    @staticmethod
    def _looks_like_mapper(path: str) -> bool:
        """매퍼 후보인지 앞부분만 읽어 감지한다."""
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                head = f.read(2048)
        except OSError:
            return False
        return "DTD Mapper" in head or "<mapper" in head

    def _scan_ognl(self, content: str, counter: Counter) -> None:
        """
        OGNL 정적 메서드 호출 @Class@method 를 검출한다 (str 스캔).

        Args:
            content: 매퍼 텍스트
            counter: @Class@method → 건수 누적
        """
        i = 0
        while True:
            at = content.find("@", i)
            if at == -1:
                break
            # @ 다음 클래스명 (FQCN) → 두 번째 @ 까지가 @Class@method
            second = content.find("@", at + 1)
            if second == -1:
                break
            cls = content[at + 1:second]
            # 메서드명: 두 번째 @ 뒤 식별자
            j = second + 1
            method = []
            while j < len(content) and (content[j].isalnum() or content[j] == "_"):
                method.append(content[j])
                j += 1
            # 클래스명이 FQCN(점 포함) 이고 메서드명이 있으면 OGNL 정적 호출로 간주
            if method and "." in cls:
                counter[f"@{cls}@{''.join(method)}"] += 1
            i = j if j > at + 1 else at + 1

    def _scan_dollar(self, content: str, counter: Counter) -> None:
        """
        ${...} 동적 변수를 검출한다 (str 스캔).

        Args:
            content: 매퍼 텍스트
            counter: 변수 루트명 → 건수 누적
        """
        i = 0
        while True:
            start = content.find("${", i)
            if start == -1:
                break
            end = content.find("}", start + 2)
            if end == -1:
                break
            inner = content[start + 2:end].strip()
            # OGNL 프로퍼티 접근(@..) 형태는 dollar 변수로 세지 않음(별도 OGNL 검출)
            root = inner.split(".")[0].split(",")[0].strip()
            if root and not root.startswith("@"):
                counter[root] += 1
            i = end + 1

    def _scan_aliases(self, tree: "etree._ElementTree", counter: Counter) -> None:
        """
        resultType/parameterType 중 미지 타입 별칭을 검출한다.

        점(.)이 포함된 FQCN이나 빌트인 별칭은 제외하고, 그 외(camelMap 등)만 센다.

        Args:
            tree: 파싱된 매퍼
            counter: 별칭 → 건수 누적
        """
        for el in tree.getroot().iter():
            if not isinstance(el.tag, str):
                continue
            for attr in ("resultType", "parameterType"):
                value = el.get(attr)
                if not value:
                    continue
                if "." in value:
                    continue  # FQCN → 정상 클래스
                if value.lower() in _BUILTIN_ALIASES:
                    continue  # 빌트인 별칭
                counter[value] += 1

    def _scan_procedures(
        self, content: str, path: str, mapper_dir: str, report: PreflightReport
    ) -> None:
        """
        프로시저 호출(CALL/EXEC 등) 포함 매퍼를 검출한다.

        Args:
            content: 매퍼 텍스트 (대문자 정규화해 검사)
            path: 파일 경로
            mapper_dir: 기준 디렉토리
            report: 결과 누적
        """
        upper = content.upper()
        if any(p in upper for p in _PROCEDURE_PREFIXES):
            rel = os.path.relpath(path, mapper_dir)
            if rel not in report.procedure_calls:
                report.procedure_calls.append(rel)

    @staticmethod
    def to_dict(report: PreflightReport) -> Dict[str, Any]:
        """PreflightReport를 직렬화 가능한 dict로 변환한다."""
        return {
            "mapper_count": report.mapper_count,
            "parsed_ok": report.parsed_ok,
            "parse_error_count": len(report.parse_errors),
            "ognl_methods": report.ognl_methods,
            "dollar_variables": report.dollar_variables,
            "unknown_type_aliases": report.unknown_type_aliases,
            "parse_errors": report.parse_errors,
            "procedure_calls": report.procedure_calls,
        }

    @staticmethod
    def build_config_template(report: PreflightReport) -> Dict[str, Any]:
        """
        검출 결과로부터 사용자가 채울 설정 템플릿을 만든다.

        Args:
            report: 스캔 결과

        Returns:
            설정 템플릿 dict (special_variables/type_aliases/ognl 처리 방침)
        """
        return {
            "type_aliases": {
                alias: "java.util.HashMap  # 실제 클래스로 수정하거나 검증용 HashMap 유지"
                for alias in report.unknown_type_aliases
            },
            "special_variables": {
                var: {"oracle": "", "postgres": ""}
                for var in report.dollar_variables
            },
            "ognl_note": (
                "OGNL 정적 메서드는 실전에서 고객 클래스를 classpath에 등록하거나, "
                "테스트용으로 substitute_special_variables.py의 ognl_methods로 치환"
            ),
        }
