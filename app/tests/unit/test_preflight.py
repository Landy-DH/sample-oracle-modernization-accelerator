"""
MapperScanner (사전 검증) 단위 테스트

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - OGNL/달러변수/미지별칭/파싱오류/프로시저 검출 및 설정템플릿 테스트
"""

import textwrap

import pytest

from oma.preflight.scanner import MapperScanner


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return str(p)


@pytest.fixture
def scanner():
    return MapperScanner()


_HEADER = (
    '<?xml version="1.0" encoding="UTF-8" ?>\n'
    '<!DOCTYPE mapper PUBLIC "-//mybatis.org//DTD Mapper 3.0//EN" '
    '"http://mybatis.org/dtd/mybatis-3-mapper.dtd">\n'
)


def test_detect_ognl(scanner, tmp_path):
    """OGNL 정적 메서드 검출 + 빈도"""
    _write(tmp_path, "m.xml", _HEADER + """
        <mapper namespace="t.M">
          <select id="a" resultType="map">SELECT 1
            <if test="@com.example.util.StringUtil@isNotEmpty(x)">AND x=#{x}</if>
            <if test="@com.example.util.StringUtil@isNotEmpty(y)">AND y=#{y}</if>
          </select>
        </mapper>
    """)
    r = scanner.scan_dir(str(tmp_path))
    assert r.ognl_methods["@com.example.util.StringUtil@isNotEmpty"] == 2


def test_detect_dollar_variables(scanner, tmp_path):
    """${} 동적 변수 검출"""
    _write(tmp_path, "m.xml", _HEADER + """
        <mapper namespace="t.M">
          <select id="a" resultType="map">SELECT * FROM ${tableName}
            ORDER BY ${orderBy}</select>
        </mapper>
    """)
    r = scanner.scan_dir(str(tmp_path))
    assert "tableName" in r.dollar_variables
    assert "orderBy" in r.dollar_variables


def test_detect_unknown_alias(scanner, tmp_path):
    """미지 타입 별칭(camelMap) 검출, 빌트인/FQCN 제외"""
    _write(tmp_path, "m.xml", _HEADER + """
        <mapper namespace="t.M">
          <select id="a" resultType="camelMap">SELECT 1</select>
          <select id="b" resultType="map">SELECT 1</select>
          <select id="c" resultType="com.foo.Bar">SELECT 1</select>
        </mapper>
    """)
    r = scanner.scan_dir(str(tmp_path))
    assert r.unknown_type_aliases.get("camelMap") == 1
    assert "map" not in r.unknown_type_aliases       # 빌트인 제외
    assert "com.foo.Bar" not in r.unknown_type_aliases  # FQCN 제외


def test_detect_parse_error(scanner, tmp_path):
    """이스케이프 안 된 < 로 파싱 실패 검출"""
    _write(tmp_path, "bad.xml", _HEADER + """
        <mapper namespace="t.M">
          <select id="a" resultType="map">SELECT * WHERE ROWNUM < 10</select>
        </mapper>
    """)
    r = scanner.scan_dir(str(tmp_path))
    assert len(r.parse_errors) == 1
    assert r.parse_errors[0]["file"] == "bad.xml"


def test_detect_procedure(scanner, tmp_path):
    """프로시저 호출 검출"""
    _write(tmp_path, "m.xml", _HEADER + """
        <mapper namespace="t.M">
          <select id="a" statementType="CALLABLE">CALL my_proc(#{a})</select>
        </mapper>
    """)
    r = scanner.scan_dir(str(tmp_path))
    assert "m.xml" in r.procedure_calls


def test_ognl_detected_even_if_parse_fails(scanner, tmp_path):
    """파싱 실패해도 토큰(OGNL/달러)은 텍스트 스캔으로 검출"""
    _write(tmp_path, "bad.xml", _HEADER + """
        <mapper namespace="t.M">
          <select id="a" resultType="map">SELECT * WHERE ROWNUM < 10
            <if test="@com.example.util.StringUtil@isEmpty(z)">x</if></select>
        </mapper>
    """)
    r = scanner.scan_dir(str(tmp_path))
    assert len(r.parse_errors) == 1                       # 파싱은 실패
    assert r.ognl_methods.get("@com.example.util.StringUtil@isEmpty") == 1  # 그래도 검출


def test_mapper_count(scanner, tmp_path):
    """매퍼 수/파싱성공 집계"""
    _write(tmp_path, "a.xml", _HEADER + '<mapper namespace="a"><select id="s" resultType="map">SELECT 1</select></mapper>')
    _write(tmp_path, "b.xml", _HEADER + '<mapper namespace="b"><select id="s" resultType="map">SELECT 2</select></mapper>')
    r = scanner.scan_dir(str(tmp_path))
    assert r.mapper_count == 2
    assert r.parsed_ok == 2


def test_config_template(scanner, tmp_path):
    """설정 템플릿: 미지별칭/달러변수 항목 생성"""
    _write(tmp_path, "m.xml", _HEADER + """
        <mapper namespace="t.M">
          <select id="a" resultType="camelMap">SELECT * FROM ${tbl}</select>
        </mapper>
    """)
    r = scanner.scan_dir(str(tmp_path))
    tmpl = MapperScanner.build_config_template(r)
    assert "camelMap" in tmpl["type_aliases"]
    assert "tbl" in tmpl["special_variables"]


def test_to_dict_serializable(scanner, tmp_path):
    """리포트 dict 직렬화"""
    import json
    _write(tmp_path, "m.xml", _HEADER + '<mapper namespace="a"><select id="s" resultType="map">SELECT 1</select></mapper>')
    r = scanner.scan_dir(str(tmp_path))
    json.dumps(MapperScanner.to_dict(r))
