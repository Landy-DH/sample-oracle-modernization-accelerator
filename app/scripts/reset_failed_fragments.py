#!/usr/bin/env python3.11
"""
실패 조각 선택 재변환 준비 스크립트

변환(Phase4)에서 status가 failed/partial로 기록된 조각만 골라
체크포인트를 되돌려, 다음 `--phase convert` 실행 시 해당 조각만
재변환되도록 만든다. 성공 조각(302개 등)은 completed_fragments에
남아 있으므로 orchestrator가 is_fragment_completed로 건너뛴다.

동작:
  1) converted/*.report.json 을 읽어 재변환 대상 status를 가진 조각 식별
     (정규식으로 SQL/XML을 파싱하지 않는다 - report.json은 순수 JSON)
  2) 체크포인트 백업(.checkpoint.json.bak-<run_id>)
  3) 대상 조각을 phase4_detail.completed_fragments 에서 제거 + completed 카운트 갱신
  4) progress.phase4_conversion 및 그 이후 phase(merge/validation/copy_target)를
     pending 으로 되돌림(재변환 결과가 하류 phase에 반영되도록)

사용:
  python3.11 scripts/reset_failed_fragments.py --config oma.properties
  python3.11 scripts/reset_failed_fragments.py --config oma.properties \
      --status failed partial --dry-run
  python3.11 scripts/reset_failed_fragments.py --config oma.properties \
      --fragment NoticeMapper__retrieveGscmNoticeList ...

변경 이력:
2026-07-28 | OMA Team | 초기 생성
  - Phase4 실패/부분 조각만 선택 재변환하기 위한 체크포인트 리셋 유틸
  - report.status 기반 자동 식별 + 명시적 --fragment 지정 모두 지원
  - 하류 phase(merge/validation/copy_target)도 pending 복귀
"""

import argparse
import json
import logging
import os
import shutil
import sys
from typing import Dict, List, Set

# 프로젝트 루트를 import 경로에 추가 (scripts/ 에서 실행)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from oma.utils.config import Config  # noqa: E402
from oma.utils.exceptions import ConfigError  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("reset_failed_fragments")

# 재변환 시 pending 으로 되돌릴 phase (conversion 및 그 하류)
_DOWNSTREAM_PHASES = (
    "phase4_conversion",
    "phase5_merge",
    "phase6_validation",
    "phase7_copy_target",
)
_STATUS_PENDING = "pending"
_REPORT_SUFFIX = ".report.json"


def _load_checkpoint(path: str) -> Dict:
    """체크포인트 JSON 을 로드한다."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"체크포인트가 없습니다: {path}")
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)


def _find_fragments_by_status(
    converted_dir: str, statuses: Set[str]
) -> List[str]:
    """
    converted/*.report.json 에서 주어진 status 를 가진 조각 id 목록을 찾는다.

    Args:
        converted_dir: 변환 결과 디렉토리
        statuses: 재변환 대상 status 집합 (예: {"failed", "partial"})

    Returns:
        조각 id 목록 (예: ["NoticeMapper__retrieveGscmNoticeList", ...])
    """
    if not os.path.isdir(converted_dir):
        raise FileNotFoundError(f"변환 디렉토리가 없습니다: {converted_dir}")

    fragment_ids: List[str] = []
    for name in sorted(os.listdir(converted_dir)):
        if not name.endswith(_REPORT_SUFFIX):
            continue
        report_path = os.path.join(converted_dir, name)
        try:
            with open(report_path, encoding="utf-8") as fp:
                report = json.load(fp)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("리포트 읽기 실패, 건너뜀: %s (%s)", name, exc)
            continue
        if report.get("status") in statuses:
            fragment_ids.append(name[: -len(_REPORT_SUFFIX)])
    return fragment_ids


def _reset(
    checkpoint: Dict, targets: List[str]
) -> Dict[str, int]:
    """
    체크포인트에서 대상 조각을 완료 목록에서 제거하고 하류 phase 를 pending 으로 되돌린다.

    Args:
        checkpoint: 로드된 체크포인트 dict (in-place 수정)
        targets: 재변환 대상 조각 id 목록

    Returns:
        {"removed": 제거된 조각 수, "not_found": 완료목록에 없던 수}
    """
    detail = checkpoint.setdefault("phase4_detail", {})
    completed: List[str] = detail.get("completed_fragments", [])
    completed_set = set(completed)

    removed = 0
    not_found = 0
    target_set = set(targets)
    for frag in target_set:
        if frag in completed_set:
            removed += 1
        else:
            not_found += 1
            logger.warning("완료 목록에 없는 조각(이미 미완료?): %s", frag)

    # 완료 목록에서 대상 제거
    detail["completed_fragments"] = [
        f for f in completed if f not in target_set
    ]
    detail["completed"] = len(detail["completed_fragments"])

    # 하류 phase pending 복귀
    progress = checkpoint.setdefault("progress", {})
    for phase in _DOWNSTREAM_PHASES:
        if phase in progress:
            progress[phase] = _STATUS_PENDING

    return {"removed": removed, "not_found": not_found}


def main() -> int:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(
        description="Phase4 실패/부분 조각만 선택 재변환하도록 체크포인트를 되돌린다.",
    )
    parser.add_argument(
        "--config", required=True, help="oma.properties 경로"
    )
    parser.add_argument(
        "--status",
        nargs="+",
        default=["failed", "partial"],
        help="재변환 대상 status (기본: failed partial)",
    )
    parser.add_argument(
        "--fragment",
        nargs="+",
        default=None,
        help="특정 조각 id 를 직접 지정(지정 시 --status 자동탐색 대신 사용)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="변경 없이 대상만 출력",
    )
    args = parser.parse_args()

    try:
        config = Config(args.config)
    except ConfigError as exc:
        logger.error("설정 로드 실패: %s", exc)
        return 2

    checkpoint_path = config.get("CHECKPOINT_PATH")
    converted_dir = os.path.join(config.get("MAPPER_WORK_DIR"), "converted")

    try:
        checkpoint = _load_checkpoint(checkpoint_path)
    except (OSError, json.JSONDecodeError, FileNotFoundError) as exc:
        logger.error("체크포인트 로드 실패: %s", exc)
        return 2

    # 대상 조각 결정
    if args.fragment:
        targets = list(dict.fromkeys(args.fragment))  # 중복 제거, 순서 유지
        logger.info("명시 지정 조각 %d개: %s", len(targets), targets)
    else:
        statuses = set(args.status)
        try:
            targets = _find_fragments_by_status(converted_dir, statuses)
        except FileNotFoundError as exc:
            logger.error("%s", exc)
            return 2
        logger.info(
            "status%s 조각 %d개 발견: %s", sorted(statuses), len(targets), targets
        )

    if not targets:
        logger.info("재변환 대상이 없습니다. 종료.")
        return 0

    if args.dry_run:
        logger.info("[DRY-RUN] 변경 없음. 위 조각들이 재변환 대상입니다.")
        return 0

    # 백업 후 리셋
    run_id = checkpoint.get("run_id", "unknown")
    backup_path = f"{checkpoint_path}.bak-{run_id}"
    shutil.copy2(checkpoint_path, backup_path)
    logger.info("체크포인트 백업: %s", backup_path)

    stats = _reset(checkpoint, targets)

    with open(checkpoint_path, "w", encoding="utf-8") as fp:
        json.dump(checkpoint, fp, ensure_ascii=False, indent=2)

    logger.info(
        "리셋 완료: 제거 %d, 완료목록에 없던 %d. "
        "이제 `python3.11 scripts/run_oma.py --config %s --phase convert,merge` 로 재변환하세요.",
        stats["removed"], stats["not_found"], args.config,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
