"""
WorkflowOrchestrator 통합 테스트 (LLM/DB 없이 fake로 Phase 2~5,7 검증)

Phase 1(딕셔너리)·6(검증)은 DB/Java 의존이라 별도 단위 테스트에서 다루고,
여기서는 파일 파이프라인(복사→치환→분할→변환→병합→타겟복사)을 검증한다.

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - copy→substitute→fragment→convert(fake)→merge→copy_target 흐름
  - 특수변수 치환/리포트 저장/체크포인트 재시작 확인

2026-07-28 | OMA Team | 조각 파일명 충돌 회귀 테스트 추가
  - 조각 식별자에 statement_type 포함되며 파일명이 바뀜(__type__ 규칙)
    → 기존 파일명 단언 갱신
  - resultMap과 select가 같은 id를 공유하는 매퍼를 fixture에 추가하고,
    병합 결과에 resultMap 보존 + select 중복 없음(id별 1개) 검증
    (버그: 파일명 충돌로 resultMap 소실/ select 중복 → MyBatis 로딩 실패)
"""

import json
import textwrap

import pytest

from oma.converter.converter import ConversionResult
from oma.fragmenter.splitter import Fragment
from oma.utils.config import Config
from oma.workflow.checkpoint import CheckpointManager
from oma.workflow.orchestrator import (
    PHASE_CONVERSION,
    PHASE_COPY,
    PHASE_COPY_TARGET,
    PHASE_FRAGMENT,
    PHASE_MERGE,
    WorkflowOrchestrator,
)

_MAPPER = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8" ?>
    <!DOCTYPE mapper PUBLIC "-//mybatis.org//DTD Mapper 3.0//EN"
        "http://mybatis.org/dtd/mybatis-3-mapper.dtd">
    <mapper namespace="test.UserMapper">
      <resultMap id="getUser" type="map">
        <result column="ID" property="id"/>
      </resultMap>
      <select id="getUser" resultMap="getUser">
        SELECT * FROM users WHERE reg_dt = #{sysdate}
      </select>
      <update id="upd">UPDATE users SET name = #{name} WHERE id = #{id}</update>
    </mapper>
    """)


class _FakeConverter:
    """convert(fragment) → ConversionResult (SQL 그대로, 통과)"""

    def convert(self, fragment):
        return ConversionResult(
            mapper_name=fragment.mapper_name, sql_id=fragment.sql_id,
            status="success", strategy="standard",
            original_sql=fragment.content, converted_sql=fragment.content,
            type_casts=[{"column": "x"}], test_cases=[
                {"test_case_id": f"{fragment.mapper_name}_{fragment.sql_id}_tc001"}
            ],
        )


@pytest.fixture
def config(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    (src / "UserMapper.xml").write_text(_MAPPER, encoding="utf-8")

    work = tmp_path / "work"
    prop = tmp_path / "oma.properties"
    prop.write_text(
        f"SOURCE_WORKSPACE={src}\n"
        f"TARGET_WORKSPACE={tmp_path}/target\n"
        f"PROJECT_WORK_DIR={work}\n"
        f"MAPPER_WORK_DIR={work}/mappers\n"
        f"TESTCASE_DIR={work}/testcases\n"
        f"REPORT_DIR={work}/reports\n"
        f"CHECKPOINT_PATH={work}/.checkpoint.json\n"
        f"SOURCE_DB_TYPE=oracle\n"
        f"SUBSTITUTE_OGNL=true\n",
        encoding="utf-8",
    )
    return Config(str(prop))


@pytest.fixture
def orch(config):
    cp = CheckpointManager(config.get("CHECKPOINT_PATH"))
    return WorkflowOrchestrator(config, checkpoint=cp, converter=_FakeConverter())


def test_copy_and_substitute(orch, config):
    """Phase2: 복사 + sysdate 치환"""
    orch.phase_copy_mappers()
    import os
    copied = os.path.join(config.get("MAPPER_WORK_DIR"), "original", "UserMapper.xml")
    assert os.path.isfile(copied)
    content = open(copied, encoding="utf-8").read()
    assert "#{sysdate}" not in content  # 치환됨
    assert "SYSDATE" in content


def test_full_file_pipeline(orch, config):
    """Phase 2→3→4→5→7 전체 파일 파이프라인"""
    import os
    orch.run(phases=[PHASE_COPY, PHASE_FRAGMENT, PHASE_CONVERSION, PHASE_MERGE,
                     PHASE_COPY_TARGET])
    work = config.get("MAPPER_WORK_DIR")

    # 분할 결과
    assert os.path.isfile(os.path.join(work, "fragmented", "mapping.json"))
    # 변환 결과 + 리포트 (파일명에 statement_type 포함)
    assert os.path.isfile(os.path.join(work, "converted", "UserMapper__select__getUser.xml"))
    assert os.path.isfile(
        os.path.join(work, "converted", "UserMapper__select__getUser.report.json"))
    # TC 저장
    assert os.path.isdir(config.get("TESTCASE_DIR"))
    assert len(os.listdir(config.get("TESTCASE_DIR"))) >= 1
    # 병합 결과
    assert os.path.isfile(os.path.join(work, "merged", "UserMapper.xml"))
    # 타겟 복사
    assert os.path.isfile(os.path.join(config.get("TARGET_WORKSPACE"), "UserMapper.xml"))


def test_conversion_report_content(orch, config):
    """변환 리포트에 type_casts/status 저장"""
    import os
    orch.run(phases=[PHASE_COPY, PHASE_FRAGMENT, PHASE_CONVERSION])
    report = json.loads(open(
        os.path.join(config.get("MAPPER_WORK_DIR"), "converted",
                     "UserMapper__select__getUser.report.json"), encoding="utf-8").read())
    assert report["status"] == "success"
    assert report["type_casts"] == [{"column": "x"}]


def test_conversion_summary(orch, config):
    """conversion-summary.json 생성"""
    import os
    orch.run(phases=[PHASE_COPY, PHASE_FRAGMENT, PHASE_CONVERSION])
    summary = json.loads(open(
        os.path.join(config.get("REPORT_DIR"), "conversion-summary.json"),
        encoding="utf-8").read())
    assert summary["success"] >= 2  # getUser + upd


def test_checkpoint_skips_completed(orch, config):
    """체크포인트: 완료된 Phase 재실행 시 건너뜀"""
    orch.run(phases=[PHASE_COPY])
    assert orch.checkpoint.is_completed(PHASE_COPY)
    # 재실행해도 예외 없이 스킵
    orch.run(phases=[PHASE_COPY])


def test_merged_is_valid_xml(orch, config):
    """병합 결과가 유효한 XML이고 statement 보존"""
    import os
    from lxml import etree
    orch.run(phases=[PHASE_COPY, PHASE_FRAGMENT, PHASE_CONVERSION, PHASE_MERGE])
    merged = os.path.join(config.get("MAPPER_WORK_DIR"), "merged", "UserMapper.xml")
    tree = etree.parse(merged)
    ids = [e.get("id") for e in tree.getroot() if isinstance(e.tag, str)]
    assert "getUser" in ids and "upd" in ids


def test_resultmap_and_select_same_id_no_collision(orch, config):
    """
    회귀: <resultMap>과 <select>가 같은 id를 공유해도 조각이 충돌하지 않는다.

    버그(2026-07-28): 조각 파일명이 statement_type 없이 {mapper}__{sql_id}라
    resultMap과 select가 같은 파일명으로 충돌 → 하나가 덮어써지고, 병합 시
    resultMap 소실 + select 중복 → MyBatis "Could not find result map" 실패.
    """
    import os
    from collections import Counter
    from lxml import etree

    orch.run(phases=[PHASE_COPY, PHASE_FRAGMENT, PHASE_CONVERSION, PHASE_MERGE])
    work = config.get("MAPPER_WORK_DIR")

    # 두 조각이 서로 다른 파일로 저장됨 (statement_type로 구분)
    conv = os.path.join(work, "converted")
    assert os.path.isfile(os.path.join(conv, "UserMapper__resultMap__getUser.xml"))
    assert os.path.isfile(os.path.join(conv, "UserMapper__select__getUser.xml"))

    # 병합 결과: resultMap 정의 보존 + 각 (tag,id) 조합이 정확히 1개씩
    root = etree.parse(os.path.join(work, "merged", "UserMapper.xml")).getroot()
    tags = Counter(
        (e.tag, e.get("id")) for e in root if isinstance(e.tag, str)
    )
    assert tags[("resultMap", "getUser")] == 1  # 소실되지 않음
    assert tags[("select", "getUser")] == 1     # 중복되지 않음
    assert tags[("update", "upd")] == 1


def test_parallel_conversion_all_fragments(tmp_path):
    """
    Phase4 병렬 경로: MAX_WORKERS>1이면 ThreadPoolExecutor로 변환해도
    모든 조각이 빠짐없이 저장되고 체크포인트에 완료 기록된다.
    """
    import os

    src = tmp_path / "source"
    src.mkdir()
    (src / "UserMapper.xml").write_text(_MAPPER, encoding="utf-8")

    work = tmp_path / "work"
    prop = tmp_path / "oma.properties"
    prop.write_text(
        f"SOURCE_WORKSPACE={src}\n"
        f"TARGET_WORKSPACE={tmp_path}/target\n"
        f"PROJECT_WORK_DIR={work}\n"
        f"MAPPER_WORK_DIR={work}/mappers\n"
        f"TESTCASE_DIR={work}/testcases\n"
        f"REPORT_DIR={work}/reports\n"
        f"CHECKPOINT_PATH={work}/.checkpoint.json\n"
        f"SOURCE_DB_TYPE=oracle\n"
        f"SUBSTITUTE_OGNL=true\n"
        f"MAX_WORKERS=4\n",
        encoding="utf-8",
    )
    config = Config(str(prop))
    cp = CheckpointManager(config.get("CHECKPOINT_PATH"))
    orch = WorkflowOrchestrator(config, checkpoint=cp, converter=_FakeConverter())

    orch.run(phases=[PHASE_COPY, PHASE_FRAGMENT, PHASE_CONVERSION, PHASE_MERGE])

    conv = os.path.join(config.get("MAPPER_WORK_DIR"), "converted")
    # 3개 조각 모두 병렬 변환되어 저장됨
    assert os.path.isfile(os.path.join(conv, "UserMapper__resultMap__getUser.xml"))
    assert os.path.isfile(os.path.join(conv, "UserMapper__select__getUser.xml"))
    assert os.path.isfile(os.path.join(conv, "UserMapper__update__upd.xml"))
    # 체크포인트에 완료 기록 (재시작 시 스킵됨)
    assert cp.is_fragment_completed("UserMapper__select__getUser")
    assert cp.is_fragment_completed("UserMapper__update__upd")
    # summary 집계 정확
    summary = json.loads(open(
        os.path.join(config.get("REPORT_DIR"), "conversion-summary.json"),
        encoding="utf-8").read())
    assert summary["success"] == 3
