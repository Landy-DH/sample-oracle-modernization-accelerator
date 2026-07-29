"""
MapperSplitter 단위 테스트

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - split/네임스페이스/statement 타입/CDATA/동적SQL 보존/mapping 생성/에러 테스트
"""

import textwrap

import pytest

from oma.fragmenter.splitter import MapperSplitter
from oma.utils.config import Config
from oma.utils.exceptions import ConversionError

_MAPPER_XML = textwrap.dedent(
    """\
    <?xml version="1.0" encoding="UTF-8" ?>
    <!DOCTYPE mapper PUBLIC "-//mybatis.org//DTD Mapper 3.0//EN"
        "http://mybatis.org/dtd/mybatis-3-mapper.dtd">
    <mapper namespace="com.acme.app.UserMapper">
        <!-- 사용자 조회 -->
        <select id="getUser" resultType="camelMap">
            SELECT user_id, name FROM users WHERE user_id = #{userId}
        </select>

        <update id="updateUser">
            UPDATE users SET name = #{name}
            <if test="status != null">, status = #{status}</if>
            WHERE user_id = #{userId}
        </update>

        <sql id="commonCols">user_id, name, status</sql>

        <select id="withCdata" resultType="camelMap">
            <![CDATA[ SELECT * FROM users WHERE age < #{maxAge} ]]>
        </select>
    </mapper>
    """
)


@pytest.fixture
def config(tmp_path):
    prop = tmp_path / "oma.properties"
    prop.write_text(f"SOURCE_WORKSPACE={tmp_path}\n", encoding="utf-8")
    return Config(str(prop))


@pytest.fixture
def mapper_file(tmp_path):
    path = tmp_path / "UserMapper.xml"
    path.write_text(_MAPPER_XML, encoding="utf-8")
    return str(path)


@pytest.fixture
def splitter(config):
    return MapperSplitter(config)


def test_split_count_and_ids(splitter, mapper_file):
    """4개 statement로 분할되고 sql_id가 정확"""
    frags = splitter.split(mapper_file)
    ids = [f.sql_id for f in frags]
    assert ids == ["getUser", "updateUser", "commonCols", "withCdata"]


def test_fragment_metadata(splitter, mapper_file):
    """mapper_name/namespace/statement_type 채워짐"""
    frags = splitter.split(mapper_file)
    first = frags[0]
    assert first.mapper_name == "UserMapper"
    assert first.namespace == "com.acme.app.UserMapper"
    assert first.statement_type == "select"
    assert first.has_id is True


def test_statement_types(splitter, mapper_file):
    """각 조각의 태그 타입 확인"""
    frags = {f.sql_id: f for f in splitter.split(mapper_file)}
    assert frags["updateUser"].statement_type == "update"
    assert frags["commonCols"].statement_type == "sql"


def test_dynamic_sql_preserved(splitter, mapper_file):
    """<if> 등 동적 SQL 태그가 content에 보존됨"""
    frags = {f.sql_id: f for f in splitter.split(mapper_file)}
    assert "<if" in frags["updateUser"].content
    assert 'test="status != null"' in frags["updateUser"].content


def test_cdata_preserved(splitter, mapper_file):
    """CDATA 섹션이 보존됨 (< 이스케이프 아님)"""
    frags = {f.sql_id: f for f in splitter.split(mapper_file)}
    assert "CDATA" in frags["withCdata"].content
    assert "age < " in frags["withCdata"].content


def test_content_is_well_formed(splitter, mapper_file):
    """조각 content가 단독으로 파싱 가능한 XML"""
    from lxml import etree

    frags = splitter.split(mapper_file)
    for f in frags:
        el = etree.fromstring(f.content.encode("utf-8"))
        assert el.get("id") == f.sql_id


def test_missing_file_raises(splitter, tmp_path):
    """없는 파일은 ConversionError"""
    with pytest.raises(ConversionError):
        splitter.split(str(tmp_path / "nope.xml"))


def test_non_mapper_root_raises(splitter, tmp_path):
    """루트가 <mapper>가 아니면 ConversionError"""
    bad = tmp_path / "bad.xml"
    bad.write_text("<beans><bean/></beans>", encoding="utf-8")
    with pytest.raises(ConversionError):
        splitter.split(str(bad))


def test_malformed_xml_raises(splitter, tmp_path):
    """깨진 XML은 ConversionError"""
    bad = tmp_path / "broken.xml"
    bad.write_text("<mapper><select id='x'>unclosed", encoding="utf-8")
    with pytest.raises(ConversionError):
        splitter.split(str(bad))


def test_element_without_id_gets_synthetic(splitter, tmp_path):
    """id 없는 요소(cache 등)도 합성 id로 보존"""
    path = tmp_path / "M.xml"
    path.write_text(
        '<mapper namespace="n"><cache/><select id="a">X</select></mapper>',
        encoding="utf-8",
    )
    frags = splitter.split(str(path))
    assert len(frags) == 2
    cache_frag = frags[0]
    assert cache_frag.statement_type == "cache"
    assert cache_frag.has_id is False
    assert cache_frag.sql_id.startswith("__el")


def test_find_and_split_workspace(splitter, mapper_file, tmp_path):
    """워크스페이스 스캔 + mapping 생성"""
    files = splitter.find_mapper_files()
    assert any(f.endswith("UserMapper.xml") for f in files)

    results = splitter.split_workspace()
    mapping = MapperSplitter.build_mapping(results)
    assert mapping["mapper_count"] >= 1
    assert mapping["fragment_count"] >= 4
    # 상대경로 키 확인
    key = next(iter(mapping["mappers"]))
    assert mapping["mappers"][key]["fragment_count"] >= 1


def test_relative_path(splitter, mapper_file):
    """source_file이 워크스페이스 기준 상대경로"""
    frags = splitter.split(mapper_file)
    assert frags[0].source_file == "UserMapper.xml"


def test_exclude_dirs(tmp_path):
    """MAPPER_EXCLUDE_DIRS로 지정한 디렉토리는 스캔 제외"""
    # 루트 매퍼 + 제외 대상 디렉토리 안의 매퍼
    (tmp_path / "Root.xml").write_text(_MAPPER_XML, encoding="utf-8")
    backup = tmp_path / "app-migration" / "backup"
    backup.mkdir(parents=True)
    (backup / "Backup.xml").write_text(_MAPPER_XML, encoding="utf-8")

    prop = tmp_path / "oma.properties"
    prop.write_text(
        f"SOURCE_WORKSPACE={tmp_path}\nMAPPER_EXCLUDE_DIRS=app-migration\n",
        encoding="utf-8",
    )
    sp = MapperSplitter(Config(str(prop)))
    files = sp.find_mapper_files()
    assert any(f.endswith("Root.xml") for f in files)
    assert not any("app-migration" in f for f in files)


def test_apple_double_files_excluded(splitter, mapper_file, tmp_path):
    """macOS 리소스 포크(._*.xml)는 매퍼 후보에서 제외"""
    # 실제 매퍼와 동일 내용의 ._ 파일 생성
    (tmp_path / "._UserMapper.xml").write_text(_MAPPER_XML, encoding="utf-8")
    files = splitter.find_mapper_files()
    assert all(not __import__("os").path.basename(f).startswith("._") for f in files)
    assert any(f.endswith("UserMapper.xml") for f in files)
