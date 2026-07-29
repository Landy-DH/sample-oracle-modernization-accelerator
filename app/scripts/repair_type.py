#!/usr/bin/env python3.11
"""
오류유형 단위 조각 수정 스크립트

repair-plan.json의 유형 번호를 받아, 그 유형에 속한 변환 조각들을 LLM으로
최소 수정(converted/<frag_id>.xml 덮어쓰기)한다. 수정 후 merge,validate를
다시 돌려 개선을 확인하고 analyze_failures로 재분석하면 한 iteration이 끝난다.

설계: design/20-iterative-repair-loop.md §3~4

사용:
  # 유형 목록 확인
  python3.11 scripts/repair_type.py --config oma.properties --list
  # 유형 1번 조각 중 2개만 먼저 수정(대화형 샘플 확인)
  python3.11 scripts/repair_type.py --config oma.properties --type 1 --limit 2
  # 유형 1번 전체 수정
  python3.11 scripts/repair_type.py --config oma.properties --type 1

  수정 후:
  python3.11 scripts/run_oma.py --config oma.properties --phase merge,validate
  python3.11 scripts/analyze_failures.py --config oma.properties

변경 이력:
2026-07-28 | OMA Team | 초기 생성
  - repair-plan.json 로드, --list/--type/--limit. FragmentRepairer로 조각 수정.
    수정은 converted/*.xml + report.json repair_history. TC는 재생성 안 함.
"""

import argparse
import json
import logging
import os
import sys

# 프로젝트 루트를 import 경로에 추가 (scripts/ 에서 실행)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from oma.converter.llm_client import LLMClient  # noqa: E402
from oma.repair.repairer import FragmentRepairer  # noqa: E402
from oma.utils.config import Config  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("repair_type")


def _load_plan(report_dir: str) -> dict:
    """repair-plan.json을 로드한다."""
    path = os.path.join(report_dir, "repair-plan.json")
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"repair-plan.json이 없습니다: {path} "
            "(먼저 analyze_failures.py 실행)"
        )
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _print_list(plan: dict) -> None:
    """유형 목록을 출력한다."""
    s = plan["summary"]
    print(f"실패 {s['failed']}/{s['total']} — 오류유형:")
    for t in plan["types"]:
        mark = "▶ repair" if t["action"] == "repair" else f"  {t['action']}"
        err = (t["representative_error"] or "").replace("\n", " ")[:60]
        print(f"  [{t['no']}] {t['group']:22s} {t['count']:4d}건  {mark}  {err}")


def main(argv=None) -> int:
    """
    CLI 진입점.

    Args:
        argv: 인자 리스트(테스트용). None이면 sys.argv 사용

    Returns:
        종료 코드(0 성공, 1 오류)
    """
    parser = argparse.ArgumentParser(
        description="오류유형 단위로 변환 조각을 LLM 수정"
    )
    parser.add_argument("--config", default="oma.properties", help="설정 파일 경로")
    parser.add_argument("--type", type=int, help="수정할 유형 번호(repair-plan의 no)")
    parser.add_argument("--limit", type=int, help="최대 조각 수(샘플 확인용)")
    parser.add_argument("--list", action="store_true", help="유형 목록만 출력")
    args = parser.parse_args(argv)

    if not os.path.isfile(args.config):
        print(f"[ERROR] 설정 파일을 찾을 수 없습니다: {args.config}", file=sys.stderr)
        return 1

    config = Config(args.config)
    report_dir = config.get("REPORT_DIR")
    mapper_work = config.get("MAPPER_WORK_DIR")

    try:
        plan = _load_plan(report_dir)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    if args.list or args.type is None:
        _print_list(plan)
        if args.type is None and not args.list:
            print("\n수정하려면 --type <번호> 를 지정하세요.")
        return 0

    repairer = FragmentRepairer(
        converted_dir=os.path.join(mapper_work, "converted"),
        fragmented_dir=os.path.join(mapper_work, "fragmented"),
        llm_client=LLMClient(config),
        source_type=config.get("SOURCE_DB_TYPE", "oracle"),
        target_type=config.get("TARGET_DB_TYPE", "postgres"),
    )

    try:
        outcomes = repairer.repair_type(plan, args.type, limit=args.limit)
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    repaired = sum(1 for o in outcomes if o.status == "repaired")
    skipped = sum(1 for o in outcomes if o.status == "skipped")
    failed = sum(1 for o in outcomes if o.status == "failed")
    logger.info(
        "유형 %d 수정 결과: 수정 %d, 스킵 %d, 실패 %d",
        args.type, repaired, skipped, failed,
    )
    for o in outcomes:
        if o.status != "repaired":
            logger.info("  [%s] %s: %s", o.status, o.frag_id,
                        o.fix_summary or o.error)

    print(
        "\n다음 단계:\n"
        f"  python3.11 scripts/run_oma.py --config {args.config} "
        "--phase merge,validate\n"
        f"  python3.11 scripts/analyze_failures.py --config {args.config}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
