"""
PostgreSQL 타겟 DB 플러그인

PostgreSQL(Aurora 포함)에 접속해 딕셔너리 생성용 스키마 정보를 조회할 수 있게 한다.
드라이버는 psycopg2를 사용한다.

시크릿 키 매핑:
  host, port, database, username, password
  스키마명은 credentials의 schema가 있으면 사용, 없으면 username 기준
  (PostgreSQL은 관례상 유저명과 동일한 스키마를 쓰는 경우가 많음)

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - PostgresTarget 구현: psycopg2 연결, 스키마=schema|username
  - connect_timeout 적용 (config의 DB_CONNECT_TIMEOUT, 기본 10초)
"""

import logging
from typing import Any, Dict

from oma.plugins.base import TargetDB
from oma.utils.exceptions import DatabaseError

logger = logging.getLogger(__name__)

_DIALECT = "postgres"
_DEFAULT_CONNECT_TIMEOUT = 10


class PostgresTarget(TargetDB):
    """
    PostgreSQL 타겟 DB 플러그인 (psycopg2)

    Attributes:
        credentials: host/port/database/username/password 를 포함한 접속 정보
    """

    def __init__(
        self, credentials: Dict[str, Any], connect_timeout: int = _DEFAULT_CONNECT_TIMEOUT
    ) -> None:
        """
        초기화

        Args:
            credentials: 접속 정보 dict
            connect_timeout: 연결 타임아웃(초)
        """
        super().__init__(credentials)
        self.connect_timeout = connect_timeout

    def connect(self) -> Any:
        """
        PostgreSQL에 연결한다.

        Returns:
            psycopg2 connection

        Raises:
            DatabaseError: 드라이버 미설치 또는 연결 실패 시
        """
        if self.connection is not None:
            return self.connection

        try:
            import psycopg2
        except ImportError as e:
            raise DatabaseError(
                "psycopg2를 임포트할 수 없습니다",
                {"error": str(e)},
            ) from e

        host = self.credentials.get("host")
        try:
            conn = psycopg2.connect(
                host=host,
                port=self.credentials.get("port"),
                dbname=self.credentials.get("database"),
                user=self.credentials.get("username"),
                password=self.credentials.get("password"),
                connect_timeout=self.connect_timeout,
            )
        except Exception as e:
            raise DatabaseError(
                "PostgreSQL 연결에 실패했습니다",
                {"host": host, "error": str(e)},
            ) from e

        logger.info("PostgreSQL 연결 성공 (host=%s, schema=%s)", host, self.get_schema_name())
        self.connection = conn
        return conn

    def get_schema_name(self) -> str:
        """
        딕셔너리 대상 스키마명을 반환한다.

        credentials의 schema가 있으면 사용, 없으면 username 기준.

        Returns:
            스키마명
        """
        return (
            self.credentials.get("schema")
            or self.credentials.get("username")
            or "public"
        )

    def get_sql_dialect(self) -> str:
        """SQL 방언 반환"""
        return _DIALECT
