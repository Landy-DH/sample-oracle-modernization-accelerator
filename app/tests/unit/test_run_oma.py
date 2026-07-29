"""
run_oma CLI 단위 테스트 (협력자 조립/phase 파싱, DB/LLM 없이)

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - parse_phases, build_orchestrator 지연 조립, --preflight, 인자 검증
2026-07-29 | Claude | --reconvert 되돌리기 로직/상호배타 테스트 추가
"""

import importlib.util
import os
import sys

import pytest

# scripts/run_oma.py 를 모듈로 로드 (tests/unit/ 기준 3단계 위가 프로젝트 루트)
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SPEC = importlib.util.spec_from_file_location(
    "run_oma", os.path.join(_ROOT, "scripts", "run_oma.py")
)
run_oma = importlib.util.module_from_spec(_SPEC)
sys.modules["run_oma"] = run_oma
_SPEC.loader.exec_module(run_oma)

from oma.utils.config import Config  # noqa: E402
from oma.workflow.orchestrator import (  # noqa: E402
    PHASE_CONVERSION,
    PHASE_DICTIONARY,
    PHASE_FRAGMENT,
    PHASE_MERGE,
)


def test_parse_phases_all():
    """all → 7개 Phase 전체"""
    assert len(run_oma.parse_phases("all")) == 7


def test_parse_phases_single():
    """단일 별칭 매핑"""
    assert run_oma.parse_phases("dictionary") == [PHASE_DICTIONARY]


def test_parse_phases_multiple():
    """콤마 구분 다중"""
    result = run_oma.parse_phases("fragment,merge")
    assert result == [PHASE_FRAGMENT, PHASE_MERGE]


def test_parse_phases_invalid():
    """알 수 없는 별칭 → ValueError"""
    with pytest.raises(ValueError):
        run_oma.parse_phases("bogus")


@pytest.fixture
def config(tmp_path):
    prop = tmp_path / "oma.properties"
    prop.write_text(
        "APPLICATION_NAME=wms\nSCHEMA_DICT_PATH=/tmp/d.json\n"
        "SOURCE_WORKSPACE=/tmp/src\nPROJECT_WORK_DIR=/tmp/wms\n"
        "MAPPER_WORK_DIR=/tmp/wms/mappers\nCHECKPOINT_PATH=/tmp/wms/.cp.json\n",
        encoding="utf-8",
    )
    return Config(str(prop))


def test_build_orchestrator_no_db_for_fragment(config, monkeypatch):
    """fragment/merge만이면 DB/LLM 협력자 조립 안 함"""
    called = {"target": False, "converter": False, "validation": False}
    monkeypatch.setattr(run_oma, "_build_target_plugin",
                        lambda c: called.__setitem__("target", True))
    monkeypatch.setattr(run_oma, "_build_converter",
                        lambda c: called.__setitem__("converter", True))
    monkeypatch.setattr(run_oma, "_build_validation",
                        lambda c: called.__setitem__("validation", True))

    run_oma.build_orchestrator(config, [PHASE_FRAGMENT, PHASE_MERGE])
    assert called == {"target": False, "converter": False, "validation": False}


def test_build_orchestrator_converter_for_convert(config, monkeypatch):
    """convert phase 포함 시 converter만 조립"""
    called = {"target": False, "converter": False, "validation": False}
    monkeypatch.setattr(run_oma, "_build_target_plugin",
                        lambda c: called.__setitem__("target", True))
    monkeypatch.setattr(run_oma, "_build_converter",
                        lambda c: called.__setitem__("converter", True))
    monkeypatch.setattr(run_oma, "_build_validation",
                        lambda c: called.__setitem__("validation", True))

    run_oma.build_orchestrator(config, [PHASE_CONVERSION])
    assert called["converter"] is True
    assert called["target"] is False


def test_build_orchestrator_target_for_dictionary(config, monkeypatch):
    """dictionary phase 포함 시 target 플러그인 조립"""
    called = {"target": False}
    monkeypatch.setattr(run_oma, "_build_target_plugin",
                        lambda c: called.__setitem__("target", True))
    run_oma.build_orchestrator(config, [PHASE_DICTIONARY])
    assert called["target"] is True


def test_main_missing_config():
    """없는 config → 종료코드 1"""
    assert run_oma.main(["--config", "/nonexistent.properties"]) == 1


def test_main_invalid_phase(tmp_path):
    """잘못된 phase → 종료코드 1"""
    prop = tmp_path / "p.properties"
    prop.write_text("APPLICATION_NAME=wms\n", encoding="utf-8")
    assert run_oma.main(["--config", str(prop), "--phase", "bogus"]) == 1


def test_main_reconvert_mutually_exclusive(tmp_path):
    """--reconvert 와 --reconvert-all 동시 사용 → 종료코드 1"""
    prop = tmp_path / "p.properties"
    prop.write_text("APPLICATION_NAME=wms\n", encoding="utf-8")
    rc = run_oma.main([
        "--config", str(prop), "--reconvert", "foo", "--reconvert-all",
    ])
    assert rc == 1


class _FakeCheckpoint:
    """되돌리기 호출을 기록하는 가짜 체크포인트."""

    def __init__(self):
        self.calls = []

    def reset_all_fragments(self):
        self.calls.append(("reset_all", None))
        return 5

    def reset_fragments_by_sql_id(self, sql_ids):
        self.calls.append(("reset_sql", sql_ids))
        return [f"M__select__{s}" for s in sql_ids]

    def reopen_phases_from(self, phase):
        self.calls.append(("reopen", phase))
        return [phase]


class _FakeOrch:
    def __init__(self):
        self.checkpoint = _FakeCheckpoint()


class _Args:
    def __init__(self, reconvert=None, reconvert_all=False):
        self.reconvert = reconvert
        self.reconvert_all = reconvert_all


def test_rewind_reconvert_all_calls_reset_all():
    """--reconvert-all → 전체 조각 초기화 + phase4 재오픈"""
    orch = _FakeOrch()
    run_oma._rewind_for_reconvert(orch, _Args(reconvert_all=True))
    calls = orch.checkpoint.calls
    assert ("reset_all", None) in calls
    assert ("reopen", PHASE_CONVERSION) in calls


def test_rewind_reconvert_selective_splits_sql_ids():
    """--reconvert 콤마 분리 후 sql_id별 되돌림 + phase4 재오픈"""
    orch = _FakeOrch()
    run_oma._rewind_for_reconvert(orch, _Args(reconvert="foo, bar"))
    calls = orch.checkpoint.calls
    assert ("reset_sql", ["foo", "bar"]) in calls
    assert ("reopen", PHASE_CONVERSION) in calls


def test_main_preflight(tmp_path, monkeypatch):
    """--preflight: preflight만 호출하고 0 반환"""
    prop = tmp_path / "p.properties"
    prop.write_text(
        f"APPLICATION_NAME=wms\nSOURCE_WORKSPACE={tmp_path}\n"
        f"PROJECT_WORK_DIR={tmp_path}/w\nMAPPER_WORK_DIR={tmp_path}/w/m\n"
        f"REPORT_DIR={tmp_path}/w/reports\nCHECKPOINT_PATH={tmp_path}/w/.cp\n",
        encoding="utf-8",
    )
    # preflight는 빈 디렉토리 스캔 → 매퍼 0개
    rc = run_oma.main(["--config", str(prop), "--preflight"])
    assert rc == 0
    assert os.path.exists(str(tmp_path / "w" / "reports" / "preflight-report.json"))
