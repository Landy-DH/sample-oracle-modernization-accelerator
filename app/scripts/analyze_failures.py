#!/usr/bin/env python3.11
"""
검증 실패 분석 스크립트 (오류유형 분류 → repair-plan 생성)

validate(Phase6) 종료 후 실행한다. reports/validation-details.json을 읽어
실패를 오류 유형별로 분류하고, 유형 번호 + 영향 조각(frag_id) 리스트를 담은
repair-plan.json과 사람용 보고서(failure-report.md)를 생성한다.

설계: design/20-iterative-repair-loop.md

사용:
  python3.11 scripts/analyze_failures.py --config oma.properties
  python3.11 scripts/analyze_failures.py --config oma.properties --show   # 표준출력에 보고서

산출물(REPORT_DIR):
  - repair-plan.json    : 유형 번호 + 영향 조각(frag_id) + 대표 에러 (repair 입력)
  - failure-report.md   : 사람용 유형별 보고서

변경 이력:
2026-07-28 | OMA Team | 초기 생성
  - FailureAnalyzer 래핑 CLI. TC json에서 mapper/sql_id 로드, statement_type
    실행가능 우선 해소. repair-plan.json/failure-report.md 저장.
"""

import argparse
import json
import logging
import os
import sys

# 프로젝트 루트를 import 경로에 추가 (scripts/ 에서 실행)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from oma.repair.analyzer import FailureAnalyzer  # noqa: E402
from oma.utils.config import Config  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("analyze_failures")


def main(argv=None) -> int:
    """
    CLI 진입점.

    Args:
        argv: 인자 리스트 (테스트용). None이면 sys.argv 사용

    Returns:
        종료 코드 (0 성공, 1 오류)
    """
    parser = argparse.ArgumentParser(
        description="검증 실패를 오류유형으로 분류해 repair-plan 생성"
    )
    parser.add_argument("--config", default="oma.properties", help="설정 파일 경로")
    parser.add_argument(
        "--show", action="store_true", help="보고서를 표준출력에도 출력"
    )
    args = parser.parse_args(argv)

    if not os.path.isfile(args.config):
        print(f"[ERROR] 설정 파일을 찾을 수 없습니다: {args.config}", file=sys.stderr)
        return 1

    config = Config(args.config)
    report_dir = config.get("REPORT_DIR")
    testcase_dir = config.get("TESTCASE_DIR")
    mapping_path = os.path.join(
        config.get("MAPPER_WORK_DIR"), "fragmented", "mapping.json"
    )

    analyzer = FailureAnalyzer(report_dir, testcase_dir, mapping_path)
    try:
        plan = analyzer.analyze()
    except FileNotFoundError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    plan_path = os.path.join(report_dir, "repair-plan.json")
    report_path = os.path.join(report_dir, "failure-report.md")
    os.makedirs(report_dir, exist_ok=True)
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    report_md = FailureAnalyzer.render_report(plan)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    s = plan["summary"]
    logger.info(
        "분석 완료: 실패 %d/%d, 유형 %d개 → %s",
        s["failed"], s["total"], len(plan["types"]), plan_path,
    )
    for t in plan["types"]:
        logger.info(
            "  [%d] %s: %d건 (%s)",
            t["no"], t["group"], t["count"], t["action"],
        )
    if args.show:
        print(report_md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
