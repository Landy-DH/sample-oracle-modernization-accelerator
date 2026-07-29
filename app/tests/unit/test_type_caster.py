"""
TypeCaster 단위 테스트

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - 컬럼별 캐스팅 판단/바인드 적용(멱등)/전체 리포트/CHAR·미발견 경고 테스트
"""

import json

import pytest

from oma.converter.type_caster import TypeCaster
from oma.dictionary.loader import DictionaryLoader

_DICT = {
    "users.user_id": {
        "data_type": "integer",
        "cast_hint": {"needs_cast_from_string": True, "cast_syntax": "::INTEGER",
                      "needs_trim": False},
    },
    "orders.order_id": {
        "data_type": "bigint",
        "cast_hint": {"needs_cast_from_string": True, "cast_syntax": "::BIGINT",
                      "needs_trim": False},
    },
    "orders.amount": {
        "data_type": "numeric",
        "cast_hint": {"needs_cast_from_string": True, "cast_syntax": "::NUMERIC",
                      "needs_trim": False},
    },
    "users.created_at": {
        "data_type": "timestamp without time zone",
        "cast_hint": {"needs_cast_from_string": True, "cast_syntax": "::TIMESTAMP",
                      "needs_trim": False},
    },
    "users.name": {
        "data_type": "character varying",
        "cast_hint": {"needs_cast_from_string": False, "cast_syntax": None,
                      "needs_trim": False},
    },
    "users.status": {
        "data_type": "character",
        "cast_hint": {"needs_cast_from_string": False, "cast_syntax": None,
                      "needs_trim": True},
    },
}


@pytest.fixture
def caster(tmp_path):
    path = tmp_path / "dict.json"
    path.write_text(json.dumps(_DICT), encoding="utf-8")
    return TypeCaster(DictionaryLoader(str(path)))


def test_cast_for_numeric(caster):
    """숫자 컬럼 → 캐스팅 구문 반환"""
    r = caster.cast_for_column("users.user_id")
    assert r.cast_applied == "::INTEGER"
    assert r.warning is None


def test_cast_for_varchar(caster):
    """varchar → 캐스팅 없음"""
    r = caster.cast_for_column("users.name")
    assert r.cast_applied is None


def test_cast_for_char_warns(caster):
    """CHAR → 캐스팅 없이 경고"""
    r = caster.cast_for_column("users.status")
    assert r.cast_applied is None
    assert r.warning is not None
    assert "CHAR" in r.warning


def test_cast_for_unknown_column_warns(caster):
    """미발견 컬럼 → 경고 + 캐스팅 없음"""
    r = caster.cast_for_column("nope.missing")
    assert r.cast_applied is None
    assert r.warning is not None


def test_apply_bind_cast_basic(caster):
    """바인드 변수에 캐스팅 추가"""
    sql = "WHERE user_id = #{userId}"
    out = caster.apply_bind_cast(sql, "userId", "::INTEGER")
    assert out == "WHERE user_id = #{userId}::INTEGER"


def test_apply_bind_cast_idempotent(caster):
    """이미 캐스팅된 것은 중복 적용 안 함 (멱등)"""
    sql = "WHERE user_id = #{userId}::INTEGER"
    out = caster.apply_bind_cast(sql, "userId", "::INTEGER")
    assert out == sql
    assert out.count("::INTEGER") == 1


def test_apply_bind_cast_multiple_occurrences(caster):
    """같은 바인드 변수가 여러 번 나오면 모두 적용"""
    sql = "a = #{id} OR b = #{id}"
    out = caster.apply_bind_cast(sql, "id", "::INTEGER")
    assert out == "a = #{id}::INTEGER OR b = #{id}::INTEGER"


def test_apply_bind_cast_does_not_touch_other_vars(caster):
    """다른 이름의 바인드 변수는 건드리지 않음"""
    sql = "a = #{userId} AND b = #{userIdx}"
    out = caster.apply_bind_cast(sql, "userId", "::INTEGER")
    assert "#{userId}::INTEGER" in out
    assert "#{userIdx}::INTEGER" not in out
    assert "#{userIdx}" in out


def test_build_type_casts_full(caster):
    """전체 매핑으로 변환 + 리포트 생성"""
    sql = (
        "SELECT * FROM orders o JOIN users u ON o.user_id=u.user_id "
        "WHERE o.order_id = #{orderId} AND o.amount > #{minAmt} "
        "AND u.name = #{name} AND u.created_at > #{since}"
    )
    mapping = {
        "orderId": "orders.order_id",
        "minAmt": "orders.amount",
        "name": "users.name",
        "since": "users.created_at",
    }
    result = caster.build_type_casts(sql, mapping)
    conv = result["converted_sql"]
    assert "#{orderId}::BIGINT" in conv
    assert "#{minAmt}::NUMERIC" in conv
    assert "#{since}::TIMESTAMP" in conv
    assert "#{name}::" not in conv  # varchar 미캐스팅
    # 캐스팅 4건 중 3건 적용
    applied = [c for c in result["type_casts"] if c["cast_applied"]]
    assert len(applied) == 3


def test_build_type_casts_collects_char_warning(caster):
    """CHAR 컬럼 매핑 시 warnings에 경고 수집"""
    result = caster.build_type_casts(
        "WHERE status = #{st}", {"st": "users.status"}
    )
    assert result["warnings"]
    assert "#{st}::" not in result["converted_sql"]
