"""
SqlAnalyzer 단위 테스트

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - 크기/토큰/복잡도/전략 분류 테스트
"""

import pytest

from oma.converter.sql_analyzer import (
    LEVEL_COMPLEX,
    LEVEL_MODERATE,
    LEVEL_SIMPLE,
    LEVEL_VERY_COMPLEX,
    STRATEGY_CHUNKED,
    STRATEGY_MANUAL_REVIEW,
    STRATEGY_STANDARD,
    STRATEGY_STANDARD_COMPRESSED,
    SqlAnalyzer,
)
from oma.utils.config import Config


@pytest.fixture
def analyzer(tmp_path):
    prop = tmp_path / "oma.properties"
    prop.write_text("LLM_LARGE_SQL_THRESHOLD=100\n", encoding="utf-8")
    return SqlAnalyzer(Config(str(prop)))


def test_basic_counts(analyzer):
    """char/token/JOIN/if/choose 카운팅"""
    sql = "SELECT * FROM a JOIN b ON a.id=b.id <if test='x'>AND x=1</if>"
    a = analyzer.analyze(sql)
    assert a["char_count"] == len(sql)
    assert a["token_estimate"] == len(sql) // 3
    assert a["join_count"] == 1
    assert a["if_count"] == 1


def test_join_case_insensitive(analyzer):
    """JOIN은 대소문자 무관 카운팅"""
    sql = "select * from a join b left join c"
    assert analyzer.analyze(sql)["join_count"] == 2


def test_complexity_formula(analyzer):
    """복잡도 = JOIN + if*2 + choose*3 + foreach*2"""
    sql = "JOIN <if <if <choose <foreach"
    a = analyzer.analyze(sql)
    # join1 + if2*2 + choose1*3 + foreach1*2 = 1+4+3+2 = 10
    assert a["complexity"] == 10


def test_classify_levels(analyzer):
    assert analyzer.classify_complexity(0) == LEVEL_SIMPLE
    assert analyzer.classify_complexity(9) == LEVEL_SIMPLE
    assert analyzer.classify_complexity(10) == LEVEL_MODERATE
    assert analyzer.classify_complexity(29) == LEVEL_MODERATE
    assert analyzer.classify_complexity(30) == LEVEL_COMPLEX
    assert analyzer.classify_complexity(99) == LEVEL_COMPLEX
    assert analyzer.classify_complexity(100) == LEVEL_VERY_COMPLEX


def test_strategy_standard_when_small(analyzer):
    """작은 SQL은 standard"""
    a = analyzer.analyze("SELECT 1")
    assert a["is_large"] is False
    assert a["strategy"] == STRATEGY_STANDARD


def test_strategy_large_simple(analyzer):
    """크지만 단순 → compression (threshold=100)"""
    sql = "SELECT " + "x," * 60  # >100 chars, 복잡도 0
    a = analyzer.analyze(sql)
    assert a["is_large"] is True
    assert a["strategy"] == STRATEGY_STANDARD_COMPRESSED


def test_strategy_large_complex(analyzer):
    """크고 복잡(30~99) → chunked"""
    sql = "JOIN " * 40 + "x" * 100  # join40 → 복잡도 40(complex), 길이>100
    a = analyzer.analyze(sql)
    assert a["is_large"] is True
    assert a["complexity_level"] == LEVEL_COMPLEX
    assert a["strategy"] == STRATEGY_CHUNKED


def test_strategy_large_very_complex(analyzer):
    """크고 매우 복잡(>=100) → manual_review"""
    sql = "<if " * 60 + "x" * 100  # if60*2=120 (very_complex)
    a = analyzer.analyze(sql)
    assert a["strategy"] == STRATEGY_MANUAL_REVIEW


def test_threshold_from_config(tmp_path):
    """대용량 임계값이 config에서 로드됨"""
    prop = tmp_path / "p.properties"
    prop.write_text("LLM_LARGE_SQL_THRESHOLD=5\n", encoding="utf-8")
    az = SqlAnalyzer(Config(str(prop)))
    assert az.analyze("123456")["is_large"] is True
    assert az.analyze("12")["is_large"] is False
