"""
MapperCombiner 단위 테스트

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - 병합/순서·namespace·DOCTYPE 보존/누락·미사용 조각 리포트/에러 테스트
"""

import textwrap

import pytest
from lxml import etree

from oma.fragmenter.splitter import Fragment, MapperSplitter
from oma.merger.combiner import MapperCombiner
from oma.utils.config import Config
from oma.utils.exceptions import ConversionError

_MAPPER_XML = textwrap.dedent(
    """\
    <?xml version="1.0" encoding="UTF-8" ?>
    <!DOCTYPE mapper PUBLIC "-//mybatis.org//DTD Mapper 3.0//EN"
        "http://mybatis.org/dtd/mybatis-3-mapper.dtd">
    <mapper namespace="com.acme.UserMapper">
        <!-- 사용자 조회 -->
        <select id="getUser" resultType="camelMap">
            SELECT * FROM users WHERE user_id = #{userId}
        </select>
        <update id="updateUser">
            UPDATE users SET name = #{name} WHERE user_id = #{userId}
        </update>
    </mapper>
    """
)


@pytest.fixture
def mapper_file(tmp_path):
    path = tmp_path / "UserMapper.xml"
    path.write_text(_MAPPER_XML, encoding="utf-8")
    return str(path)


@pytest.fixture
def config(tmp_path):
    prop = tmp_path / "oma.properties"
    prop.write_text(f"SOURCE_WORKSPACE={tmp_path}\n", encoding="utf-8")
    return Config(str(prop))


def _converted_fragment(sql_id, stype, content):
    return Fragment(
        mapper_name="UserMapper", namespace="com.acme.UserMapper",
        sql_id=sql_id, statement_type=stype, content=content,
        source_file="UserMapper.xml",
    )


@pytest.fixture
def combiner():
    return MapperCombiner()


def test_merge_replaces_statements(combiner, mapper_file):
    """변환 조각으로 statement가 교체됨"""
    frags = [
        _converted_fragment("getUser", "select",
            '<select id="getUser" resultType="camelMap">'
            'SELECT * FROM users WHERE user_id = #{userId}::INTEGER</select>'),
        _converted_fragment("updateUser", "update",
            '<update id="updateUser">UPDATE users SET name = #{name} '
            'WHERE user_id = #{userId}::INTEGER</update>'),
    ]
    result = combiner.merge_to_string(mapper_file, frags)
    assert "#{userId}::INTEGER" in result
    assert result.count("::INTEGER") == 2  # getUser의 WHERE 1 + updateUser의 WHERE 1


def test_merge_preserves_namespace_and_order(combiner, mapper_file):
    """namespace와 statement 순서 보존"""
    frags = [
        _converted_fragment("updateUser", "update",
            '<update id="updateUser">UPDATED</update>'),
        _converted_fragment("getUser", "select",
            '<select id="getUser">GOT</select>'),
    ]
    result = combiner.merge_to_string(mapper_file, frags)
    tree = etree.fromstring(result.encode("utf-8"))
    assert tree.get("namespace") == "com.acme.UserMapper"
    ids = [e.get("id") for e in tree if isinstance(e.tag, str)]
    # 원본 순서(getUser 먼저) 유지 (조각 순서와 무관)
    assert ids == ["getUser", "updateUser"]


def test_merge_preserves_doctype(combiner, mapper_file):
    """DOCTYPE(mybatis dtd) 보존"""
    frags = [_converted_fragment("getUser", "select",
        '<select id="getUser">X</select>')]
    result = combiner.merge_to_string(mapper_file, frags)
    assert "DTD Mapper 3.0" in result


def test_merge_report_replaced_and_not_replaced(combiner, mapper_file):
    """일부 조각만 제공 → replaced/not_replaced 기록"""
    frags = [_converted_fragment("getUser", "select",
        '<select id="getUser">CONVERTED</select>')]
    _tree, report = combiner.merge_with_report(mapper_file, frags)
    assert "getUser" in report.replaced
    assert "updateUser" in report.not_replaced


def test_merge_report_unused_fragment(combiner, mapper_file):
    """원본에 없는 조각 → unused_fragments"""
    frags = [
        _converted_fragment("getUser", "select", '<select id="getUser">X</select>'),
        _converted_fragment("ghost", "select", '<select id="ghost">Y</select>'),
    ]
    _tree, report = combiner.merge_with_report(mapper_file, frags)
    assert "ghost" in report.unused_fragments


def test_merge_not_replaced_keeps_original(combiner, mapper_file):
    """조각 없는 statement는 원본 내용 유지"""
    frags = [_converted_fragment("getUser", "select",
        '<select id="getUser">CONVERTED</select>')]
    result = combiner.merge_to_string(mapper_file, frags)
    # updateUser는 원본 그대로
    assert "UPDATE users SET name" in result


def test_missing_original_raises(combiner, tmp_path):
    """원본 파일 없으면 ConversionError"""
    with pytest.raises(ConversionError):
        combiner.merge_to_string(str(tmp_path / "nope.xml"), [])


def test_invalid_fragment_raises(combiner, mapper_file):
    """조각 XML이 깨졌으면 ConversionError"""
    frags = [_converted_fragment("getUser", "select", "<select id=broken")]
    with pytest.raises(ConversionError):
        combiner.merge_to_string(mapper_file, frags)


def test_roundtrip_split_then_merge(combiner, config, mapper_file):
    """split → merge 라운드트립: 모든 sql_id 보존"""
    splitter = MapperSplitter(config)
    frags = splitter.split(mapper_file)
    _tree, report = combiner.merge_with_report(mapper_file, frags)
    # 모든 원본 조각이 교체되고 미사용/누락 없음
    assert set(report.replaced) == {"getUser", "updateUser"}
    assert report.not_replaced == []
    assert report.unused_fragments == []
