"""
타겟 bigint 컬럼 범위 초과 교정 스텝 (3차 full-load 보조)

1차(DMS SC)가 Oracle NUMBER(정밀도 무제한/≥19)를 PostgreSQL bigint 로 변환하는데,
소스 실제 값이 bigint 최대(9223372036854775807, 19자리)를 넘으면 full-load 시
"value ... is out of range for type bigint" 로 적재가 실패한다.

이 스텝은 소스/타겟을 대조해 그런 컬럼만 골라 타겟 컬럼 타입을 numeric 으로
넓힌다(데이터 손실 없음). 대상은 자동 판별하며, 하드코딩하지 않는다.

판별:
  1. 타겟 스키마에서 bigint(int8) 컬럼 목록 조회(information_schema)
  2. 각 컬럼의 소스 Oracle 최대 절대값이 bigint 최대를 넘는지 확인
  3. 넘으면 ALTER TABLE ... ALTER COLUMN ... TYPE numeric USING col::numeric

설계:
  - executor 의 'source'(Oracle) + 'target'(PostgreSQL) endpoint 모두 사용.
  - 소스 대문자 / 타겟 소문자 오브젝트명 차이를 감안(소스 조회는 대문자).
  - 정규식 파싱 없음(카탈로그/information_schema 만 사용).

변경 이력:
2026-08-05 | OMA Team | 초기 생성
  - bigint 범위 초과 정수 컬럼을 numeric 으로 자동 교정(적재 out-of-range 방지)
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# PostgreSQL bigint 최대값(부호 있는 64-bit)
_BIGINT_MAX = 9223372036854775807

# 타겟 스키마의 bigint 컬럼 목록(information_schema)
_TARGET_BIGINT_SQL = """
SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = %s
  AND data_type = 'bigint'
ORDER BY table_name, column_name
"""


class BigintWidenError(Exception):
    """bigint 컬럼 교정 오류."""


class BigintWidener:
    """
    bigint 범위 초과 타겟 컬럼을 numeric 으로 교정하는 스텝.

    Attributes:
        executor: 'source'/'target' endpoint 가 등록된 DBExecutor
        source_schema: 소스 Oracle 스키마(대문자)
        target_schema: 타겟 PostgreSQL 스키마(소문자)
    """

    _SOURCE = "source"
    _TARGET = "target"

    def __init__(
        self,
        executor: Any,
        source_schema: str,
        target_schema: str,
    ) -> None:
        """
        Args:
            executor: 'source'(Oracle) + 'target'(PostgreSQL) 등록된 DBExecutor
            source_schema: 소스 Oracle 스키마명(대문자)
            target_schema: 타겟 PostgreSQL 스키마명(소문자)
        """
        self.executor = executor
        self.source_schema = source_schema
        self.target_schema = target_schema

    def _quote(self, ident: str) -> str:
        """
        식별자를 큰따옴표로 안전하게 감싼다(내부 " 이스케이프).

        Args:
            ident: 식별자

        Returns:
            큰따옴표로 감싼 식별자
        """
        return '"' + ident.replace('"', '""') + '"'

    def _target_bigint_columns(self) -> List[Dict[str, str]]:
        """
        타겟 스키마의 bigint 컬럼 목록을 조회한다.

        Returns:
            [{"table_name", "column_name"}, ...]

        Raises:
            BigintWidenError: 조회 실패 시
        """
        try:
            rows = self.executor.query(
                self._TARGET, _TARGET_BIGINT_SQL, [self.target_schema]
            )
        except Exception as e:  # noqa: BLE001
            raise BigintWidenError(f"타겟 bigint 컬럼 조회 실패: {e}") from e
        return [
            {"table_name": r["table_name"], "column_name": r["column_name"]}
            for r in rows
        ]

    def _source_max_abs(self, table: str, column: str) -> Optional[int]:
        """
        소스 Oracle 컬럼의 최대 절대값을 조회한다(정수 컬럼 전제).

        타겟은 소문자, 소스는 대문자이므로 대문자로 변환해 조회한다.

        Args:
            table: 타겟 테이블명(소문자)
            column: 타겟 컬럼명(소문자)

        Returns:
            최대 절대값(int) 또는 None(값 없음/컬럼 없음)
        """
        src_tab = self._quote(table.upper())
        src_col = self._quote(column.upper())
        sql = (
            f"SELECT MAX(ABS({src_col})) AS MX "
            f"FROM {self._quote(self.source_schema.upper())}.{src_tab}"
        )
        try:
            rows = self.executor.query(self._SOURCE, sql)
        except Exception as e:  # noqa: BLE001 - 소스에 없는 컬럼/테이블은 skip
            logger.warning(
                "소스 최대값 조회 skip: %s.%s (%s)", table, column, e
            )
            return None
        if rows and rows[0].get("MX") is not None:
            return int(rows[0]["MX"])
        return None

    def _widen_column(self, table: str, column: str) -> None:
        """
        타겟 컬럼 타입을 numeric 으로 변경한다.

        Args:
            table: 타겟 테이블명(소문자)
            column: 타겟 컬럼명(소문자)

        Raises:
            Exception: ALTER 실패 시(호출자에서 수집)
        """
        tbl = self._quote(self.target_schema) + "." + self._quote(table)
        col = self._quote(column)
        sql = (
            f"ALTER TABLE {tbl} ALTER COLUMN {col} TYPE numeric "
            f"USING {col}::numeric"
        )
        self.executor.execute(self._TARGET, sql)

    def widen_overflowing(self) -> Dict[str, Any]:
        """
        bigint 범위를 넘는 타겟 컬럼을 numeric 으로 교정한다.

        Returns:
            {"checked", "widened", "failed",
             "columns": [{table, column, max_value}, ...],
             "errors": [{table, column, error}, ...]}

        Raises:
            BigintWidenError: 타겟 컬럼 목록 조회 실패 시
        """
        candidates = self._target_bigint_columns()
        widened: List[Dict[str, Any]] = []
        errors: List[Dict[str, str]] = []
        for c in candidates:
            table, column = c["table_name"], c["column_name"]
            mx = self._source_max_abs(table, column)
            if mx is None or mx <= _BIGINT_MAX:
                continue
            try:
                self._widen_column(table, column)
                widened.append(
                    {"table": table, "column": column, "max_value": str(mx)}
                )
                logger.info(
                    "  bigint→numeric 교정: %s.%s (max=%s)", table, column, mx
                )
            except Exception as e:  # noqa: BLE001
                errors.append(
                    {"table": table, "column": column, "error": str(e)}
                )
                logger.warning(
                    "  bigint 교정 실패: %s.%s (%s)", table, column, e
                )
        logger.info(
            "bigint 범위 교정 완료: checked=%d widened=%d failed=%d",
            len(candidates), len(widened), len(errors),
        )
        return {
            "checked": len(candidates),
            "widened": len(widened),
            "failed": len(errors),
            "columns": widened,
            "errors": errors,
        }
