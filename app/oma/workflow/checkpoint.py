"""
체크포인트 관리 모듈

전체 변환 워크플로우(Phase 1~7)의 진행 상황을 .checkpoint.json에 저장해
중단 시 재시작을 지원한다. Phase 단위 진행과 Phase4(변환)의 조각 단위 진행/실패를
추적한다.

저장은 원자적으로 수행한다(임시 파일 → rename)으로 중간 크래시 시 손상 방지.

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - CheckpointManager: phase/fragment 진행 저장, 재시작, 실패 추적
  - 원자적 저장(tmp+os.replace), 완료 조각은 set으로 관리(대규모 조회 성능)
  - 시간 함수 주입 가능(테스트), datetime timezone-aware 사용
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# 워크플로우 Phase 순서/이름
PHASES = [
    "phase1_dictionary",
    "phase2_copy_mappers",
    "phase3_fragment",
    "phase4_conversion",
    "phase5_merge",
    "phase6_validation",
    "phase7_copy_target",
]

# 진행 상태 값
STATUS_PENDING = "pending"
STATUS_IN_PROGRESS = "in_progress"
STATUS_COMPLETED = "completed"

# 조각 재시도 상한 (실패 조각 can_retry 판단용)
_MAX_FRAGMENT_RETRIES = 3


class CheckpointManager:
    """
    체크포인트 관리자

    Attributes:
        checkpoint_file: .checkpoint.json 경로
        checkpoint: 현재 체크포인트 dict
    """

    def __init__(
        self,
        checkpoint_path: str,
        now_fn: Optional[Callable[[], datetime]] = None,
    ) -> None:
        """
        초기화 (기존 체크포인트 로드 또는 신규 생성)

        Args:
            checkpoint_path: 체크포인트 파일 경로(또는 디렉토리)
            now_fn: 현재 시각 반환 함수 (테스트용 주입). 기본은 UTC now
        """
        # 디렉토리를 주면 그 아래 .checkpoint.json 사용
        if os.path.isdir(checkpoint_path):
            self.checkpoint_file = os.path.join(checkpoint_path, ".checkpoint.json")
        else:
            self.checkpoint_file = checkpoint_path

        self._now = now_fn or (lambda: datetime.now(timezone.utc))
        self.checkpoint: Dict[str, Any] = self._load_or_create()
        # 완료 조각은 조회 성능을 위해 set으로도 유지
        self._completed_set = set(
            self.checkpoint.get("phase4_detail", {}).get("completed_fragments", [])
        )

    def _timestamp(self) -> str:
        """ISO 8601 UTC 타임스탬프 문자열."""
        return self._now().isoformat()

    def _load_or_create(self) -> Dict[str, Any]:
        """체크포인트 파일을 로드하거나 새로 만든다."""
        if os.path.isfile(self.checkpoint_file):
            try:
                with open(self.checkpoint_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                logger.info("체크포인트 로드: run_id=%s, phase=%s",
                            data.get("run_id"), data.get("phase"))
                return data
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("체크포인트 로드 실패, 새로 생성: %s", e)
        return self._create_new()

    def _create_new(self) -> Dict[str, Any]:
        """새 체크포인트 구조를 만든다."""
        ts = self._timestamp()
        return {
            "run_id": self._now().strftime("%Y%m%d_%H%M%S"),
            "phase": PHASES[0],
            "started_at": ts,
            "last_checkpoint_at": ts,
            "progress": {phase: STATUS_PENDING for phase in PHASES},
            "phase4_detail": {
                "completed": 0,
                "failed": 0,
                "completed_fragments": [],
                "failed_fragments": [],
            },
            "statistics": {},
        }

    # ------------------------------------------------------------- Phase 단위

    def mark_phase_started(self, phase: str) -> None:
        """페이즈 시작을 기록한다."""
        self._validate_phase(phase)
        self.checkpoint["phase"] = phase
        self.checkpoint["progress"][phase] = STATUS_IN_PROGRESS
        self.save()

    def mark_phase_completed(self, phase: str) -> None:
        """페이즈 완료를 기록한다."""
        self._validate_phase(phase)
        self.checkpoint["progress"][phase] = STATUS_COMPLETED
        self.save()

    def is_completed(self, phase: str) -> bool:
        """페이즈 완료 여부를 반환한다."""
        return self.checkpoint["progress"].get(phase) == STATUS_COMPLETED

    def current_phase(self) -> str:
        """현재(마지막으로 시작된) 페이즈를 반환한다."""
        return self.checkpoint["phase"]

    def is_fresh_run(self) -> bool:
        """아무 페이즈도 시작하지 않은 새 실행인지 여부."""
        return all(
            s == STATUS_PENDING for s in self.checkpoint["progress"].values()
        )

    # ---------------------------------------------------------- Fragment 단위

    def mark_fragment_completed(self, fragment_id: str) -> None:
        """조각 변환 완료를 기록한다 (중복 방지)."""
        if fragment_id in self._completed_set:
            return
        detail = self.checkpoint["phase4_detail"]
        detail["completed_fragments"].append(fragment_id)
        detail["completed"] = len(detail["completed_fragments"])
        self._completed_set.add(fragment_id)
        self.save()

    def mark_fragment_failed(
        self, fragment_id: str, error: str, retry_count: int
    ) -> None:
        """조각 변환 실패를 기록한다."""
        detail = self.checkpoint["phase4_detail"]
        detail["failed_fragments"].append({
            "fragment_id": fragment_id,
            "error": str(error),
            "retry_count": retry_count,
            "can_retry": retry_count < _MAX_FRAGMENT_RETRIES,
            "failed_at": self._timestamp(),
        })
        detail["failed"] = len(detail["failed_fragments"])
        self.save()

    def is_fragment_completed(self, fragment_id: str) -> bool:
        """조각이 이미 완료됐는지 여부."""
        return fragment_id in self._completed_set

    def get_pending_fragments(self, all_fragment_ids: List[str]) -> List[str]:
        """
        전체 조각 목록에서 아직 완료되지 않은 조각을 반환한다.

        Args:
            all_fragment_ids: 전체 조각 ID 목록

        Returns:
            미완료 조각 ID 리스트 (순서 유지)
        """
        return [fid for fid in all_fragment_ids if fid not in self._completed_set]

    def get_retryable_failures(self) -> List[Dict[str, Any]]:
        """재시도 가능한 실패 조각 목록을 반환한다."""
        failures = self.checkpoint["phase4_detail"].get("failed_fragments", [])
        return [f for f in failures if f.get("can_retry")]

    def clear_failure(self, fragment_id: str) -> None:
        """재시도 성공 등으로 실패 기록을 제거한다."""
        detail = self.checkpoint["phase4_detail"]
        detail["failed_fragments"] = [
            f for f in detail["failed_fragments"]
            if f.get("fragment_id") != fragment_id
        ]
        detail["failed"] = len(detail["failed_fragments"])
        self.save()

    # ----------------------------------------------------------- 통계/저장

    def update_statistics(self, **kwargs: Any) -> None:
        """통계 값을 병합 갱신한다 (llm_api_calls 등)."""
        self.checkpoint.setdefault("statistics", {}).update(kwargs)
        self.save()

    def save(self) -> None:
        """
        체크포인트를 원자적으로 저장한다 (tmp 파일 작성 후 교체).

        중간 크래시 시에도 기존 체크포인트가 손상되지 않도록 os.replace를 쓴다.
        """
        self.checkpoint["last_checkpoint_at"] = self._timestamp()

        directory = os.path.dirname(self.checkpoint_file)
        if directory:
            os.makedirs(directory, exist_ok=True)

        tmp_file = f"{self.checkpoint_file}.tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(self.checkpoint, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, self.checkpoint_file)

    def reset(self) -> None:
        """체크포인트를 초기화한다 (새 실행 시작)."""
        self.checkpoint = self._create_new()
        self._completed_set = set()
        self.save()

    @staticmethod
    def _validate_phase(phase: str) -> None:
        """알 수 없는 페이즈명이면 예외를 던진다."""
        if phase not in PHASES:
            raise ValueError(f"알 수 없는 페이즈: {phase} (유효: {PHASES})")
