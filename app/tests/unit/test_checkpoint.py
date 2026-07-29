"""
CheckpointManager 단위 테스트

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - phase/fragment 진행, 재시작 로드, 실패 추적, 원자적 저장 테스트
"""

import json
from datetime import datetime, timezone

import pytest

from oma.workflow.checkpoint import (
    PHASES,
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_PENDING,
    CheckpointManager,
)

# 고정 시각 주입 (테스트 재현성)
_FIXED = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def cp_path(tmp_path):
    return str(tmp_path / ".checkpoint.json")


@pytest.fixture
def cp(cp_path):
    return CheckpointManager(cp_path, now_fn=lambda: _FIXED)


def test_new_checkpoint_created(cp):
    """신규 체크포인트: 모든 phase pending"""
    assert cp.is_fresh_run() is True
    assert cp.current_phase() == PHASES[0]
    assert all(cp.checkpoint["progress"][p] == STATUS_PENDING for p in PHASES)


def test_saved_to_disk(cp, cp_path):
    """생성 즉시 파일로 저장되지 않지만, phase 표시 시 저장됨"""
    cp.mark_phase_started("phase1_dictionary")
    with open(cp_path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["progress"]["phase1_dictionary"] == STATUS_IN_PROGRESS


def test_phase_lifecycle(cp):
    """phase 시작→완료"""
    cp.mark_phase_started("phase1_dictionary")
    assert cp.checkpoint["progress"]["phase1_dictionary"] == STATUS_IN_PROGRESS
    cp.mark_phase_completed("phase1_dictionary")
    assert cp.is_completed("phase1_dictionary") is True
    assert cp.is_fresh_run() is False


def test_invalid_phase_raises(cp):
    """알 수 없는 phase는 ValueError"""
    with pytest.raises(ValueError):
        cp.mark_phase_started("phase99_unknown")


def test_fragment_completed_tracking(cp):
    """조각 완료 추적 + 카운트"""
    cp.mark_fragment_completed("UserMapper__getUser")
    cp.mark_fragment_completed("UserMapper__insertUser")
    assert cp.is_fragment_completed("UserMapper__getUser") is True
    assert cp.checkpoint["phase4_detail"]["completed"] == 2


def test_fragment_completed_idempotent(cp):
    """같은 조각 중복 완료는 카운트 1회"""
    cp.mark_fragment_completed("A")
    cp.mark_fragment_completed("A")
    assert cp.checkpoint["phase4_detail"]["completed"] == 1


def test_get_pending_fragments(cp):
    """전체 목록에서 완료분 제외"""
    cp.mark_fragment_completed("b")
    pending = cp.get_pending_fragments(["a", "b", "c"])
    assert pending == ["a", "c"]


def test_fragment_failed_tracking(cp):
    """조각 실패 기록 + can_retry 판단"""
    cp.mark_fragment_failed("X", "LLM timeout", retry_count=1)
    cp.mark_fragment_failed("Y", "boom", retry_count=3)
    failures = cp.checkpoint["phase4_detail"]["failed_fragments"]
    assert len(failures) == 2
    assert failures[0]["can_retry"] is True   # retry 1 < 3
    assert failures[1]["can_retry"] is False  # retry 3 >= 3


def test_get_retryable_failures(cp):
    """재시도 가능한 실패만 반환"""
    cp.mark_fragment_failed("X", "e", 1)
    cp.mark_fragment_failed("Y", "e", 3)
    retryable = cp.get_retryable_failures()
    assert len(retryable) == 1
    assert retryable[0]["fragment_id"] == "X"


def test_clear_failure(cp):
    """실패 기록 제거 (재시도 성공 시)"""
    cp.mark_fragment_failed("X", "e", 1)
    cp.clear_failure("X")
    assert cp.checkpoint["phase4_detail"]["failed"] == 0


def test_reload_resumes_state(cp_path):
    """저장 후 새 인스턴스로 로드하면 상태 복원 (재시작)"""
    cp1 = CheckpointManager(cp_path, now_fn=lambda: _FIXED)
    cp1.mark_phase_started("phase1_dictionary")
    cp1.mark_phase_completed("phase1_dictionary")
    cp1.mark_phase_started("phase4_conversion")
    cp1.mark_fragment_completed("frag1")

    # 새 인스턴스 = 재시작
    cp2 = CheckpointManager(cp_path, now_fn=lambda: _FIXED)
    assert cp2.is_completed("phase1_dictionary") is True
    assert cp2.current_phase() == "phase4_conversion"
    assert cp2.is_fragment_completed("frag1") is True
    assert cp2.get_pending_fragments(["frag1", "frag2"]) == ["frag2"]


def test_corrupt_checkpoint_recreates(cp_path):
    """손상된 체크포인트 파일이면 새로 생성"""
    with open(cp_path, "w", encoding="utf-8") as f:
        f.write("{not valid json")
    cp = CheckpointManager(cp_path, now_fn=lambda: _FIXED)
    assert cp.is_fresh_run() is True


def test_directory_path_uses_default_filename(tmp_path):
    """디렉토리 경로를 주면 .checkpoint.json 사용"""
    cp = CheckpointManager(str(tmp_path), now_fn=lambda: _FIXED)
    cp.mark_phase_started("phase1_dictionary")
    assert (tmp_path / ".checkpoint.json").exists()


def test_update_statistics(cp):
    """통계 병합 갱신"""
    cp.update_statistics(llm_api_calls=10, llm_total_tokens=5000)
    cp.update_statistics(llm_api_calls=20)  # 갱신
    assert cp.checkpoint["statistics"]["llm_api_calls"] == 20
    assert cp.checkpoint["statistics"]["llm_total_tokens"] == 5000


def test_atomic_save_no_tmp_leftover(cp, cp_path):
    """저장 후 .tmp 파일이 남지 않음 (원자적 교체)"""
    import os
    cp.mark_phase_started("phase1_dictionary")
    assert not os.path.exists(cp_path + ".tmp")
    assert os.path.exists(cp_path)


def test_reset(cp):
    """reset은 상태를 초기화"""
    cp.mark_phase_completed("phase1_dictionary")
    cp.mark_fragment_completed("a")
    cp.reset()
    assert cp.is_fresh_run() is True
    assert cp.get_pending_fragments(["a"]) == ["a"]
