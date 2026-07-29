"""
실패 분석기(analyzer) 단위 테스트

변경 이력:
2026-07-28 | OMA Team | 초기 생성
  - TC json에서 mapper/sql_id 로드, statement_type 실행가능 우선, 안정번호 유형
"""

import json

import pytest

from oma.repair.analyzer import FailureAnalyzer


def _write(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


@pytest.fixture
def workspace(tmp_path):
    """report/testcase/mapping 디렉토리를 갖춘 최소 작업공간."""
    report = tmp_path / "reports"
    tcdir = tmp_path / "testcases"
    fragdir = tmp_path / "fragmented"
    for d in (report, tcdir, fragdir):
        d.mkdir()

    # resultMap과 select가 같은 sql_id로 충돌 → 실행가능(select) 우선
    _write(fragdir / "mapping.json", {
        "mappers": {
            "OrderMapper.xml": {
                "mapper_name": "OrderMapper",
                "fragments": [
                    {"sql_id": "getOrder", "statement_type": "resultMap"},
                    {"sql_id": "getOrder", "statement_type": "select"},
                ],
            }
        }
    })
    _write(tcdir / "OrderMapper_getOrder_tc001.json", {
        "mapper": "OrderMapper", "sql_id": "getOrder", "namespace": "x.OrderMapper",
    })
    return report, tcdir, fragdir


def test_analyze_builds_types_and_frag_id(workspace):
    """실패 TC가 유형으로 분류되고 frag_id가 실행가능 타입으로 구성된다."""
    report, tcdir, fragdir = workspace
    _write(report / "validation-details.json", {
        "run_id": "r1",
        "test_cases": [
            {"tc_id": "OrderMapper_getOrder_tc001", "status": "failed",
             "failure_type": "execution_error",
             "note": "target: ERROR: function to_char(numeric) does not exist",
             "mapper": "OrderMapper", "sql_id": "getOrder"},
            {"tc_id": "x", "status": "passed"},
        ],
    })
    analyzer = FailureAnalyzer(str(report), str(tcdir), str(fragdir / "mapping.json"))
    plan = analyzer.analyze()

    assert plan["summary"] == {"total": 2, "passed": 1, "failed": 1}
    assert len(plan["types"]) == 1
    t = plan["types"][0]
    assert t["no"] == 1
    assert t["action"] == "repair"
    frag = t["fragments"][0]
    # 실행가능 타입(select) 우선 → resultMap 아님
    assert frag["frag_id"] == "OrderMapper__select__getOrder"


def test_lookup_falls_back_to_tc_json(workspace):
    """상세 항목에 mapper/sql_id가 없으면 testcases/{tc_id}.json에서 읽는다."""
    report, tcdir, fragdir = workspace
    _write(report / "validation-details.json", {
        "test_cases": [
            {"tc_id": "OrderMapper_getOrder_tc001", "status": "failed",
             "failure_type": "execution_error",
             "note": "target: ERROR: function to_char(numeric) does not exist"},
        ],
    })
    analyzer = FailureAnalyzer(str(report), str(tcdir), str(fragdir / "mapping.json"))
    plan = analyzer.analyze()
    frag = plan["types"][0]["fragments"][0]
    assert frag["mapper"] == "OrderMapper"
    assert frag["sql_id"] == "getOrder"


def test_missing_details_raises(tmp_path):
    """validation-details.json이 없으면 FileNotFoundError."""
    analyzer = FailureAnalyzer(str(tmp_path), str(tmp_path), str(tmp_path / "m.json"))
    with pytest.raises(FileNotFoundError):
        analyzer.analyze()


def test_render_report_contains_type(workspace):
    """마크다운 보고서에 유형/그룹이 포함된다."""
    report, tcdir, fragdir = workspace
    _write(report / "validation-details.json", {
        "test_cases": [
            {"tc_id": "OrderMapper_getOrder_tc001", "status": "failed",
             "failure_type": "execution_error",
             "note": "target: ERROR: function to_char(numeric) does not exist",
             "mapper": "OrderMapper", "sql_id": "getOrder"},
        ],
    })
    analyzer = FailureAnalyzer(str(report), str(tcdir), str(fragdir / "mapping.json"))
    md = FailureAnalyzer.render_report(analyzer.analyze())
    assert "A_미변환_Oracle함수" in md
    assert "OrderMapper" in md
