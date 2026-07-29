"""
동적 SQL 테스트 케이스 생성 모듈

MyBatis 매퍼 조각의 동적 SQL(<if>/<choose>/<foreach>) 분기를 분석해 테스트 케이스를
생성한다. 각 TC는 파라미터 조합 + 기대 분기 + 딕셔너리 샘플 값으로 구성된다.

설계 원칙 (15-coding-guidelines.md 준수):
  - 동적 태그 추출은 lxml.etree로 수행 (XML 구조 → 결정론적, 정규식 아님)
  - #{param} 바인드 변수 추출은 단순 토큰 스캔(str.find) — SQL 파싱이 아니라
    MyBatis 플레이스홀더 감지 (DBLINK 감지 같은 허용된 단순 패턴 감지에 해당)
  - test 조건의 의미 해석/파라미터-컬럼 매핑 추론은 LLM(변환 단계)의 몫.
    여기서는 구조적으로 추출 가능한 분기와 파라미터만 다룬다.

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - TestCaseGenerator: 동적 태그 추출, 시나리오(레벨별) 생성, 샘플 값 채움
  - <if> 참/거짓, <foreach> 0/1/N, <choose> when/otherwise 커버리지
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from lxml import etree

from oma.dictionary.loader import DictionaryLoader

logger = logging.getLogger(__name__)

# foreach 다중 케이스에서 생성할 항목 수
_FOREACH_MULTI_COUNT = 3
# 분기 수에 따른 시나리오 전략 경계
_EXHAUSTIVE_MAX_BRANCHES = 2   # 이하: 가능한 조합 위주
_STANDARD_MAX_BRANCHES = 4     # 이하: 표준(단일+최소+최대)

# 딕셔너리 샘플이 없을 때 타입별 기본 대체 값
_DEFAULT_SAMPLE_BY_KIND = {
    "numeric": 1,
    "datetime": "2026-01-01 00:00:00",
    "string": "SAMPLE",
}


@dataclass
class DynamicElement:
    """추출된 동적 SQL 요소"""

    kind: str            # 'if' | 'choose' | 'foreach'
    test: Optional[str]  # if/when의 test 조건식 (원본 그대로)
    collection: Optional[str]  # foreach의 collection 속성
    params: List[str] = field(default_factory=list)  # 이 요소 안의 #{param} 목록
    when_tests: List[str] = field(default_factory=list)  # choose의 when test 목록
    has_otherwise: bool = False


@dataclass
class TestCase:
    """단일 테스트 케이스"""

    test_case_id: str
    mapper: str
    sql_id: str
    description: str
    parameters: Dict[str, Any]
    expected_branches: List[str]
    namespace: Optional[str] = None


class TestCaseGenerator:
    """
    동적 SQL 테스트 케이스 생성기

    Attributes:
        loader: DictionaryLoader (샘플 값 조회용, 선택)
    """

    def __init__(self, loader: Optional[DictionaryLoader] = None) -> None:
        """
        초기화

        Args:
            loader: DictionaryLoader (없으면 타입 기본값 사용)
        """
        self.loader = loader

    # ------------------------------------------------------------------ 추출

    def extract_dynamic_elements(self, fragment_content: str) -> List[DynamicElement]:
        """
        조각 XML에서 동적 SQL 요소를 추출한다 (lxml).

        Args:
            fragment_content: 단일 statement의 XML 문자열

        Returns:
            DynamicElement 리스트 (문서 순서)
        """
        parser = etree.XMLParser(
            no_network=True, load_dtd=False, resolve_entities=False,
            strip_cdata=False, recover=True,
        )
        try:
            root = etree.fromstring(fragment_content.encode("utf-8"), parser)
        except etree.XMLSyntaxError:
            logger.warning("동적 요소 추출용 파싱 실패 (빈 목록 반환)")
            return []
        if root is None:
            return []

        elements: List[DynamicElement] = []
        # iter로 하위 모든 동적 태그 순회 (중첩 포함)
        for el in root.iter():
            if not isinstance(el.tag, str):
                continue
            if el.tag == "if":
                elements.append(
                    DynamicElement(
                        kind="if",
                        test=el.get("test"),
                        collection=None,
                        params=self._collect_params(el),
                    )
                )
            elif el.tag == "foreach":
                elements.append(
                    DynamicElement(
                        kind="foreach",
                        test=None,
                        collection=el.get("collection"),
                        params=self._collect_params(el),
                    )
                )
            elif el.tag == "choose":
                whens = [w.get("test") for w in el.findall("when")]
                elements.append(
                    DynamicElement(
                        kind="choose",
                        test=None,
                        collection=None,
                        params=self._collect_params(el),
                        when_tests=[w for w in whens if w],
                        has_otherwise=el.find("otherwise") is not None,
                    )
                )
        return elements

    @staticmethod
    def _collect_params(element: Any) -> List[str]:
        """
        요소의 텍스트/꼬리에서 #{param} 바인드 변수명을 추출한다 (토큰 스캔).

        정규식 미사용. #{...} 안의 첫 식별자(점/콤마 앞)를 파라미터명으로 본다.
        예: #{ageRange.min} → ageRange, #{userId} → userId

        Args:
            element: lxml 요소

        Returns:
            중복 제거된 파라미터명 리스트 (등장 순서 유지)
        """
        # tail(닫는 태그 뒤 형제 텍스트)은 이 요소 소속이 아니므로 제외한다.
        # lxml의 tostring은 tail을 포함하므로, 임시로 떼어내고 직렬화한다.
        saved_tail = element.tail
        element.tail = None
        try:
            text = etree.tostring(element, encoding="unicode")
        finally:
            element.tail = saved_tail
        return TestCaseGenerator._scan_params(text)

    @staticmethod
    def _scan_params(text: str) -> List[str]:
        """
        텍스트에서 #{param} 바인드 변수명을 추출한다 (토큰 스캔, 중복 제거).

        Args:
            text: 대상 문자열

        Returns:
            파라미터 루트명 리스트 (등장 순서 유지)
        """
        params: List[str] = []
        seen = set()
        i = 0
        while True:
            start = text.find("#{", i)
            if start == -1:
                break
            end = text.find("}", start + 2)
            if end == -1:
                break
            inner = text[start + 2 : end].strip()
            name = TestCaseGenerator._param_root(inner)
            if name and name not in seen:
                seen.add(name)
                params.append(name)
            i = end + 1
        return params

    def _static_params(self, fragment_content: str, elements: List[DynamicElement]) -> List[str]:
        """
        동적 태그에 속하지 않은 정적(필수) 파라미터명을 구한다.

        조각 전체의 #{param} 집합에서 동적 요소(if/choose/foreach)가 소유한
        파라미터를 뺀 나머지. INSERT VALUES/UPDATE SET/WHERE 등 항상 실행되는
        위치의 파라미터로, 모든 TC 시나리오에 채워야 한다.

        Args:
            fragment_content: 조각 XML
            elements: 추출된 동적 요소들

        Returns:
            정적 파라미터명 리스트 (순서 유지)
        """
        all_params = self._scan_params(fragment_content)
        dynamic = set()
        for el in elements:
            dynamic.update(el.params)
        return [p for p in all_params if p not in dynamic]

    @staticmethod
    def _param_root(inner: str) -> str:
        """
        #{...} 내부 문자열에서 파라미터 루트명을 뽑는다.

        'ageRange.min' → 'ageRange', 'id, jdbcType=INTEGER' → 'id'

        Args:
            inner: 중괄호 내부 문자열

        Returns:
            파라미터 루트명
        """
        # 구분자(., ,, 공백) 이전까지가 루트명
        for sep in (".", ",", " "):
            idx = inner.find(sep)
            if idx != -1:
                inner = inner[:idx]
        return inner.strip()

    # ------------------------------------------------------------------ 생성

    def generate(
        self,
        mapper_name: str,
        sql_id: str,
        fragment_content: str,
        param_columns: Optional[Dict[str, str]] = None,
        namespace: Optional[str] = None,
    ) -> List[TestCase]:
        """
        조각으로부터 테스트 케이스 목록을 생성한다.

        Args:
            mapper_name: 매퍼 이름
            sql_id: statement id
            fragment_content: 조각 XML
            param_columns: {param -> "table.column"} 매핑 (선택; 샘플 값 조회용)
            namespace: 매퍼 namespace (검증 시 statement 조회 키에 필요)

        Returns:
            TestCase 리스트
        """
        param_columns = param_columns or {}
        elements = self.extract_dynamic_elements(fragment_content)
        if_params = self._ordered_if_params(elements)
        choose_els = [e for e in elements if e.kind == "choose"]
        foreach_els = [e for e in elements if e.kind == "foreach"]

        # 정적(필수) 파라미터: 조각의 모든 #{param} 중 동적 태그에 속하지 않은 것.
        # INSERT VALUES/UPDATE SET/WHERE 등 항상 실행되는 위치의 파라미터로,
        # 모든 시나리오에 채워야 NOT NULL/컬럼수 제약을 만족한다.
        base_params = self._static_params(fragment_content, elements)

        scenarios = self._build_scenarios(if_params, choose_els, foreach_els)

        test_cases: List[TestCase] = []
        for idx, scenario in enumerate(scenarios, start=1):
            params = self._materialize_params(scenario, param_columns, base_params)
            tc_id = f"{mapper_name}_{sql_id}_tc{idx:03d}"
            test_cases.append(
                TestCase(
                    test_case_id=tc_id,
                    mapper=mapper_name,
                    sql_id=sql_id,
                    description=scenario["description"],
                    parameters=params,
                    expected_branches=scenario["branches"],
                    namespace=namespace,
                )
            )
        return test_cases

    @staticmethod
    def _ordered_if_params(elements: List[DynamicElement]) -> List[str]:
        """<if> 요소들의 파라미터를 순서 유지하며 평탄화(중복 제거)한다."""
        result: List[str] = []
        seen = set()
        for e in elements:
            if e.kind != "if":
                continue
            for p in e.params:
                if p not in seen:
                    seen.add(p)
                    result.append(p)
        return result

    def _build_scenarios(
        self,
        if_params: List[str],
        choose_els: List[DynamicElement],
        foreach_els: List[DynamicElement],
    ) -> List[Dict[str, Any]]:
        """
        분기 요소로부터 시나리오(활성 파라미터 조합) 목록을 만든다.

        전략:
          - <if>: 모두 비활성(최소) + 각 파라미터 단일 활성 + 모두 활성(최대)
          - <choose>: 각 when 및 otherwise 케이스
          - <foreach>: 0개 / 1개 / N개 케이스
        분기가 없으면 기본 케이스 1개.

        Args:
            if_params: <if> 파라미터 목록
            choose_els: choose 요소 목록
            foreach_els: foreach 요소 목록

        Returns:
            시나리오 dict 목록 ({description, branches, active(dict)})
        """
        scenarios: List[Dict[str, Any]] = []

        # 1) <if> 시나리오
        if if_params:
            scenarios.append(
                {"description": "모든 if 조건 비활성 (최소)",
                 "branches": [], "active": {}}
            )
            # 분기 수가 적으면 단일 활성 모두 생성, 많아도 대표로 각 1회
            for p in if_params:
                scenarios.append(
                    {"description": f"{p}만 활성",
                     "branches": [f"if:{p}"],
                     "active": {p: True}}
                )
            if len(if_params) > 1:
                scenarios.append(
                    {"description": "모든 if 조건 활성 (최대)",
                     "branches": [f"if:{p}" for p in if_params],
                     "active": {p: True for p in if_params}}
                )

        # 2) <choose> 시나리오 (각 when + otherwise)
        for ci, choose in enumerate(choose_els):
            for wi, test in enumerate(choose.when_tests):
                scenarios.append(
                    {"description": f"choose[{ci}] when: {test}",
                     "branches": [f"when:{test}"],
                     "active": {}}
                )
            if choose.has_otherwise:
                scenarios.append(
                    {"description": f"choose[{ci}] otherwise",
                     "branches": [f"choose[{ci}]:otherwise"],
                     "active": {}}
                )

        # 3) <foreach> 시나리오 (0/1/N)
        for foreach in foreach_els:
            coll = foreach.collection or "items"
            scenarios.append(
                {"description": f"foreach {coll}: 빈 리스트",
                 "branches": [f"foreach:{coll}:0"],
                 "active": {}, "foreach": {coll: 0}}
            )
            scenarios.append(
                {"description": f"foreach {coll}: 단일 항목",
                 "branches": [f"foreach:{coll}:1"],
                 "active": {}, "foreach": {coll: 1}}
            )
            scenarios.append(
                {"description": f"foreach {coll}: 다중 항목",
                 "branches": [f"foreach:{coll}:{_FOREACH_MULTI_COUNT}"],
                 "active": {}, "foreach": {coll: _FOREACH_MULTI_COUNT}}
            )

        # 분기가 전혀 없으면 기본 케이스 1개
        if not scenarios:
            scenarios.append(
                {"description": "정적 SQL (분기 없음)",
                 "branches": [], "active": {}}
            )
        return scenarios

    def _materialize_params(
        self,
        scenario: Dict[str, Any],
        param_columns: Dict[str, str],
        base_params: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        시나리오의 활성 파라미터 + 정적(필수) 파라미터에 실제 값을 채운다.

        정적 파라미터(base_params)는 모든 시나리오에 항상 포함해 INSERT VALUES/
        WHERE 등의 NOT NULL·컬럼수 제약을 만족시킨다. 값은 딕셔너리 샘플 우선.

        Args:
            scenario: _build_scenarios 항목
            param_columns: {param -> table.column} 매핑
            base_params: 항상 채울 정적 파라미터명 리스트

        Returns:
            파라미터 dict (foreach는 리스트)
        """
        params: Dict[str, Any] = {}

        # 정적 필수 파라미터 먼저 채움
        for param in base_params or []:
            params[param] = self._sample_for_param(param, param_columns)

        for param, active in scenario.get("active", {}).items():
            if active:
                params[param] = self._sample_for_param(param, param_columns)

        for coll, count in scenario.get("foreach", {}).items():
            sample = self._sample_for_param(coll, param_columns)
            params[coll] = [sample for _ in range(count)]

        return params

    def _sample_for_param(
        self, param: str, param_columns: Dict[str, str]
    ) -> Any:
        """
        파라미터의 샘플 값을 딕셔너리에서 조회한다 (없으면 타입 기본값).

        Args:
            param: 파라미터명
            param_columns: {param -> table.column}

        Returns:
            샘플 값
        """
        column = param_columns.get(param)
        if column and self.loader is not None:
            entry = self.loader.lookup(column)
            if entry.get("found"):
                max_len = entry.get("char_max_length")
                sample = entry.get("sample_value")
                if sample is not None:
                    return self._fit_length(sample, max_len)
                return self._default_by_type(entry.get("data_type", ""), max_len)
        return _DEFAULT_SAMPLE_BY_KIND["string"]

    @staticmethod
    def _fit_length(value: Any, max_len: Any) -> Any:
        """
        문자열 값을 컬럼 길이 제한에 맞게 자른다 (숫자/None은 그대로).

        char_max_length가 있는 문자 컬럼에 긴 문자열을 넣으면 길이 초과 오류가
        나므로, 문자열 샘플/기본값을 max_len으로 절단한다.

        Args:
            value: 원본 값
            max_len: 컬럼 최대 길이 (없으면 제한 없음)

        Returns:
            길이 조정된 값
        """
        if isinstance(value, str) and isinstance(max_len, int) and max_len > 0:
            return value[:max_len]
        return value

    @staticmethod
    def _default_by_type(data_type: str, max_len: Any = None) -> Any:
        """data_type에 맞는 기본 샘플 값을 반환한다 (문자열은 길이 제한 반영)."""
        dt = (data_type or "").lower()
        numeric = ("int", "numeric", "decimal", "real", "double", "serial")
        datetime = ("timestamp", "date", "time")
        if any(k in dt for k in numeric):
            return _DEFAULT_SAMPLE_BY_KIND["numeric"]
        if any(k in dt for k in datetime):
            return _DEFAULT_SAMPLE_BY_KIND["datetime"]
        # 문자열: 길이 제한이 있으면 그에 맞춰 자름 (예: char(1) → "S")
        return TestCaseGenerator._fit_length(
            _DEFAULT_SAMPLE_BY_KIND["string"], max_len
        )

    @staticmethod
    def to_dict(test_case: TestCase) -> Dict[str, Any]:
        """TestCase를 JSON 직렬화 가능한 dict로 변환한다."""
        return {
            "test_case_id": test_case.test_case_id,
            "mapper": test_case.mapper,
            "namespace": test_case.namespace,
            "sql_id": test_case.sql_id,
            "description": test_case.description,
            "parameters": test_case.parameters,
            "expected_branches": test_case.expected_branches,
        }
