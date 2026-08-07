"""
DB 커넥션 생성 모듈 (schema 단계 전용)

시크릿 dict를 입력받아 DB 타입에 맞는 드라이버로 커넥션을 생성한다.
  - oracle   : oracledb (thin mode, sqlplus 미사용)
  - postgres : psycopg2

자격증명은 시크릿에서만 오며, 이 모듈은 접속 "방법"만 안다(무상태).

시크릿 필드 계약:
  - oracle  : host, port, sid, username, password
  - postgres: host, port, database, username, password

변경 이력:
2026-08-05 | OMA Team | 초기 생성
  - connect(db_type, secret) : oracle/postgres 커넥션 생성
  - oracledb thin mode (service_name=SID) 사용
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# 지원 DB 타입
ORACLE = "oracle"
POSTGRES = "postgres"
_SUPPORTED = (ORACLE, POSTGRES)


class ConnectionError_(Exception):
    """커넥션 생성 오류(빌트인 ConnectionError와 구분)."""


def _require_fields(secret: Dict[str, Any], fields: tuple) -> None:
    """
    시크릿에 필수 필드가 있는지 검증한다.

    Args:
        secret: 시크릿 dict
        fields: 필수 필드 튜플

    Raises:
        ConnectionError_: 누락 필드가 있을 때(값은 노출하지 않음)
    """
    missing = [f for f in fields if not secret.get(f)]
    if missing:
        raise ConnectionError_(f"시크릿 필수 필드 누락: {missing}")


def _connect_oracle(secret: Dict[str, Any]) -> Any:
    """
    Oracle 커넥션을 생성한다(oracledb thin mode).

    Args:
        secret: host, port, sid, username, password

    Returns:
        oracledb Connection

    Raises:
        ConnectionError_: 드라이버 임포트/접속 실패 시
    """
    _require_fields(secret, ("host", "port", "sid", "username", "password"))
    try:
        import oracledb
    except ImportError as e:
        raise ConnectionError_(f"oracledb 임포트 실패: {e}") from e

    dsn = oracledb.makedsn(
        secret["host"], int(secret["port"]), service_name=secret["sid"]
    )
    logger.info(
        "Oracle 접속: %s@%s:%s/%s",
        secret["username"],
        secret["host"],
        secret["port"],
        secret["sid"],
    )
    try:
        return oracledb.connect(
            user=secret["username"], password=secret["password"], dsn=dsn
        )
    except Exception as e:  # noqa: BLE001 - 값 노출 방지 위해 메시지만 사용
        raise ConnectionError_(f"Oracle 접속 실패: {e}") from e


def _connect_postgres(secret: Dict[str, Any]) -> Any:
    """
    PostgreSQL 커넥션을 생성한다(psycopg2).

    Args:
        secret: host, port, database, username, password

    Returns:
        psycopg2 connection

    Raises:
        ConnectionError_: 드라이버 임포트/접속 실패 시
    """
    _require_fields(
        secret, ("host", "port", "database", "username", "password")
    )
    try:
        import psycopg2
    except ImportError as e:
        raise ConnectionError_(f"psycopg2 임포트 실패: {e}") from e

    logger.info(
        "PostgreSQL 접속: %s@%s:%s/%s",
        secret["username"],
        secret["host"],
        secret["port"],
        secret["database"],
    )
    try:
        return psycopg2.connect(
            host=secret["host"],
            port=int(secret["port"]),
            dbname=secret["database"],
            user=secret["username"],
            password=secret["password"],
        )
    except Exception as e:  # noqa: BLE001 - 값 노출 방지 위해 메시지만 사용
        raise ConnectionError_(f"PostgreSQL 접속 실패: {e}") from e


def connect(db_type: str, secret: Dict[str, Any]) -> Any:
    """
    DB 타입에 맞는 커넥션을 생성한다.

    Args:
        db_type: 'oracle' 또는 'postgres'
        secret: 자격증명 dict(시크릿에서 조회)

    Returns:
        DB-API 2.0 커넥션 객체

    Raises:
        ConnectionError_: 미지원 타입 또는 접속 실패 시
    """
    db_type = (db_type or "").strip().lower()
    if db_type == ORACLE:
        return _connect_oracle(secret)
    if db_type == POSTGRES:
        return _connect_postgres(secret)
    raise ConnectionError_(
        f"지원하지 않는 db_type: {db_type} (지원: {_SUPPORTED})"
    )
