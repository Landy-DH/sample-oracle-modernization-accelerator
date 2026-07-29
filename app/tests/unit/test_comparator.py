"""
ResultComparator 단위 테스트

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - 일치/행수/컬럼/값/tolerance/스킵/실행오류 비교 테스트
"""

import pytest

from oma.validation.comparator import (
    FAIL_COLUMN,
    FAIL_EXECUTION_ERROR,
    FAIL_ROW_COUNT,
    FAIL_VALUE,
    STATUS_FAILED,
    STATUS_PASSED,
    STATUS_SKIPPED,
    ResultComparator,
)


def _select(rows, columns=None, sampled=False):
    """SELECT 성공 결과 dict 생성 헬퍼"""
    return {
        "success": True, "skipped": False, "sampled": sampled,
        "rows": rows, "columns": columns or (list(rows[0].keys()) if rows else []),
        "rowCount": len(rows),
    }


def _vr(source, target, tc_id="tc1"):
    return {"tcId": tc_id, "status": "ok", "sourceResult": source, "targetResult": target}


@pytest.fixture
def cmp():
    return ResultComparator()


def test_identical_passes(cmp):
    """동일 결과 → passed"""
    rows = [{"id": 1, "name": "A"}]
    c = cmp.compare(_vr(_select(rows), _select(rows)))
    assert c.status == STATUS_PASSED
    assert c.matched is True


def test_row_count_mismatch(cmp):
    """행 수 불일치 → row_count_mismatch"""
    c = cmp.compare(_vr(
        _select([{"id": 1}, {"id": 2}]),
        _select([{"id": 1}]),
    ))
    assert c.status == STATUS_FAILED
    assert c.failure_type == FAIL_ROW_COUNT
    assert c.source_rows == 2 and c.target_rows == 1


def test_column_mismatch(cmp):
    """컬럼 집합 불일치 → column_mismatch"""
    c = cmp.compare(_vr(
        _select([{"id": 1, "name": "A"}]),
        _select([{"id": 1, "nickname": "A"}]),
    ))
    assert c.failure_type == FAIL_COLUMN
    assert c.columns_matched is False


def test_column_case_insensitive(cmp):
    """컬럼 대소문자 무시"""
    c = cmp.compare(_vr(
        _select([{"ID": 1}], columns=["ID"]),
        _select([{"id": 1}], columns=["id"]),
    ))
    assert c.columns_matched is True
    assert c.matched is True


def test_value_mismatch(cmp):
    """값 불일치 → value_mismatch + 상세"""
    c = cmp.compare(_vr(
        _select([{"id": 1, "name": "A"}]),
        _select([{"id": 1, "name": "B"}]),
    ))
    assert c.failure_type == FAIL_VALUE
    assert c.value_differences[0]["column"] == "name"
    assert c.value_differences[0]["source_value"] == "A"


def test_numeric_no_tolerance(cmp):
    """근사(tolerance) 없음: 미세한 부동소수점 차이도 불일치"""
    c = cmp.compare(_vr(
        _select([{"price": 99.99}]),
        _select([{"price": 99.989999999}]),
    ))
    assert c.matched is False
    assert c.failure_type == FAIL_VALUE


def test_numeric_int_float_equivalent(cmp):
    """5 vs 5.0 은 정확 동치로 일치 (근사 아님)"""
    c = cmp.compare(_vr(
        _select([{"n": 5}]),
        _select([{"n": 5.0}]),
    ))
    assert c.matched is True


def test_numeric_different_values(cmp):
    """값이 다르면 불일치"""
    c = cmp.compare(_vr(
        _select([{"price": 100.0}]),
        _select([{"price": 105.0}]),
    ))
    assert c.matched is False
    assert c.failure_type == FAIL_VALUE


def test_char_padding_is_mismatch(cmp):
    """CHAR 패딩(양끝 공백) 차이는 불일치로 판정 (엄격)"""
    c = cmp.compare(_vr(
        _select([{"status": "Y"}]),
        _select([{"status": "Y "}]),
    ))
    assert c.matched is False
    assert c.failure_type == FAIL_VALUE


def test_null_values(cmp):
    """양쪽 NULL은 일치, 한쪽만 NULL은 불일치"""
    assert cmp.compare(_vr(
        _select([{"x": None}]), _select([{"x": None}]))).matched is True
    assert cmp.compare(_vr(
        _select([{"x": None}]), _select([{"x": 1}]))).matched is False


def test_skipped(cmp):
    """프로시저 스킵 → skipped"""
    src = {"success": False, "skipped": True, "skipReason": "procedure"}
    c = cmp.compare(_vr(src, src))
    assert c.status == STATUS_SKIPPED


def test_execution_error(cmp):
    """한쪽 실행 실패 → execution_error"""
    ok = _select([{"id": 1}])
    fail = {"success": False, "skipped": False, "errorMessage": "syntax error",
            "rowCount": 0, "rows": [], "columns": []}
    c = cmp.compare(_vr(ok, fail))
    assert c.failure_type == FAIL_EXECUTION_ERROR
    assert "syntax error" in c.note


def test_java_error_status(cmp):
    """Java 단계 error status → execution_error"""
    c = cmp.compare({"tcId": "tc1", "status": "error", "errorMessage": "no statement"})
    assert c.status == STATUS_FAILED
    assert c.failure_type == FAIL_EXECUTION_ERROR


def test_sampled_note(cmp):
    """샘플링 결과는 note 표시"""
    rows = [{"id": 1}]
    c = cmp.compare(_vr(_select(rows, sampled=True), _select(rows)))
    assert c.note is not None and "샘플" in c.note


def test_to_dict_serializable(cmp):
    """Comparison → dict 직렬화"""
    import json
    c = cmp.compare(_vr(_select([{"id": 1}]), _select([{"id": 1}])))
    json.dumps(ResultComparator.to_dict(c))
