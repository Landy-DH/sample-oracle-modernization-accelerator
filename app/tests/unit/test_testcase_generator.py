"""
TestCaseGenerator 단위 테스트

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - 동적 태그 추출, if/choose/foreach 시나리오, 샘플 값 채움, 파일명 규칙 테스트
"""

import json

import pytest

from oma.dictionary.loader import DictionaryLoader
from oma.testcase.generator import TestCaseGenerator

_IF_FRAGMENT = """
<select id="searchUsers">
  SELECT * FROM users
  <where>
    <if test="userId != null">AND user_id = #{userId}</if>
    <if test="username != null">AND username = #{username}</if>
    <if test="status != null">AND status = #{status}</if>
  </where>
</select>
"""

_FOREACH_FRAGMENT = """
<select id="getByIds">
  SELECT * FROM users WHERE user_id IN
  <foreach collection="userIds" item="id" open="(" separator="," close=")">
    #{id}
  </foreach>
</select>
"""

_CHOOSE_FRAGMENT = """
<select id="getByType">
  SELECT * FROM users
  <where>
    <choose>
      <when test="type == 'id'">user_id = #{value}</when>
      <when test="type == 'name'">username = #{value}</when>
      <otherwise>1=0</otherwise>
    </choose>
  </where>
</select>
"""

_STATIC_FRAGMENT = """
<select id="all">SELECT * FROM users</select>
"""


@pytest.fixture
def gen():
    return TestCaseGenerator()


def test_extract_if_elements(gen):
    """<if> 3개와 각 파라미터 추출"""
    els = gen.extract_dynamic_elements(_IF_FRAGMENT)
    ifs = [e for e in els if e.kind == "if"]
    assert len(ifs) == 3
    assert ifs[0].params == ["userId"]


def test_extract_foreach(gen):
    """<foreach> collection/param 추출"""
    els = gen.extract_dynamic_elements(_FOREACH_FRAGMENT)
    fe = [e for e in els if e.kind == "foreach"]
    assert len(fe) == 1
    assert fe[0].collection == "userIds"
    assert "id" in fe[0].params


def test_extract_choose(gen):
    """<choose> when/otherwise 추출"""
    els = gen.extract_dynamic_elements(_CHOOSE_FRAGMENT)
    ch = [e for e in els if e.kind == "choose"]
    assert len(ch) == 1
    assert len(ch[0].when_tests) == 2
    assert ch[0].has_otherwise is True


def test_param_root_extraction(gen):
    """#{ageRange.min}/#{id, jdbcType=..} 루트명 추출"""
    assert gen._param_root("ageRange.min") == "ageRange"
    assert gen._param_root("id, jdbcType=INTEGER") == "id"
    assert gen._param_root("userId") == "userId"


def test_generate_if_scenarios(gen):
    """if 3개 → 최소 + 단일3 + 최대 = 5개 TC"""
    tcs = gen.generate("UserMapper", "searchUsers", _IF_FRAGMENT)
    assert len(tcs) == 5
    # 최소 케이스
    assert tcs[0].parameters == {}
    # 단일 활성
    assert tcs[1].parameters == {"userId": "SAMPLE"}
    # 최대 케이스
    assert set(tcs[-1].parameters.keys()) == {"userId", "username", "status"}


def test_generate_tc_id_format(gen):
    """TC id 형식: {mapper}_{sqlId}_tc{NNN}"""
    tcs = gen.generate("UserMapper", "searchUsers", _IF_FRAGMENT)
    assert tcs[0].test_case_id == "UserMapper_searchUsers_tc001"
    assert tcs[4].test_case_id == "UserMapper_searchUsers_tc005"


def test_generate_foreach_cases(gen):
    """foreach → 0/1/N 케이스"""
    tcs = gen.generate("M", "getByIds", _FOREACH_FRAGMENT)
    assert len(tcs) == 3
    assert tcs[0].parameters["userIds"] == []
    assert len(tcs[1].parameters["userIds"]) == 1
    assert len(tcs[2].parameters["userIds"]) == 3


def test_generate_choose_cases(gen):
    """choose → when 2개 + otherwise = 3개"""
    tcs = gen.generate("M", "getByType", _CHOOSE_FRAGMENT)
    assert len(tcs) == 3
    branches = [b for tc in tcs for b in tc.expected_branches]
    assert any("otherwise" in b for b in branches)
    assert sum(1 for b in branches if b.startswith("when:")) == 2


def test_generate_static_single_case(gen):
    """분기 없는 정적 SQL → 기본 1개"""
    tcs = gen.generate("M", "all", _STATIC_FRAGMENT)
    assert len(tcs) == 1
    assert tcs[0].parameters == {}


def test_sample_from_dictionary(tmp_path):
    """param_columns 매핑 + 딕셔너리로 실제 샘플 값 채움"""
    d = {"users.user_id": {"data_type": "integer", "sample_value": 12345,
                           "cast_hint": {}}}
    path = tmp_path / "d.json"
    path.write_text(json.dumps(d), encoding="utf-8")
    gen = TestCaseGenerator(DictionaryLoader(str(path)))

    tcs = gen.generate("UserMapper", "searchUsers", _IF_FRAGMENT,
                       param_columns={"userId": "users.user_id"})
    single = next(t for t in tcs if t.parameters.get("userId") is not None)
    assert single.parameters["userId"] == 12345


def test_default_by_type_numeric_when_no_sample(tmp_path):
    """샘플 값 없으면 타입 기반 기본값 (numeric→1)"""
    d = {"t.c": {"data_type": "bigint", "sample_value": None, "cast_hint": {}}}
    path = tmp_path / "d.json"
    path.write_text(json.dumps(d), encoding="utf-8")
    gen = TestCaseGenerator(DictionaryLoader(str(path)))
    frag = '<select id="s"><if test="x != null">AND c = #{x}</if></select>'
    tcs = gen.generate("M", "s", frag, param_columns={"x": "t.c"})
    active = next(t for t in tcs if t.parameters)
    assert active.parameters["x"] == 1


def test_if_params_exclude_tail_text(gen):
    """<if> 뒤(tail)의 정적 파라미터가 if 파라미터에 섞이지 않아야 함 (회귀)"""
    frag = """
    <update id="u">
      UPDATE t SET a = '1'
      <if test="cond == '50'">, b = #{onlyThis}</if>
        , c = #{tailParam}
      WHERE k = #{whereParam}
    </update>
    """
    els = gen.extract_dynamic_elements(frag)
    if_el = next(e for e in els if e.kind == "if")
    assert if_el.params == ["onlyThis"]
    assert "tailParam" not in if_el.params
    assert "whereParam" not in if_el.params


def test_to_dict_serializable(gen):
    """TestCase → dict → JSON 직렬화"""
    tcs = gen.generate("M", "getByIds", _FOREACH_FRAGMENT)
    d = TestCaseGenerator.to_dict(tcs[0])
    json.dumps(d)  # 예외 없어야 함
    assert d["test_case_id"] == "M_getByIds_tc001"
