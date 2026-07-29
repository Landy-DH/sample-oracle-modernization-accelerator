"""
검증 실패 오류유형 분류기

검증 실패 TC의 note(소스/타겟 실행 에러 또는 MyBatis 로딩 에러)를 근거로
오류 유형(category)과 그룹(group)을 판정한다. 설계: design/20-iterative-repair-loop.md §2.

HARD RULE 준수:
  - SQL을 정규식으로 파싱하지 않는다. note(에러 메시지)의 키워드만 감지한다.
  - 함수 매핑을 하드코딩하지 않는다(분류만 하며, 수정 방법은 repairer/LLM이 판단).

note 형태(3종):
  ① 양면: "source: ERROR ... | target: ERROR ..."  → 양쪽 동일하면 오탐(F)
  ② target 단면: "target: ERROR ..."               → 타겟만 실패 = repair 후보
  ③ source 단면: "source: ERROR ..."               → 소스만 실패 = 원본 문제

변경 이력:
2026-07-28 | OMA Team | 초기 생성
  - classify(note, failure_type) → (group, category)
  - 카테고리→안정번호 매핑(GROUP_ORDER), 오탐(F)은 양면 동일 에러만
"""

import re
from typing import Optional, Tuple

# 그룹 정의(안정 순서). 번호는 이 순서 + 카테고리 사전순으로 부여(설계 §2.2).
GROUP_UNCONVERTED_FN = "A_미변환_Oracle함수"
GROUP_CONVERSION_SUSPECT = "B_변환결함_의심"
GROUP_TESTDATA_OGNL = "C_테스트데이터_OGNL파라미터"
GROUP_TESTDATA_RANGE = "D_테스트데이터_값범위"
GROUP_TC_MISGEN = "E_비실행조각_TC오생성"
GROUP_FALSE_POSITIVE = "F_오탐_원본도동일실패"

# 그룹 고정 순서(번호 부여 기준) — 건수와 무관하게 안정
GROUP_ORDER = (
    GROUP_UNCONVERTED_FN,
    GROUP_CONVERSION_SUSPECT,
    GROUP_TESTDATA_OGNL,
    GROUP_TESTDATA_RANGE,
    GROUP_TC_MISGEN,
    GROUP_FALSE_POSITIVE,
)

# repair(재변환) 대상 그룹
REPAIR_GROUPS = frozenset({GROUP_UNCONVERTED_FN, GROUP_CONVERSION_SUSPECT})

# 그룹별 성격/조치 라벨(보고용)
GROUP_META = {
    GROUP_UNCONVERTED_FN: ("변환결함", "repair"),
    GROUP_CONVERSION_SUSPECT: ("변환결함 의심", "repair"),
    GROUP_TESTDATA_OGNL: ("테스트데이터", "tc_fix"),
    GROUP_TESTDATA_RANGE: ("테스트데이터", "tc_fix"),
    GROUP_TC_MISGEN: ("TC생성 이슈", "tc_filter"),
    GROUP_FALSE_POSITIVE: ("오탐", "none"),
}


def _sides(note: str) -> Tuple[str, str]:
    """
    note에서 source/target 에러 문자열을 분리한다(없으면 빈 문자열).

    note는 "source: ... | target: ..." 형태라 source 조각 끝에 구분자 ' | '가
    남는다. 양쪽 동일성 비교가 어긋나지 않도록 trailing 구분자를 제거한다.
    """
    src = tgt = ""
    if "source:" in note:
        src = note.split("source:", 1)[1].split("target:", 1)[0].strip()
        # source | target 구분자로 쓰인 trailing '|' 제거
        src = src.rstrip().rstrip("|").rstrip()
    if "target:" in note:
        tgt = note.split("target:", 1)[1].strip()
    return src, tgt


def _error_signature(err: str) -> str:
    """
    에러 메시지를 비교용으로 정규화한다(Hint/Position/따옴표값/괄호값 제거).

    양면 동일 여부 판정 시 위치·구체값 차이를 무시하고 에러 본질만 비교한다.
    """
    s = err.split("Hint:")[0]
    s = re.sub(r"Position: \d+", "", s)
    s = re.sub(r"=\([^)]*\)", "", s)   # =(값) 제거
    s = re.sub(r'"[^"]*"', '""', s)     # "값" → ""
    return s.strip()[:120]


def classify(note: Optional[str], failure_type: Optional[str]) -> Tuple[str, str]:
    """
    검증 실패의 (group, category)를 판정한다.

    Args:
        note: 검증 상세의 note(에러 메시지). None/빈문자 허용.
        failure_type: 검증기가 매긴 실패 유형(value_mismatch/row_count_mismatch/
            execution_error 등). execution_error가 아니면 그 자체를 카테고리로.

    Returns:
        (group, category) 튜플
    """
    note = note or ""

    # 실행 에러가 아니면 검증기 분류를 그대로 사용(값/행수 불일치 등)
    if failure_type and failure_type != "execution_error":
        return GROUP_CONVERSION_SUSPECT, failure_type

    # MyBatis 로딩 실패 = 비실행 조각(resultMap/sql)에 TC 생성됐거나 매퍼 로딩 문제
    if "Mapped Statements collection does not contain" in note:
        return GROUP_TC_MISGEN, "mybatis_stmt_not_found"

    # OGNL 파라미터 문제(테스트데이터)
    if "evaluated to a null value" in note or "is null for method" in note:
        return GROUP_TESTDATA_OGNL, "ognl_null_param"
    if "no getter for property" in note:
        return GROUP_TESTDATA_OGNL, "ognl_getter_missing"

    src, tgt = _sides(note)

    # 양면 에러 → 동일하면 오탐(F), 다르면 변환결함 의심
    if src and tgt:
        if _error_signature(src) == _error_signature(tgt):
            return GROUP_FALSE_POSITIVE, "both_error_identical"
        return GROUP_CONVERSION_SUSPECT, "both_error_differ"

    # source 단면 → 원본만 실패(원본 문제) = 오탐
    if src and not tgt:
        return GROUP_FALSE_POSITIVE, "source_only_error"

    # target 단면 → 타겟만 실패 = repair 후보
    if tgt and not src:
        return _classify_target_error(tgt)

    return GROUP_CONVERSION_SUSPECT, "unknown"


def _classify_target_error(tgt: str) -> Tuple[str, str]:
    """타겟 단면 에러를 세부 카테고리로 분류한다."""
    if "does not exist" in tgt and "function" in tgt:
        fn = re.search(r"function (\w+)\(", tgt)
        name = fn.group(1) if fn else "unknown"
        return GROUP_UNCONVERTED_FN, f"target_fn_missing:{name}"
    if "column" in tgt and "does not exist" in tgt:
        return GROUP_CONVERSION_SUSPECT, "target_column_missing"
    if "operator does not exist" in tgt:
        return GROUP_CONVERSION_SUSPECT, "target_operator_type"
    if "invalid reference to FROM" in tgt:
        return GROUP_CONVERSION_SUSPECT, "target_from_alias"
    if "out of range" in tgt:
        return GROUP_TESTDATA_RANGE, "target_data_out_of_range"
    if "too long" in tgt:
        return GROUP_TESTDATA_RANGE, "target_value_too_long"
    return GROUP_CONVERSION_SUSPECT, "target_other"


def category_number(group: str) -> int:
    """
    그룹의 안정 번호(1부터)를 반환한다(GROUP_ORDER 기준).

    건수와 무관하게 그룹당 고정 번호라 반복 루프에서도 번호가 바뀌지 않는다.
    """
    try:
        return GROUP_ORDER.index(group) + 1
    except ValueError:
        return len(GROUP_ORDER) + 1
