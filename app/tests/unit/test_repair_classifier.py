"""
오류유형 분류기(classifier) 단위 테스트

변경 이력:
2026-07-28 | OMA Team | 초기 생성
  - _sides trailing '|' 제거, 양면 동일=오탐(F), target 단면 세부분류, 안정번호
"""

from oma.repair import classifier


def test_sides_strips_trailing_separator():
    """source 조각 끝의 ' | ' 구분자가 제거되어 양면 비교가 어긋나지 않는다."""
    note = "source: ERROR: boom | target: ERROR: boom"
    src, tgt = classifier._sides(note)
    assert src == "ERROR: boom"
    assert tgt == "ERROR: boom"


def test_both_error_identical_is_false_positive():
    """양면 동일 에러는 오탐(F)으로 분류한다."""
    note = "source: ERROR: syntax error at 1 | target: ERROR: syntax error at 1"
    group, category = classifier.classify(note, "execution_error")
    assert group == classifier.GROUP_FALSE_POSITIVE
    assert category == "both_error_identical"


def test_both_error_differ_is_conversion_suspect():
    """양면이 다른 에러면 변환결함 의심(B)."""
    note = "source: ERROR: aaa | target: ERROR: bbb column does not exist"
    group, _ = classifier.classify(note, "execution_error")
    assert group == classifier.GROUP_CONVERSION_SUSPECT


def test_target_missing_function_is_group_a():
    """타겟 단면 함수 없음 에러는 A(미변환 함수)."""
    note = "target: ERROR: function to_char(numeric) does not exist"
    group, category = classifier.classify(note, "execution_error")
    assert group == classifier.GROUP_UNCONVERTED_FN
    assert category == "target_fn_missing:to_char"


def test_source_only_error_is_false_positive():
    """소스 단면만 실패면 원본 문제 = 오탐(F)."""
    note = "source: ERROR: original problem"
    group, category = classifier.classify(note, "execution_error")
    assert group == classifier.GROUP_FALSE_POSITIVE
    assert category == "source_only_error"


def test_mybatis_not_found_is_tc_misgen():
    """MyBatis 미등록 statement는 비실행조각 TC 오생성(E)."""
    note = "Mapped Statements collection does not contain value for x"
    group, _ = classifier.classify(note, "execution_error")
    assert group == classifier.GROUP_TC_MISGEN


def test_ognl_null_is_testdata():
    """OGNL null 파라미터는 테스트데이터(C)."""
    note = "The expression 'x' evaluated to a null value."
    group, _ = classifier.classify(note, "execution_error")
    assert group == classifier.GROUP_TESTDATA_OGNL


def test_out_of_range_is_testdata_range():
    """타겟 out of range는 값범위 테스트데이터(D)."""
    note = "target: ERROR: timestamp out of range"
    group, _ = classifier.classify(note, "execution_error")
    assert group == classifier.GROUP_TESTDATA_RANGE


def test_non_execution_failure_type_used_directly():
    """execution_error가 아니면 failure_type을 카테고리로 쓴다(B)."""
    group, category = classifier.classify(None, "value_mismatch")
    assert group == classifier.GROUP_CONVERSION_SUSPECT
    assert category == "value_mismatch"


def test_category_number_is_stable_by_group_order():
    """번호는 GROUP_ORDER 기준 안정값(건수 무관)."""
    assert classifier.category_number(classifier.GROUP_UNCONVERTED_FN) == 1
    assert classifier.category_number(classifier.GROUP_FALSE_POSITIVE) == 6


def test_error_signature_ignores_position_and_values():
    """시그니처는 Position/따옴표값 차이를 무시한다."""
    a = classifier._error_signature('ERROR: bad "foo" Position: 12')
    b = classifier._error_signature('ERROR: bad "bar" Position: 99')
    assert a == b
