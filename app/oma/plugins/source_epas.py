"""
EPAS(EDB Postgres Advanced Server) 소스 DB 플러그인

EPAS에 접속해 변환 원본 스키마 정보를 조회할 수 있게 한다.
EPAS는 Oracle 호환 모드 DB지만 접속은 PostgreSQL 와이어 프로토콜을 쓰므로
드라이버는 psycopg2를 사용한다 (target_postgres.py와 동일한 연결 방식).

Oracle 소스와 달리 service_name→SID 폴백 로직은 불필요하다
(PG 프로토콜은 host/port/dbname/user/password로 단순 접속).

시크릿 키 매핑:
  host, port, database, username, password
  스키마명은 credentials의 target_schema > schema > username 순으로 사용
  (EPAS 스키마명은 소문자 그대로 사용 — Oracle처럼 대문자화하지 않음)

변경 이력:
2026-07-28 | OMA Team | 초기 생성 (design/19-multisource-target-guide.md 조합 B)
  - EpasSource 구현: psycopg2 연결(폴백 없음), 스키마=target_schema|schema|username
  - 참고 템플릿: source_oracle.py(역할) + target_postgres.py(psycopg2 연결)
  - connect_timeout 적용 (기본 10초)
"""

import logging
from typing import Any, Dict

from oma.plugins.base import SourceDB
from oma.utils.exceptions import DatabaseError

logger = logging.getLogger(__name__)

_DIALECT = "epas"
_DEFAULT_CONNECT_TIMEOUT = 10


class EpasSource(SourceDB):
    """
    EPAS 소스 DB 플러그인 (psycopg2)

    EPAS는 PostgreSQL 프로토콜로 접속하므로 Oracle의 service_name/SID 폴백이
    필요 없다. 관리자 계정으로 접속해 대상 스키마의 메타데이터를 조회한다.

    Attributes:
        credentials: host/port/database/username/password 를 포함한 접속 정보
        connect_timeout: 연결 타임아웃(초)
    """

    def __init__(
        self,
        credentials: Dict[str, Any],
        connect_timeout: int = _DEFAULT_CONNECT_TIMEOUT,
    ) -> None:
        """
        초기화

        Args:
            credentials: 접속 정보 dict (Secrets Manager/Config에서 주입)
            connect_timeout: 연결 타임아웃(초)
        """
        super().__init__(credentials)
        self.connect_timeout = connect_timeout

    def connect(self) -> Any:
        """
        EPAS에 연결한다 (psycopg2, PostgreSQL 와이어 프로토콜).

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
        # EPAS는 sid가 아닌 database명으로 접속 (Oracle 소스와의 차이)
        database = self.credentials.get("database") or self.credentials.get("sid")
        try:
            conn = psycopg2.connect(
                host=host,
                port=self.credentials.get("port"),
                dbname=database,
                user=self.credentials.get("username"),
                password=self.credentials.get("password"),
                connect_timeout=self.connect_timeout,
            )
        except Exception as e:
            raise DatabaseError(
                "EPAS 연결에 실패했습니다",
                {"host": host, "error": str(e)},
            ) from e

        logger.info(
            "EPAS 연결 성공 (host=%s, db=%s, schema=%s)",
            host, database, self.get_schema_name(),
        )
        self.connection = conn
        return conn

    def get_schema_name(self) -> str:
        """
        메타데이터 조회 대상 스키마명을 반환한다.

        target_schema > schema > username 순으로 사용한다. EPAS 스키마명은
        PostgreSQL과 동일하게 소문자 그대로 쓰므로 대문자화하지 않는다
        (Oracle 소스와의 차이).

        Returns:
            스키마명
        """
        return (
            self.credentials.get("target_schema")
            or self.credentials.get("schema")
            or self.credentials.get("username")
            or "public"
        )

    def get_sql_dialect(self) -> str:
        """SQL 방언 반환"""
        return _DIALECT
