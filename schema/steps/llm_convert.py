"""
LLM 기반 오브젝트 변환 스텝 (2차 핵심)

triage 가 선별한 미변환/오류 오브젝트를 대상으로:
  1) 소스 Oracle 에서 원본 DDL 추출(dbms_metadata.get_ddl)
  2) Bedrock LLM 으로 PostgreSQL DDL 변환(oma.properties 모델)
  3) 변환 결과를 타겟 PostgreSQL 에 적용(DDLApplier 재사용)

정규식으로 SQL 을 파싱하지 않는다(마크다운 펜스 제거만 라인 기반).
자격증명/모델/리전은 config·Secrets Manager 주입(하드코딩 금지).

변경 이력:
2026-08-05 | OMA Team | 초기 생성
  - LlmConverter.convert_targets(): DDL추출→LLM변환→타겟적용, 결과 요약
2026-08-05 | OMA Team | 패키지 네이밍 규칙 추가
  - 패키지 내부 프로시저/함수는 <패키지명>_<프로시저명> 형태 독립 함수로 변환
    (앱 변환 단계가 이 규칙에 맞춰 호출부를 변환할 수 있도록)
2026-08-05 | OMA Team | ROW_COUNT 변환 지침 추가
  - GET STACKED DIAGNOSTICS ROW_COUNT 오변환 방지(→ GET DIAGNOSTICS)
"""

import logging
from typing import Any, Dict, List, Optional

from db.executor import DBExecutor, ExecutorError
from steps.ddl_apply import DDLApplier

logger = logging.getLogger(__name__)

# Oracle dbms_metadata 오브젝트 타입 매핑(공백→언더스코어)
# 예: "PACKAGE BODY" → "PACKAGE_BODY", "TYPE BODY" → "TYPE_BODY"
_ORACLE_GET_DDL_SQL = "SELECT DBMS_METADATA.GET_DDL(:otype, :oname, :oschema) AS DDL FROM dual"

# PL/SQL 계열 오브젝트 타입(공백 정규화 후 판정)
_PACKAGE_TYPES = {"PACKAGE", "PACKAGE_BODY"}

# 패키지 전용 네이밍 규칙 지시(패키지 타입일 때만 프롬프트에 삽입).
# PostgreSQL 에는 패키지 개념이 없으므로 내부 프로시저/함수를 독립 함수로 펼치되,
# 앱 변환 단계가 호출부를 규칙적으로 치환할 수 있도록 이름을 고정한다.
_PACKAGE_RULES = """
Package-specific rules (CRITICAL — PostgreSQL has no packages):
- Flatten the package: emit each procedure/function inside the package as a
  SEPARATE standalone PostgreSQL function.
- Name every emitted function as "<package_name>_<subprogram_name>" (lowercase),
  e.g. package MY_PKG procedure DO_WORK -> function my_pkg_do_work.
  This naming is a hard contract: the later application-conversion step rewrites
  every call site to this exact pattern. Do NOT invent other names or nesting.
- Update all INTERNAL calls between package members to use the same
  "<package_name>_<subprogram_name>" names.
- Convert package-level variables/constants/cursors appropriately (e.g. as
  function-local state or separate objects); do not silently drop them.
"""


def _build_prompt(
    obj_type: str, obj_name: str, target_schema: str, oracle_ddl: str
) -> str:
    """
    오브젝트 타입에 맞는 변환 프롬프트를 조립한다.

    Args:
        obj_type: 오브젝트 타입(예: PROCEDURE, PACKAGE BODY)
        obj_name: 오브젝트명
        target_schema: 타겟 스키마명(소문자)
        oracle_ddl: 원본 Oracle DDL

    Returns:
        LLM 에 전달할 프롬프트 문자열
    """
    normalized = obj_type.strip().upper().replace(" ", "_")
    package_rules = _PACKAGE_RULES if normalized in _PACKAGE_TYPES else ""
    return _PROMPT_TEMPLATE.format(
        obj_type=obj_type,
        obj_name=obj_name,
        target_schema=target_schema,
        oracle_ddl=oracle_ddl,
        package_rules=package_rules,
    )


# LLM 변환 프롬프트 템플릿(설명 없이 DDL 만 반환하도록 지시)
_PROMPT_TEMPLATE = """You are migrating an Oracle database object to PostgreSQL (Aurora PostgreSQL compatible).

Convert the following Oracle {obj_type} named "{obj_name}" to PostgreSQL.

Oracle DDL:
```sql
{oracle_ddl}
```

Requirements:
- Convert PL/SQL to PL/pgSQL (use `CREATE OR REPLACE ... LANGUAGE plpgsql`, `$$` dollar-quoting).
- Map Oracle-specific constructs to PostgreSQL equivalents
  (NVL → COALESCE, SYSDATE → CURRENT_TIMESTAMP, DECODE → CASE, sequences .NEXTVAL → nextval(), etc.).
- For row counts use `GET DIAGNOSTICS <var> = ROW_COUNT;` (SQL%ROWCOUNT).
  Do NOT use `GET STACKED DIAGNOSTICS` for ROW_COUNT — STACKED DIAGNOSTICS is
  only valid inside an exception handler and does not support ROW_COUNT.
- Use lowercase, schema-qualified names in the target schema "{target_schema}".
- Preserve the original logic and behavior faithfully.
- Return ONLY the PostgreSQL DDL. No explanations, no commentary, no markdown fences.
{package_rules}
PostgreSQL DDL:"""


class LlmConvertError(Exception):
    """LLM 변환 스텝 오류."""


def strip_markdown_fence(text: str) -> str:
    """
    LLM 응답에서 선행/후행 마크다운 코드펜스를 제거한다.

    Args:
        text: LLM 응답 텍스트

    Returns:
        펜스가 제거된 DDL 텍스트
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.split("\n")
    # 첫 줄(``` 또는 ```sql) 제거
    lines = lines[1:]
    # 마지막 줄이 ``` 이면 제거
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


class LlmConverter:
    """
    triage 대상 오브젝트를 LLM 으로 변환·적용하는 변환기.

    Attributes:
        executor: source/target 이 등록된 DBExecutor
        llm: invoke(prompt) 를 제공하는 Bedrock 클라이언트
        source_schema: Oracle 스키마(대문자)
        target_schema: PostgreSQL 스키마(소문자)
    """

    def __init__(
        self,
        executor: DBExecutor,
        llm: Any,
        source_schema: str,
        target_schema: str,
        source_label: str = "source",
        target_label: str = "target",
    ) -> None:
        """
        Args:
            executor: DBExecutor(source/target 등록됨)
            llm: BedrockClient 등 invoke(prompt)->str 제공 객체
            source_schema: Oracle 스키마명(대문자)
            target_schema: PostgreSQL 스키마명(소문자)
            source_label: 소스 endpoint 라벨
            target_label: 타겟 endpoint 라벨
        """
        self.executor = executor
        self.llm = llm
        self.source_schema = source_schema
        self.target_schema = target_schema
        self.source_label = source_label
        self.target_label = target_label
        self._applier = DDLApplier(executor, target_label=target_label)

    def extract_oracle_ddl(self, object_type: str, object_name: str) -> str:
        """
        소스 Oracle 에서 오브젝트 원본 DDL 을 추출한다.

        Args:
            object_type: 오브젝트 타입(예: PROCEDURE, PACKAGE BODY)
            object_name: 오브젝트명

        Returns:
            원본 DDL 텍스트

        Raises:
            LlmConvertError: 추출 실패 또는 결과 없음
        """
        otype = object_type.strip().upper().replace(" ", "_")
        try:
            rows = self.executor.query(
                self.source_label,
                _ORACLE_GET_DDL_SQL,
                {
                    "otype": otype,
                    "oname": object_name.upper(),
                    "oschema": self.source_schema.upper(),
                },
            )
        except ExecutorError as e:
            raise LlmConvertError(
                f"DDL 추출 실패({object_type} {object_name}): {e}"
            ) from e
        if not rows:
            raise LlmConvertError(f"DDL 없음: {object_type} {object_name}")
        ddl = rows[0].get("DDL")
        # oracledb thin 모드는 LOB 를 str 로 반환. 방어적으로 read() 처리.
        if ddl is not None and not isinstance(ddl, str) and hasattr(ddl, "read"):
            ddl = ddl.read()
        if not ddl:
            raise LlmConvertError(f"DDL 비어있음: {object_type} {object_name}")
        return str(ddl)

    def convert_one(self, target: Dict[str, Any]) -> Dict[str, Any]:
        """
        단일 오브젝트를 추출→변환→적용한다.

        Args:
            target: triage 결과 항목({object_type, object_name, ...})

        Returns:
            {object_type, object_name, status, detail, pg_ddl?}
            status ∈ {CONVERTED, EXTRACT_FAILED, LLM_FAILED, APPLY_FAILED}
        """
        obj_type = target["object_type"]
        obj_name = target["object_name"]
        logger.info("변환 시작: %s %s", obj_type, obj_name)

        # 1) 원본 DDL 추출
        try:
            oracle_ddl = self.extract_oracle_ddl(obj_type, obj_name)
        except LlmConvertError as e:
            logger.error("  추출 실패: %s", e)
            return {
                "object_type": obj_type,
                "object_name": obj_name,
                "status": "EXTRACT_FAILED",
                "detail": str(e)[:300],
            }

        # 2) LLM 변환(패키지면 네이밍 규칙 지시 추가)
        prompt = _build_prompt(
            obj_type=obj_type,
            obj_name=obj_name,
            target_schema=self.target_schema.lower(),
            oracle_ddl=oracle_ddl,
        )
        try:
            raw = self.llm.invoke(prompt)
        except Exception as e:  # noqa: BLE001 - 다양한 LLM 예외 수용
            logger.error("  LLM 변환 실패: %s", e)
            return {
                "object_type": obj_type,
                "object_name": obj_name,
                "status": "LLM_FAILED",
                "detail": str(e)[:300],
            }
        pg_ddl = strip_markdown_fence(raw)
        if not pg_ddl:
            return {
                "object_type": obj_type,
                "object_name": obj_name,
                "status": "LLM_FAILED",
                "detail": "빈 변환 결과",
            }

        # 3) 타겟 적용(문장 단위, already exists 는 skip)
        apply_result = self._applier.apply_text(pg_ddl)
        if apply_result["failed"] > 0:
            logger.warning(
                "  적용 일부 실패: %s %s (failed=%d)",
                obj_type,
                obj_name,
                apply_result["failed"],
            )
            return {
                "object_type": obj_type,
                "object_name": obj_name,
                "status": "APPLY_FAILED",
                "detail": apply_result["failed_statements"],
                "pg_ddl": pg_ddl,
            }

        logger.info("  변환·적용 완료: %s %s", obj_type, obj_name)
        return {
            "object_type": obj_type,
            "object_name": obj_name,
            "status": "CONVERTED",
            "detail": apply_result,
            "pg_ddl": pg_ddl,
        }

    def convert_targets(
        self, targets: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        triage 대상 전체를 순차 변환한다.

        Args:
            targets: triage.select_targets 결과 리스트

        Returns:
            {"total", "converted", "failed", "results": [...]}
        """
        results: List[Dict[str, Any]] = []
        converted = 0
        for target in targets:
            res = self.convert_one(target)
            results.append(res)
            if res["status"] == "CONVERTED":
                converted += 1

        summary = {
            "total": len(targets),
            "converted": converted,
            "failed": len(targets) - converted,
            "results": results,
        }
        logger.info(
            "LLM 변환 요약: total=%d converted=%d failed=%d",
            summary["total"],
            converted,
            summary["failed"],
        )
        return summary
