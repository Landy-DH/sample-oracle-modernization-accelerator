"""
Converter 통합 테스트 (LLM mock, 실제 Bedrock 호출 없음)

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - 변환 성공/수동검토 스킵/LLM 실패/딕셔너리 subset/TC 통합 테스트
"""

import json

import pytest

from oma.converter.converter import Converter
from oma.converter.sql_analyzer import SqlAnalyzer
from oma.dictionary.loader import DictionaryLoader
from oma.fragmenter.splitter import Fragment
from oma.utils.config import Config
from oma.utils.exceptions import LLMError

_DICT = {
    "users.user_id": {"table": "users", "column": "user_id",
                      "data_type": "integer", "sample_value": 12345,
                      "cast_hint": {"cast_syntax": "::INTEGER"}},
    "users.name": {"table": "users", "column": "name",
                   "data_type": "character varying", "sample_value": "Alice",
                   "cast_hint": {"cast_syntax": None}},
}


class _FakeLLM:
    """invoke_json을 흉내내는 fake LLM"""

    def __init__(self, response=None, raise_error=False):
        self._response = response or {}
        self._raise = raise_error
        self.last_prompt = None
        self.last_system = None

    def invoke_json(self, prompt, system=None, max_tokens=None):
        self.last_prompt = prompt
        self.last_system = system
        if self._raise:
            raise LLMError("boom")
        return self._response


@pytest.fixture
def loader(tmp_path):
    path = tmp_path / "d.json"
    path.write_text(json.dumps(_DICT), encoding="utf-8")
    return DictionaryLoader(str(path))


@pytest.fixture
def config(tmp_path):
    prop = tmp_path / "oma.properties"
    prop.write_text("LLM_LARGE_SQL_THRESHOLD=50000\n", encoding="utf-8")
    return Config(str(prop))


def _fragment(content, sql_id="getUser", statement_type="select"):
    return Fragment(
        mapper_name="UserMapper", namespace="ns", sql_id=sql_id,
        statement_type=statement_type, content=content, source_file="UserMapper.xml",
    )


def _converter(loader, config, llm):
    return Converter(llm, loader, SqlAnalyzer(config))


def test_convert_success(loader, config):
    """LLM 성공 응답 → converted_sql/type_casts 반영"""
    llm = _FakeLLM({
        "conversion_status": "success",
        "converted_sql": "<select id='getUser'>... #{userId}::INTEGER ...</select>",
        "type_casts": [{"column": "users.user_id", "converted": "#{userId}::INTEGER"}],
        "warnings": [],
    })
    conv = _converter(loader, config, llm)
    frag = _fragment("<select id='getUser'>WHERE user_id = #{userId}</select>")
    result = conv.convert(frag)

    assert result.status == "success"
    assert "::INTEGER" in result.converted_sql
    assert len(result.type_casts) == 1
    assert result.error is None


def test_convert_passes_system_prompt(loader, config):
    """LLM 호출 시 system 프롬프트가 전달됨"""
    llm = _FakeLLM({"converted_sql": "x"})
    conv = _converter(loader, config, llm)
    conv.convert(_fragment("<select id='g'>SELECT 1</select>"))
    assert llm.last_system is not None
    assert "PostgreSQL" in llm.last_system


def test_manual_review_skips_llm(loader, config):
    """매우 크고 복잡 → LLM 호출 없이 skipped"""
    llm = _FakeLLM({"converted_sql": "should not be used"})
    conv = _converter(loader, config, llm)
    # 크고(>50000자) 매우 복잡(<if> 다수)한 조각
    big = "<select id='big'>" + "<if test='x'>a</if>" * 3000 + "x" * 60000 + "</select>"
    result = conv.convert(_fragment(big, sql_id="big"))

    assert result.status == "skipped"
    assert result.manual_review_required is True
    assert llm.last_prompt is None  # LLM 미호출
    assert result.converted_sql == result.original_sql


def test_llm_failure_keeps_original(loader, config):
    """LLM 실패 → status=failed, 원본 유지, 수동검토 플래그"""
    llm = _FakeLLM(raise_error=True)
    conv = _converter(loader, config, llm)
    frag = _fragment("<select id='g'>WHERE user_id = #{userId}</select>")
    result = conv.convert(frag)

    assert result.status == "failed"
    assert result.converted_sql == result.original_sql
    assert result.manual_review_required is True
    assert result.error is not None


def test_dictionary_subset_only_referenced_columns(loader, config):
    """딕셔너리 subset은 조각에 등장하는 컬럼만 포함"""
    conv = _converter(loader, config, _FakeLLM({"converted_sql": "x"}))
    subset = conv.build_dictionary_subset("WHERE user_id = #{userId}")
    assert "users.user_id" in subset
    assert "users.name" not in subset  # name은 조각에 없음


def test_subset_scoped_by_table(tmp_path, config):
    """같은 컬럼명이 여러 테이블에 있어도 조각의 테이블로 한정"""
    d = {
        "twork_ib.ctkey": {"table": "twork_ib", "column": "ctkey",
                           "data_type": "character varying", "cast_hint": {}},
        "other_tbl.ctkey": {"table": "other_tbl", "column": "ctkey",
                            "data_type": "integer", "cast_hint": {}},
    }
    path = tmp_path / "d.json"
    path.write_text(json.dumps(d), encoding="utf-8")
    loader = DictionaryLoader(str(path))
    conv = _converter(loader, config, _FakeLLM({"converted_sql": "x"}))

    subset = conv.build_dictionary_subset(
        "UPDATE TWORK_IB SET x=1 WHERE CTKEY = #{ctkey}"
    )
    assert "twork_ib.ctkey" in subset
    assert "other_tbl.ctkey" not in subset  # 다른 테이블은 제외


def test_test_cases_generated_for_dynamic_sql(loader, config):
    """동적 SQL 조각 → TC 생성됨"""
    llm = _FakeLLM({"converted_sql": "x", "conversion_status": "success"})
    conv = _converter(loader, config, llm)
    frag = _fragment(
        "<select id='s'>SELECT * FROM users"
        "<where><if test='userId != null'>AND user_id = #{userId}</if></where></select>",
        sql_id="s",
    )
    result = conv.convert(frag)
    assert len(result.test_cases) >= 2  # 최소/활성
    assert all("test_case_id" in tc for tc in result.test_cases)


def test_no_test_cases_for_non_executable_fragments(loader, config):
    """resultMap/sql 조각은 실행 statement가 아니므로 TC를 만들지 않는다."""
    llm = _FakeLLM({"converted_sql": "x", "conversion_status": "success"})
    conv = _converter(loader, config, llm)
    for stype, content in (
        ("resultMap", "<resultMap id='r'><result property='a' column='a'/></resultMap>"),
        ("sql", "<sql id='w'>AND user_id = #{userId}</sql>"),
    ):
        result = conv.convert(_fragment(content, sql_id="r", statement_type=stype))
        assert result.test_cases == [], f"{stype} 조각에 TC가 생성됨"


def test_warnings_set_manual_review(loader, config):
    """LLM이 warning 반환 시 manual_review_required True"""
    llm = _FakeLLM({
        "converted_sql": "x",
        "conversion_status": "partial",
        "warnings": [{"severity": "high", "type": "missing_column",
                      "issue": "col not found"}],
    })
    conv = _converter(loader, config, llm)
    result = conv.convert(_fragment("<select id='g'>SELECT 1</select>"))
    assert result.manual_review_required is True
    assert len(result.warnings) == 1
