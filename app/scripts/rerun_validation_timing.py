"""
검증 재실행 (성능 시간 수집용 일회성 스크립트)

WorkflowOrchestrator의 체크포인트가 phase6_validation을 완료로 표시해 --phase validate가
건너뛰므로, ValidationOrchestrator를 직접 호출해 재검증만 수행한다. 다른 Phase의
체크포인트 상태는 건드리지 않는다.

생성물: REPORT_DIR에 validation-*.json 갱신 + performance-timings.csv/json 신규.

변경 이력:
2026-07-29 | Claude | 초기 생성 (실행 시간 수집 재검증)
  - run_oma._build_validation 재사용, config.TESTCASE_DIR로 validate_all 호출
  - 원인: 체크포인트가 phase6 완료 처리 → 정식 CLI로는 재검증 불가
"""

import os
import sys

# 프로젝트 루트를 import 경로에 추가 (scripts/ 에서 실행 대응)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from oma.utils.config import Config  # noqa: E402
from oma.utils.logger import setup_logger  # noqa: E402
from scripts.run_oma import _build_validation  # noqa: E402

logger = setup_logger("rerun_validation_timing")


def main() -> int:
    """thepop 검증을 재실행하고 성능 리포트를 생성한다."""
    config = Config("oma.properties")
    testcase_dir = config.get("TESTCASE_DIR")
    logger.info("재검증 시작: testcase_dir=%s", testcase_dir)

    validation = _build_validation(config)
    summary = validation.validate_all(testcase_dir)

    logger.info(
        "재검증 완료: total=%s passed=%s failed=%s skipped=%s",
        summary.get("total_test_cases"), summary.get("passed"),
        summary.get("failed"), summary.get("skipped"),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
