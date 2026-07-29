"""
조각 수정(repair) 전용 프롬프트

변환(prompts.py)과 달리, 이미 변환된 조각이 검증에서 낸 에러를 근거로 "최소 수정"을
지시한다. 입력 3종(원본 조각 / 현재 변환 조각 / 검증 에러)을 주고, 에러를 해소하는
수정본과 변경 요약을 JSON으로 받는다.

설계: design/20-iterative-repair-loop.md §3.2

원칙:
  - 함수 매핑을 하드코딩/나열하지 않는다. 모델이 에러와 문맥을 보고 판단하게 한다.
  - MyBatis 동적 태그/XML 구조/이미 올바른 부분은 보존(최소 수정).
  - 방언 힌트는 dialect_rules.json에서 최소만 주입(변환 프롬프트와 동일 소스).

변경 이력:
2026-07-28 | OMA Team | 초기 생성
  - build_repair_system_prompt/build_repair_prompt + 출력 JSON 계약
"""

import json
from typing import Any, Dict

from oma.converter.prompts import _load_dialect_rule

# 수정 출력 JSON 계약
_REPAIR_CONTRACT = {
    "fixed_sql": "수정된 조각 XML 전문 (statement 태그 + 동적태그 보존). "
                 "수정 불필요하면 현재 조각 그대로.",
    "fix_summary": "무엇을 왜 고쳤는지 한 줄 요약 (한국어)",
    "changed": "true | false (실제 변경 여부)",
}


def build_repair_system_prompt(source_type: str, target_type: str) -> str:
    """
    조각 수정 지침을 담은 시스템 프롬프트를 구성한다(방언 힌트 주입).

    Args:
        source_type: 소스 DB 타입(oracle/epas)
        target_type: 타겟 DB 타입(postgres/mysql)

    Returns:
        시스템 프롬프트 문자열
    """
    rule = _load_dialect_rule(source_type, target_type)
    cast_syntax = rule.get("cast_syntax", "타겟 DB 표준 캐스팅 문법")
    notes = "\n".join(f"  - {n}" for n in rule.get("notes", []))

    return (
        f"당신은 {source_type}→{target_type} 변환 결과를 검증 에러 기반으로 고치는 "
        "전문가입니다. 이미 변환된 MyBatis 매퍼 조각이 타겟 DB에서 실행 에러를 냈습니다. "
        "그 에러를 해소하도록 조각을 **최소 수정**합니다.\n\n"

        "## 수정 원칙\n"
        "- 주어진 검증 에러를 해소하는 것이 목표입니다. 에러와 무관한 부분은 절대 "
        "바꾸지 마세요(최소 수정).\n"
        "- MyBatis 동적 태그(<if>/<choose>/<foreach>/<where> 등)와 XML 구조, CDATA, "
        "주석, statement 태그/id/속성을 그대로 보존합니다.\n"
        f"- 남아있는 {source_type} 전용 함수/문법을 {target_type} 표준으로 바꿉니다. "
        "구체 대응은 에러 메시지와 문맥을 보고 스스로 판단하세요(의미 보존이 최우선). "
        "예를 들어 '함수가 없다'는 에러는 인자 형태/개수가 타겟과 맞지 않거나 함수명이 "
        "다를 수 있으니, 결과 의미(NULL 처리·문자열화·날짜 포맷·정렬)가 바뀌지 않도록 "
        "고칩니다.\n"
        f"- 캐스팅이 필요하면 타겟 문법을 씁니다: {cast_syntax}. 캐스팅은 바인드/리터럴에만, "
        "컬럼 좌변에는 적용하지 않습니다(인덱스 보호).\n"
        f"방언 힌트:\n{notes}\n\n"

        "## 원본 조각의 의미가 기준\n"
        "원본(소스 방언) 조각을 함께 제공합니다. 무엇을 하려던 SQL인지 파악하는 근거로만 "
        "쓰고, 출력은 타겟 방언 수정본이어야 합니다.\n\n"

        "반드시 지정된 JSON 스키마로만 응답합니다. 코드펜스/설명 없이 순수 JSON."
    )


def build_repair_prompt(
    source_sql: str, current_sql: str, error: str
) -> str:
    """
    조각 수정용 사용자 프롬프트(데이터)를 만든다.

    Args:
        source_sql: 원본(소스 방언) 조각 XML (없으면 빈 문자열)
        current_sql: 현재 변환된 조각 XML (수정 대상)
        error: 검증 에러 메시지(note)

    Returns:
        사용자 프롬프트 문자열
    """
    contract_json = json.dumps(_REPAIR_CONTRACT, ensure_ascii=False, indent=2)
    source_block = source_sql.strip() or "(원본 조각 없음 - 현재 변환 조각만으로 판단)"

    return (
        "# 검증 에러 (이 에러를 해소해야 함)\n"
        "```\n"
        f"{error}\n"
        "```\n\n"
        "# 현재 변환 조각 (수정 대상)\n"
        "```xml\n"
        f"{current_sql}\n"
        "```\n\n"
        "# 원본 조각 (의미 파악용 참조)\n"
        "```xml\n"
        f"{source_block}\n"
        "```\n\n"
        "# 출력 형식 (이 JSON 구조로만 응답)\n"
        "```json\n"
        f"{contract_json}\n"
        "```"
    )
