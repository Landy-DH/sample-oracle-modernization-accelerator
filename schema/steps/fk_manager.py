"""
타겟 스키마 외래키(FK) 캡처/드랍/재생성 스텝 (3차 full-load 보조)

DMS full-load 는 테이블을 병렬로 적재하므로 자식 테이블이 부모보다 먼저
적재되면 FK 참조 무결성 위반으로 로딩이 실패한다. 이를 피하려고:
  1. full-load 전  : 타겟 스키마의 모든 FK 를 "정의째" 백업 후 DROP
  2. full-load 후  : 백업한 정의로 FK 를 다시 ADD

FK 정의는 정규식 파싱 없이 PostgreSQL 카탈로그 함수 pg_get_constraintdef()
로 그대로(문자열) 얻어 재생성에 사용한다.

설계:
  - executor 의 'target' endpoint(PostgreSQL)만 사용.
  - 캡처 결과는 감사/복구용으로 JSON 백업 파일에도 저장(backup_path).
  - DROP 은 IF EXISTS, 재생성은 개별 실행하여 일부 실패가 전체를 막지 않게 함.

변경 이력:
2026-08-05 | OMA Team | 초기 생성
  - ForeignKeyManager: capture / drop_all / recreate
  - full-load 전 FK 드랍 → 후 재생성(참조 무결성 위반 로딩 실패 방지)
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 타겟 스키마의 FK 제약을 정의째 조회
#   pg_get_constraintdef(oid) → "FOREIGN KEY (...) REFERENCES ... (...)" 문자열
_FK_LIST_SQL = """
SELECT
    con.conname                    AS constraint_name,
    rel.relname                    AS table_name,
    pg_get_constraintdef(con.oid)  AS definition
FROM pg_constraint con
JOIN pg_class rel      ON rel.oid = con.conrelid
JOIN pg_namespace nsp  ON nsp.oid = rel.relnamespace
WHERE con.contype = 'f'
  AND nsp.nspname = %s
ORDER BY rel.relname, con.conname
"""


class ForeignKeyManagerError(Exception):
    """FK 관리 오류."""


class ForeignKeyManager:
    """
    타겟 스키마 FK 캡처/드랍/재생성기.

    Attributes:
        executor: 'target' endpoint 가 등록된 DBExecutor
        target_schema: 대상(타겟) 스키마명
        backup_path: 캡처 정의를 저장할 JSON 경로(선택)
    """

    _TARGET = "target"

    def __init__(
        self,
        executor: Any,
        target_schema: str,
        backup_path: Optional[str] = None,
    ) -> None:
        """
        Args:
            executor: 'target' endpoint 가 등록된 DBExecutor
            target_schema: 대상 스키마명(PostgreSQL, 소문자)
            backup_path: FK 정의 백업 JSON 파일 경로(선택)
        """
        self.executor = executor
        self.target_schema = target_schema
        self.backup_path = backup_path

    def _quote(self, ident: str) -> str:
        """
        식별자를 큰따옴표로 안전하게 감싼다(내부 " 는 이스케이프).

        Args:
            ident: 식별자(스키마/테이블/제약명)

        Returns:
            큰따옴표로 감싼 식별자
        """
        escaped = ident.replace('"', '""')
        return f'"{escaped}"'

    def capture(self) -> List[Dict[str, str]]:
        """
        타겟 스키마의 모든 FK 를 정의째 조회하고(선택적으로) 백업한다.

        Returns:
            [{"constraint_name", "table_name", "definition"}, ...]

        Raises:
            ForeignKeyManagerError: 조회 실패 시
        """
        try:
            rows = self.executor.query(
                self._TARGET, _FK_LIST_SQL, [self.target_schema]
            )
        except Exception as e:  # noqa: BLE001 - ExecutorError 등 포괄
            raise ForeignKeyManagerError(f"FK 조회 실패: {e}") from e

        fks = [
            {
                "constraint_name": r["constraint_name"],
                "table_name": r["table_name"],
                "definition": r["definition"],
            }
            for r in rows
        ]
        logger.info(
            "타겟 스키마 %s FK 캡처: %d개", self.target_schema, len(fks)
        )
        if self.backup_path and fks:
            self._save_backup(fks)
        return fks

    def _save_backup(self, fks: List[Dict[str, str]]) -> None:
        """
        캡처한 FK 정의를 JSON 파일로 저장한다(감사/복구용).

        Args:
            fks: capture() 결과
        """
        try:
            os.makedirs(os.path.dirname(self.backup_path), exist_ok=True)
            with open(self.backup_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"schema": self.target_schema, "foreign_keys": fks},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            logger.info("FK 정의 백업 저장: %s", self.backup_path)
        except OSError as e:
            # 백업 실패는 치명적이지 않음(정의는 메모리에 있음) → 경고만.
            logger.warning("FK 백업 저장 실패(%s): %s", self.backup_path, e)

    def drop_all(self, fks: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        캡처한 FK 를 모두 DROP 한다(IF EXISTS).

        Args:
            fks: capture() 결과

        Returns:
            {"dropped", "failed", "errors": [{constraint, error}, ...]}

        Raises:
            ForeignKeyManagerError: (개별 실패는 errors 로 수집; 전체 예외 없음)
        """
        dropped = 0
        errors: List[Dict[str, str]] = []
        for fk in fks:
            table = self._quote(self.target_schema) + "." + self._quote(
                fk["table_name"]
            )
            con = self._quote(fk["constraint_name"])
            sql = f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {con}"
            try:
                self.executor.execute(self._TARGET, sql)
                dropped += 1
                logger.info(
                    "  FK DROP: %s.%s",
                    fk["table_name"],
                    fk["constraint_name"],
                )
            except Exception as e:  # noqa: BLE001
                errors.append(
                    {"constraint": fk["constraint_name"], "error": str(e)}
                )
                logger.warning(
                    "  FK DROP 실패: %s (%s)", fk["constraint_name"], e
                )
        logger.info("FK DROP 완료: dropped=%d failed=%d", dropped, len(errors))
        return {"dropped": dropped, "failed": len(errors), "errors": errors}

    def recreate(self, fks: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        백업한 정의로 FK 를 다시 ADD 한다.

        Args:
            fks: capture() 결과(정의 포함)

        Returns:
            {"recreated", "failed", "errors": [{constraint, error}, ...]}
        """
        recreated = 0
        errors: List[Dict[str, str]] = []
        for fk in fks:
            table = self._quote(self.target_schema) + "." + self._quote(
                fk["table_name"]
            )
            con = self._quote(fk["constraint_name"])
            # definition 예: "FOREIGN KEY (col) REFERENCES other(col) ..."
            sql = (
                f"ALTER TABLE {table} "
                f"ADD CONSTRAINT {con} {fk['definition']}"
            )
            try:
                self.executor.execute(self._TARGET, sql)
                recreated += 1
                logger.info(
                    "  FK 재생성: %s.%s",
                    fk["table_name"],
                    fk["constraint_name"],
                )
            except Exception as e:  # noqa: BLE001
                errors.append(
                    {"constraint": fk["constraint_name"], "error": str(e)}
                )
                logger.warning(
                    "  FK 재생성 실패: %s (%s)", fk["constraint_name"], e
                )
        logger.info(
            "FK 재생성 완료: recreated=%d failed=%d", recreated, len(errors)
        )
        return {"recreated": recreated, "failed": len(errors), "errors": errors}

    def load_backup(self) -> List[Dict[str, str]]:
        """
        백업 파일에서 FK 정의를 읽는다(재생성 단독 실행/복구용).

        Returns:
            capture() 형식의 FK 리스트(파일이 없으면 빈 리스트)

        Raises:
            ForeignKeyManagerError: 백업 경로 미설정 또는 파싱 실패 시
        """
        if not self.backup_path:
            raise ForeignKeyManagerError("backup_path 미설정")
        if not os.path.exists(self.backup_path):
            logger.warning("FK 백업 파일 없음: %s", self.backup_path)
            return []
        try:
            with open(self.backup_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("foreign_keys", [])
        except (OSError, json.JSONDecodeError) as e:
            raise ForeignKeyManagerError(f"FK 백업 로드 실패: {e}") from e
