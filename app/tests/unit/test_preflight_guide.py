"""
PreflightGuide 단위 테스트

변경 이력:
2026-07-28 | OMA Team | 초기 생성
  - 설정 스텁/Markdown 가이드 생성 테스트
"""

import json

from oma.preflight.guide import PreflightGuide
from oma.preflight.scanner import PreflightReport


def _report():
    r = PreflightReport()
    r.mapper_count = 3
    r.parsed_ok = 2
    r.ognl_methods = {"@com.example.util.StringUtil@isNotEmpty": 5}
    r.dollar_variables = {"tableName": 2, "orderBy": 1}
    r.unknown_type_aliases = {"camelMap": 4}
    r.parse_errors = [{"file": "bad.xml", "error": "StartTag: invalid element"}]
    r.procedure_calls = ["proc.xml"]
    return r


def test_config_stubs_structure():
    """스텁: variables/ognl_methods/type_aliases 항목 생성"""
    stubs = PreflightGuide.build_config_stubs(_report())
    assert "tableName" in stubs["variables"]
    assert stubs["variables"]["tableName"] == {"oracle": "", "postgres": ""}
    assert "@com.example.util.StringUtil@isNotEmpty" in stubs["ognl_methods"]
    assert "camelMap" in stubs["type_aliases"]


def test_config_stubs_json_serializable():
    """스텁은 JSON 직렬화 가능"""
    json.dumps(PreflightGuide.build_config_stubs(_report()))


def test_markdown_guide_contains_sections():
    """가이드: 각 이슈 섹션과 검출 항목 포함"""
    md = PreflightGuide.build_markdown_guide(_report())
    assert "# Pre-flight 조치 가이드" in md
    assert "OGNL 정적 메서드" in md
    assert "isNotEmpty" in md          # 검출 항목
    assert "${} 동적 변수" in md
    assert "tableName" in md
    assert "미지 타입 별칭" in md
    assert "camelMap" in md
    assert "XML 파싱 실패" in md
    assert "bad.xml" in md
    assert "프로시저 호출" in md


def test_markdown_guide_has_actions():
    """가이드: 조치 방법(어디에 반영) 안내 포함"""
    md = PreflightGuide.build_markdown_guide(_report())
    assert "special_variables.json" in md   # 변수/OGNL 반영 위치
    assert "classpath" in md                # OGNL 실전 방법
    assert "LenientConfiguration" in md      # 별칭 처리 설명


def test_empty_report_guide():
    """검출 없는 리포트도 '검출 없음' 섹션으로 안전"""
    md = PreflightGuide.build_markdown_guide(PreflightReport())
    assert "검출 없음" in md
