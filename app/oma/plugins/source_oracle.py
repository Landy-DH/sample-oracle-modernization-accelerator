"""
Oracle 소스 DB 플러그인

Oracle에 접속해 변환 원본 스키마의 메타데이터를 조회할 수 있게 한다.
드라이버는 python-oracledb(thin 모드)를 사용한다 — Instant Client 불필요.

접속 방식 (검증 결과 반영):
  Oracle 소스가 PDB(멀티테넌트)인 경우 SID로는 접속되지 않고 service_name만
  동작한다. 반대로 비-CDB는 둘 다 가능하다. 따라서 service_name을 먼저 시도하고
  실패하면 SID로 폴백한다 (PDB 여부를 사전에 판별할 필요 없음).

시크릿 키 매핑:
  host, port, username, password, sid
  (sid 값이 실제로는 service_name일 수 있어 위 폴백 로직으로 흡수)

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - OracleSource 구현: oracledb thin, service_name→SID 폴백
  - 스키마명은 username(대문자) 기준 (Oracle 스키마=유저)
"""

import logging
from typing import Any, Dict, List

from oma.plugins.base import SourceDB
from oma.utils.exceptions import DatabaseError

logger = logging.getLogger(__name__)

_DIALECT = "oracle"
# service_name → sid 순으로 접속 시도
_CONNECT_MODES = ("service_name", "sid")


class OracleSource(SourceDB):
    """
    Oracle 소스 DB 플러그인 (oracledb thin)

    Attributes:
        credentials: host/port/username/password/sid 를 포함한 접속 정보
    """

    def connect(self) -> Any:
        """
        Oracle에 연결한다. service_name 우선, 실패 시 SID로 폴백.

        Returns:
            oracledb Connection

        Raises:
            DatabaseError: 드라이버 미설치 또는 모든 방식 실패 시
        """
        if self.connection is not None:
            return self.connection

        try:
            import oracledb
        except ImportError as e:
            raise DatabaseError(
                "oracledb 드라이버를 임포트할 수 없습니다",
                {"error": str(e)},
            ) from e

        host = self.credentials.get("host")
        port = self.credentials.get("port")
        user = self.credentials.get("username")
        password = self.credentials.get("password")
        # 시크릿의 sid 키는 SID 또는 service_name 어느 쪽이든 될 수 있음
        db_identifier = self.credentials.get("sid") or self.credentials.get(
            "service_name"
        )

        errors: List[str] = []
        for mode in _CONNECT_MODES:
            try:
                dsn = oracledb.makedsn(host, port, **{mode: db_identifier})
                conn = oracledb.connect(user=user, password=password, dsn=dsn)
                logger.info(
                    "Oracle 연결 성공 (mode=%s, host=%s, id=%s)",
                    mode, host, db_identifier,
                )
                self.connection = conn
                return conn
            except Exception as e:
                # 첫 줄만 기록 (스택/민감정보 방지)
                first_line = str(e).splitlines()[0] if str(e) else repr(e)
                errors.append(f"{mode}: {first_line}")
                logger.debug("Oracle 연결 실패 (mode=%s): %s", mode, first_line)

        raise DatabaseError(
            "Oracle 연결에 실패했습니다 (service_name/SID 모두)",
            {"host": host, "port": port, "attempts": errors},
        )

    def get_schema_name(self) -> str:
        """
        메타데이터 조회 대상 스키마명을 반환한다.

        Oracle은 스키마=유저이므로 대상 스키마(credentials의 target_schema)가
        있으면 그것을, 없으면 접속 유저명을 대문자로 반환한다.

        Returns:
            스키마명 (대문자)
        """
        schema = (
            self.credentials.get("target_schema")
            or self.credentials.get("schema")
            or self.credentials.get("username")
            or ""
        )
        return schema.upper()

    def get_sql_dialect(self) -> str:
        """SQL 방언 반환"""
        return _DIALECT
