"""
ValidationReporter 단위 테스트

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - 요약 통계/JSON/CSV 생성 및 성공률(스킵 제외) 테스트
"""

import csv
import json

import pytest

from oma.validation.comparator import (
    FAIL_ROW_COUNT,
    FAIL_VALUE,
    STATUS_FAILED,
    STATUS_PASSED,
    STATUS_SKIPPED,
    Comparison,
)
from oma.validation.reporter import ValidationReporter


def _comps():
    return [
        Comparison(tc_id="t1", status=STATUS_PASSED, matched=True),
        Comparison(tc_id="t2", status=STATUS_PASSED, matched=True),
        Comparison(tc_id="t3", status=STATUS_FAILED, failure_type=FAIL_ROW_COUNT,
                   severity="high", source_rows=5, target_rows=3),
        Comparison(tc_id="t4", status=STATUS_FAILED, failure_type=FAIL_VALUE,
                   severity="medium"),
        Comparison(tc_id="t5", status=STATUS_SKIPPED, note="procedure"),
    ]


@pytest.fixture
def reporter(tmp_path):
    return ValidationReporter(str(tmp_path / "reports"), run_id="run1")


def test_build_summary_counts(reporter):
    """passed/failed/skipped 집계"""
    s = reporter.build_summary(_comps())
    assert s["total_test_cases"] == 5
    assert s["passed"] == 2
    assert s["failed"] == 2
    assert s["skipped"] == 1


def test_success_rate_excludes_skipped(reporter):
    """성공률은 스킵 제외 (2/4 = 50%)"""
    s = reporter.build_summary(_comps())
    assert s["success_rate"] == 50.0


def test_failure_breakdown(reporter):
    """실패 유형 분포"""
    s = reporter.build_summary(_comps())
    assert s["failure_breakdown"][FAIL_ROW_COUNT] == 1
    assert s["failure_breakdown"][FAIL_VALUE] == 1


def test_generate_all_reports_creates_files(reporter, tmp_path):
    """3종 리포트 파일 생성"""
    reporter.generate_all_reports(_comps())
    rdir = tmp_path / "reports"
    assert (rdir / "validation-summary.json").exists()
    assert (rdir / "validation-details.json").exists()
    assert (rdir / "validation-failures.csv").exists()


def test_json_summary_content(reporter, tmp_path):
    """요약 JSON 내용 확인"""
    reporter.generate_all_reports(_comps())
    data = json.loads((tmp_path / "reports" / "validation-summary.json").read_text())
    assert data["run_id"] == "run1"
    assert data["passed"] == 2


def test_details_json_all_tcs(reporter, tmp_path):
    """상세 JSON에 모든 TC 포함"""
    reporter.generate_all_reports(_comps())
    data = json.loads((tmp_path / "reports" / "validation-details.json").read_text())
    assert len(data["test_cases"]) == 5


def test_csv_only_failures(reporter, tmp_path):
    """CSV에는 실패 TC만 (2건)"""
    reporter.generate_all_reports(_comps())
    with open(tmp_path / "reports" / "validation-failures.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    ids = {r["tc_id"] for r in rows}
    assert ids == {"t3", "t4"}
    # row_diff 계산 확인 (t3: 3-5 = -2)
    t3 = next(r for r in rows if r["tc_id"] == "t3")
    assert t3["row_diff"] == "-2"


def test_empty_comparisons(reporter):
    """빈 입력도 안전 (성공률 0)"""
    s = reporter.build_summary([])
    assert s["total_test_cases"] == 0
    assert s["success_rate"] == 0.0
