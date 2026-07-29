"""
검증 결과 리포트 생성 모듈

Comparison 목록을 받아 콘솔 요약 + JSON(summary/details) + CSV(failures) 리포트를
생성한다. (HTML 상세 시각화는 향후 확장)

출력 위치: REPORT_DIR (기본 projects/<app>/reports/)
  - validation-summary.json : 전체 통계/실패유형 분포
  - validation-details.json : TC별 상세 비교
  - validation-failures.csv : 실패 TC (Excel 검토용)

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - ValidationReporter: print_summary/generate_json_summary/details/csv/
    generate_all_reports
  - 통계 집계(passed/failed/skipped, 실패유형 분포, 성공률)
"""

import csv
import json
import logging
import os
from collections import Counter
from typing import Any, Dict, List

from oma.validation.comparator import (
    STATUS_FAILED,
    STATUS_PASSED,
    STATUS_SKIPPED,
    Comparison,
    ResultComparator,
)

logger = logging.getLogger(__name__)

_SUMMARY_FILE = "validation-summary.json"
_DETAILS_FILE = "validation-details.json"
_FAILURES_CSV = "validation-failures.csv"


class ValidationReporter:
    """
    검증 리포트 생성기

    Attributes:
        report_dir: 리포트 출력 디렉토리
    """

    def __init__(self, report_dir: str, run_id: str = "") -> None:
        """
        초기화

        Args:
            report_dir: 리포트 출력 디렉토리
            run_id: 실행 식별자 (리포트에 기록)
        """
        self.report_dir = report_dir
        self.run_id = run_id

    def generate_all_reports(self, comparisons: List[Comparison]) -> Dict[str, Any]:
        """
        모든 형식의 리포트를 생성하고 요약 통계를 반환한다.

        Args:
            comparisons: Comparison 리스트

        Returns:
            요약 통계 dict
        """
        os.makedirs(self.report_dir, exist_ok=True)
        summary = self.build_summary(comparisons)

        self.generate_json_summary(summary)
        self.generate_json_details(comparisons)
        self.generate_csv_failures(comparisons)
        self.print_summary(summary)
        return summary

    def build_summary(self, comparisons: List[Comparison]) -> Dict[str, Any]:
        """
        통계 요약을 만든다.

        Args:
            comparisons: Comparison 리스트

        Returns:
            요약 dict
        """
        total = len(comparisons)
        passed = sum(1 for c in comparisons if c.status == STATUS_PASSED)
        failed = sum(1 for c in comparisons if c.status == STATUS_FAILED)
        skipped = sum(1 for c in comparisons if c.status == STATUS_SKIPPED)

        failure_breakdown = Counter(
            c.failure_type for c in comparisons
            if c.status == STATUS_FAILED and c.failure_type
        )
        # 성공률은 스킵 제외 기준
        denom = total - skipped
        success_rate = round(passed / denom * 100, 1) if denom > 0 else 0.0

        return {
            "run_id": self.run_id,
            "total_test_cases": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "success_rate": success_rate,
            "failure_breakdown": dict(failure_breakdown),
        }

    def generate_json_summary(self, summary: Dict[str, Any]) -> str:
        """요약 JSON을 저장하고 경로를 반환한다."""
        path = os.path.join(self.report_dir, _SUMMARY_FILE)
        self._write_json(path, summary)
        return path

    def generate_json_details(self, comparisons: List[Comparison]) -> str:
        """상세 JSON을 저장하고 경로를 반환한다."""
        path = os.path.join(self.report_dir, _DETAILS_FILE)
        details = {
            "run_id": self.run_id,
            "test_cases": [ResultComparator.to_dict(c) for c in comparisons],
        }
        self._write_json(path, details)
        return path

    def generate_csv_failures(self, comparisons: List[Comparison]) -> str:
        """실패 TC를 CSV로 저장하고 경로를 반환한다."""
        path = os.path.join(self.report_dir, _FAILURES_CSV)
        failures = [c for c in comparisons if c.status == STATUS_FAILED]

        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "tc_id", "failure_type", "severity",
                "source_rows", "target_rows", "row_diff", "note",
            ])
            for c in failures:
                writer.writerow([
                    c.tc_id, c.failure_type or "", c.severity or "",
                    c.source_rows, c.target_rows,
                    c.target_rows - c.source_rows,
                    (c.note or "").replace("\n", " "),
                ])
        return path

    def print_summary(self, summary: Dict[str, Any]) -> None:
        """콘솔에 요약을 출력한다."""
        total = summary["total_test_cases"]
        logger.info("=" * 50)
        logger.info("Validation Completed")
        logger.info("=" * 50)
        logger.info("Total: %d", total)
        logger.info("  Passed : %d (%.1f%%)", summary["passed"], summary["success_rate"])
        logger.info("  Failed : %d", summary["failed"])
        logger.info("  Skipped: %d", summary["skipped"])
        if summary["failure_breakdown"]:
            logger.info("Failure breakdown:")
            for ftype, count in summary["failure_breakdown"].items():
                logger.info("  %-22s: %d", ftype, count)
        logger.info("Reports: %s/", self.report_dir)

    @staticmethod
    def _write_json(path: str, data: Any) -> None:
        """JSON을 파일로 저장한다."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
