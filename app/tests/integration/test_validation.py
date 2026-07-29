"""
ValidationOrchestrator 통합 테스트 (bridge mock)

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - TC 로드→검증→비교→리포트 전체 플로우, 빈 디렉토리, 로드실패 처리
"""

import json

import pytest

from oma.validation.comparator import ResultComparator
from oma.validation.orchestrator import ValidationOrchestrator
from oma.validation.reporter import ValidationReporter
from oma.utils.exceptions import ValidationError


class _FakeBridge:
    """validate_batch를 흉내내는 fake (TC 그대로 받아 정해진 결과 반환)"""

    def __init__(self, results):
        self._results = results
        self.received = None

    def validate_batch(self, test_cases):
        self.received = test_cases
        return self._results


def _select(rows):
    cols = list(rows[0].keys()) if rows else []
    return {"success": True, "skipped": False, "sampled": False,
            "rows": rows, "columns": cols, "rowCount": len(rows)}


def _vr(tc_id, source, target):
    return {"tcId": tc_id, "status": "ok", "sourceResult": source, "targetResult": target}


@pytest.fixture
def tc_dir(tmp_path):
    d = tmp_path / "testcases"
    d.mkdir()
    (d / "M_a_tc001.json").write_text(json.dumps(
        {"test_case_id": "M_a_tc001", "namespace": "M", "sql_id": "a", "parameters": {}}),
        encoding="utf-8")
    (d / "M_b_tc001.json").write_text(json.dumps(
        {"test_case_id": "M_b_tc001", "namespace": "M", "sql_id": "b", "parameters": {}}),
        encoding="utf-8")
    return str(d)


@pytest.fixture
def report_dir(tmp_path):
    return str(tmp_path / "reports")


def _orch(bridge, report_dir):
    return ValidationOrchestrator(
        bridge=bridge,
        comparator=ResultComparator(),
        reporter=ValidationReporter(report_dir, run_id="test"),
    )


def test_validate_all_flow(tc_dir, report_dir):
    """TC 로드 → 검증 → 비교 → 리포트 전체 흐름"""
    rows = [{"id": 1}]
    bridge = _FakeBridge([
        _vr("M_a_tc001", _select(rows), _select(rows)),          # 통과
        _vr("M_b_tc001", _select([{"id": 1}, {"id": 2}]), _select(rows)),  # 행수 불일치
    ])
    orch = _orch(bridge, report_dir)
    summary = orch.validate_all(tc_dir)

    assert summary["total_test_cases"] == 2
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    # 리포트 파일 생성 확인
    import os
    assert os.path.exists(os.path.join(report_dir, "validation-summary.json"))


def test_bridge_receives_loaded_tcs(tc_dir, report_dir):
    """로드된 TC가 브리지에 전달됨 (파일명 정렬순 2개)"""
    bridge = _FakeBridge([
        _vr("M_a_tc001", _select([{"id": 1}]), _select([{"id": 1}])),
        _vr("M_b_tc001", _select([{"id": 1}]), _select([{"id": 1}])),
    ])
    orch = _orch(bridge, report_dir)
    orch.validate_all(tc_dir)
    assert len(bridge.received) == 2
    assert bridge.received[0]["test_case_id"] == "M_a_tc001"


def test_empty_dir_produces_empty_report(tmp_path, report_dir):
    """TC 없는 디렉토리 → 빈 리포트 (검증 호출 안 함)"""
    empty = tmp_path / "empty"
    empty.mkdir()
    bridge = _FakeBridge([])
    orch = _orch(bridge, report_dir)
    summary = orch.validate_all(str(empty))
    assert summary["total_test_cases"] == 0
    assert bridge.received is None  # 브리지 미호출


def test_missing_dir_raises(report_dir):
    """없는 디렉토리는 ValidationError"""
    bridge = _FakeBridge([])
    orch = _orch(bridge, report_dir)
    with pytest.raises(ValidationError):
        orch.validate_all("/nonexistent/testcases")


def test_corrupt_tc_skipped(tmp_path, report_dir):
    """깨진 TC 파일은 건너뛰고 나머지 로드"""
    d = tmp_path / "tc"
    d.mkdir()
    (d / "good.json").write_text(json.dumps({"test_case_id": "good"}), encoding="utf-8")
    (d / "bad.json").write_text("{broken", encoding="utf-8")
    bridge = _FakeBridge([_vr("good", _select([{"id": 1}]), _select([{"id": 1}]))])
    orch = _orch(bridge, report_dir)
    orch.validate_all(str(d))
    assert len(bridge.received) == 1  # good만 로드됨
