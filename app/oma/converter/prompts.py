"""
변환 프롬프트 템플릿 모듈

Oracle/EPAS 매퍼를 PostgreSQL/MySQL로 변환하는 LLM 프롬프트를 구성한다.

설계 철학:
  - 고성능 모델(Opus 4.8 등)을 신뢰해 함수 변환 세부 규칙/퓨샷은 최소화한다.
    (NVL→COALESCE 같은 매핑을 일일이 나열하지 않고 모델 판단에 맡김)
  - 대신 이 도구의 핵심인 두 가지를 상세히 지시한다:
      (1) 형변환: 딕셔너리 근거로 바인드/리터럴에 명시적 캐스팅
      (2) param_mappings: 각 #{param}이 어느 table.column인지 + 딕셔너리 샘플값
          → TC 생성이 실제 샘플값을 쓰도록 (NOT NULL/타입 위반 방지)
  - 지침은 시스템 프롬프트로, 데이터(조각/딕셔너리)는 사용자 프롬프트로 분리.
  - 방언별 특이사항은 dialect_rules.json에서 최소 힌트만 주입 (멀티 소스/타겟).

지원 조합: oracle→postgres, oracle→mysql, epas→postgres (dialect_rules.json)

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - SYSTEM_PROMPT, build_conversion_prompt(), 출력 JSON 계약
2026-07-27 | OMA Team | 재설계
  - 멀티 소스/타겟(방언 힌트 주입), 함수 규칙 최소화(모델 신뢰),
    형변환+param_mappings 상세화, 지침을 시스템 프롬프트로 이동
"""

import json
import os
from typing import Any, Dict, Optional

_DIALECT_RULES_PATH = os.path.join(os.path.dirname(__file__), "dialect_rules.json")

# 출력 JSON 계약 (형변환 + TC 매핑 중심)
_OUTPUT_CONTRACT = {
    "conversion_status": "success | partial | failed",
    "converted_sql": "변환된 조각 XML 전문 (statement 태그 + 동적태그 보존)",
    "param_mappings": [
        {
            "param": "바인드 변수명 (예: userId)",
            "column": "추론한 table.column (소문자). 불명확하면 null",
            "data_type": "딕셔너리의 data_type 또는 null",
            "sample_value": "딕셔너리 sample_value (있으면 그대로, 없으면 null)",
            "cast_applied": "적용한 캐스팅 (예: ::INTEGER) 또는 null",
        }
    ],
    "type_casts": [
        {"original": "...", "converted": "...", "column": "table.col",
         "reason": "..."}
    ],
    "warnings": [
        {"severity": "high|medium|low", "type": "missing_column|char_padding|"
         "complex_query|performance", "issue": "...", "suggestion": "..."}
    ],
    "manual_review_required": False,
}


def _load_dialect_rule(source_type: str, target_type: str) -> Dict[str, Any]:
    """
    소스→타겟 방언 규칙을 로드한다.

    Args:
        source_type: 소스 DB 타입 (oracle/epas)
        target_type: 타겟 DB 타입 (postgres/mysql)

    Returns:
        방언 규칙 dict (없으면 빈 dict)
    """
    with open(_DIALECT_RULES_PATH, "r", encoding="utf-8") as f:
        rules = json.load(f)
    key = f"{source_type.lower()}_to_{target_type.lower()}"
    return rules.get(key, {})


def build_system_prompt(source_type: str, target_type: str) -> str:
    """
    변환 지침을 담은 시스템 프롬프트를 구성한다 (방언 힌트 주입).

    Args:
        source_type: 소스 DB 타입
        target_type: 타겟 DB 타입

    Returns:
        시스템 프롬프트 문자열
    """
    rule = _load_dialect_rule(source_type, target_type)
    cast_syntax = rule.get("cast_syntax", "타겟 DB 표준 캐스팅 문법")
    notes = "\n".join(f"  - {n}" for n in rule.get("notes", []))

    return (
        f"당신은 {source_type} SQL을 {target_type}로 변환하는 전문가입니다. "
        "MyBatis 매퍼 조각을 정확히 변환합니다.\n\n"

        "## 변환 (당신의 판단에 맡깁니다)\n"
        f"{source_type} 전용 함수/문법을 {target_type} 표준으로 변환하세요. "
        "일반적인 함수 대응은 스스로 판단하되, 의미(NULL 처리·연산 결과·정렬)가 "
        "바뀌지 않도록 보존하세요. MyBatis 동적 태그(<if>/<choose>/<foreach>)와 "
        "XML 구조는 그대로 유지합니다.\n"
        f"방언 힌트:\n{notes}\n\n"

        "## 형변환 (핵심 - 반드시 정확히)\n"
        f"캐스팅 문법: {cast_syntax}\n"
        "- 딕셔너리의 data_type을 근거로 숫자/날짜 타입 바인드 변수(#{...})와 "
        "리터럴에 명시적 캐스팅을 추가합니다.\n"
        "- 캐스팅은 바인드/리터럴에만. 컬럼 좌변에는 절대 적용하지 않습니다(인덱스 보호).\n"
        "- 문자열(varchar/text)은 캐스팅하지 않습니다. CHAR(n)은 패딩 주의를 warning으로.\n"
        "- 딕셔너리에 없는 컬럼은 원본 유지 + warning.\n\n"

        "## param_mappings (핵심 - TC 생성용)\n"
        "매퍼의 모든 #{param}에 대해 어느 table.column인지 추론하고, 딕셔너리에서 그 "
        "컬럼의 data_type과 sample_value를 찾아 반환하세요. 이 매핑으로 테스트 케이스가 "
        "실제 제약(NOT NULL/타입/길이)을 만족하는 샘플값을 씁니다. "
        "**모든 바인드 변수를 빠짐없이** 포함하세요.\n"
        "매핑 추론 가이드 (문맥을 최대한 활용):\n"
        "- `컬럼 = #{param}`, `#{param}` 형태의 WHERE/SET: 좌변 컬럼이 매핑 대상.\n"
        "- INSERT: 컬럼 리스트(IFID, IFNM, ...)와 VALUES 항목을 **순서대로 1:1 정렬**해 "
        "각 #{param}의 컬럼을 정한다. 변수명이 컬럼명과 달라도(예: #{surkey}가 "
        "INSERTURKEY/UPDATEURKEY 위치) 위치로 매핑한다. 같은 변수가 여러 컬럼에 쓰이면 "
        "각 위치의 컬럼으로 각각 매핑(대표 1개 컬럼의 타입 사용 가능).\n"
        "- <foreach>/<choose> 안의 파라미터도 해당 위치의 컬럼으로 매핑한다.\n"
        "- 함수로 감싼 경우(NVL(#{iftype},'R'))도 그 위치의 컬럼으로 매핑한다.\n"
        "- FROM/테이블 별칭을 분석해 정확한 table을 정한다. 정말 불명확할 때만 "
        "column/data_type/sample_value를 null로 둔다(그 외에는 반드시 추론).\n\n"

        "반드시 지정된 JSON 스키마로만 응답합니다. 코드펜스/설명 없이 순수 JSON."
    )


def build_conversion_prompt(
    fragment_content: str,
    dictionary_subset: Dict[str, Any],
) -> str:
    """
    조각 변환용 사용자 프롬프트(데이터)를 만든다.

    지침은 시스템 프롬프트에 있으므로, 여기서는 변환 대상 조각과 관련 딕셔너리,
    출력 형식만 전달한다.

    Args:
        fragment_content: 변환 대상 조각 XML
        dictionary_subset: {"table.column": {data_type, cast_hint, sample_value}}

    Returns:
        사용자 프롬프트 문자열
    """
    dict_json = json.dumps(dictionary_subset, ensure_ascii=False, indent=2)
    contract_json = json.dumps(_OUTPUT_CONTRACT, ensure_ascii=False, indent=2)

    return (
        "# 변환 대상 매퍼 조각\n"
        "```xml\n"
        f"{fragment_content}\n"
        "```\n\n"
        "# 스키마 딕셔너리 (이 조각 관련 컬럼: data_type/cast_hint/sample_value)\n"
        "```json\n"
        f"{dict_json}\n"
        "```\n\n"
        "# 출력 형식 (이 JSON 구조로만 응답)\n"
        "```json\n"
        f"{contract_json}\n"
        "```"
    )


# 하위호환: 기존 SYSTEM_PROMPT 상수를 참조하던 코드용 (oracle→postgres 기본)
SYSTEM_PROMPT = build_system_prompt("oracle", "postgres")
