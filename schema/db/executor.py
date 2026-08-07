"""
DB 쿼리 실행 모듈 (schema 단계 전용)

"접속 전용 모듈에 원하는 쿼리를 주면 실행" 하는 공통 인터페이스.
소스(Oracle)든 타겟(PostgreSQL)이든 동일한 방식으로 쿼리를 실행한다.

동작:
  - 시크릿 이름 → SecretsManager로 자격증명 조회
  - db_type에 맞는 커넥션 생성(connection.connect)
  - 커넥션은 요청 시 생성하여 캐싱(같은 secret_name 재사용)
  - query()      : SELECT → 행 리스트(dict) 반환
  - execute()    : DML/DDL → 영향 행 수 반환(자동 commit)
  - executescript(): 여러 문장을 순차 실행

파라미터 바인딩을 지원하여 SQL 문자열 조작(정규식/치환)을 피한다.

변경 이력:
2026-08-05 | OMA Team | 초기 생성
  - DBExecutor: query/execute/executescript, 커넥션 캐싱, close()
  - QueryResult(name tuple 유사) dict 반환
2026-08-05 | OMA Team | psycopg2 '%' 리터럴 오해석 + 트랜잭션 오염 수정
  - query/execute: params 가 없으면 vars 인자를 넘기지 않음
    (원인: psycopg2 는 vars 가 주어지면 SQL 내 리터럴 '%' 를 파라미터
     자리로 해석 → "list index out of range")
  - query: 실패 시 conn.rollback() 추가
    (원인: 실패 문장이 트랜잭션을 abort 상태로 남겨 후속 쿼리까지
     "current transaction is aborted" 로 연쇄 실패)
"""

import logging
from typing import Any, Dict, List, Optional, Sequence

from db import connection as conn_mod
from db.secrets import SecretsManager

logger = logging.getLogger(__name__)

# 쿼리 결과 행 타입 별칭
QueryResult = Dict[str, Any]


class ExecutorError(Exception):
    """쿼리 실행 오류."""


class DBExecutor:
    """
    시크릿 기반 DB 쿼리 실행기.

    소스/타겟 각각에 대해 (db_type, secret_name)을 등록하고,
    endpoint 키('source'/'target' 등 임의 라벨)로 쿼리를 실행한다.

    Attributes:
        region: AWS region
    """

    def __init__(
        self,
        region: str,
        secrets_manager: Optional[SecretsManager] = None,
    ) -> None:
        """
        Args:
            region: AWS region
            secrets_manager: 주입할 SecretsManager(선택, 테스트용)
        """
        self.region = region
        self._secrets = secrets_manager or SecretsManager(region=region)
        # endpoint 라벨 → {"db_type":.., "secret_name":..}
        self._endpoints: Dict[str, Dict[str, str]] = {}
        # endpoint 라벨 → 커넥션(지연 생성/캐싱)
        self._connections: Dict[str, Any] = {}

    def register(self, label: str, db_type: str, secret_name: str) -> None:
        """
        endpoint를 등록한다.

        Args:
            label: 논리 이름(예: 'source', 'target')
            db_type: 'oracle' | 'postgres'
            secret_name: 자격증명 시크릿 이름
        """
        self._endpoints[label] = {
            "db_type": db_type,
            "secret_name": secret_name,
        }
        logger.info(
            "endpoint 등록: %s (db_type=%s, secret=%s)",
            label,
            db_type,
            secret_name,
        )

    def _get_connection(self, label: str) -> Any:
        """
        endpoint 커넥션을 지연 생성/반환한다.

        Args:
            label: endpoint 라벨

        Returns:
            DB-API 커넥션

        Raises:
            ExecutorError: 미등록 라벨이거나 접속 실패 시
        """
        if label in self._connections:
            return self._connections[label]
        if label not in self._endpoints:
            raise ExecutorError(f"등록되지 않은 endpoint: {label}")

        ep = self._endpoints[label]
        try:
            secret = self._secrets.get_secret(ep["secret_name"])
            conn = conn_mod.connect(ep["db_type"], secret)
        except Exception as e:  # noqa: BLE001
            raise ExecutorError(f"endpoint '{label}' 접속 실패: {e}") from e

        self._connections[label] = conn
        return conn

    def query(
        self,
        label: str,
        sql: str,
        params: Optional[Sequence[Any]] = None,
    ) -> List[QueryResult]:
        """
        SELECT 쿼리를 실행하고 행을 dict 리스트로 반환한다.

        Args:
            label: endpoint 라벨
            sql: SELECT 문(파라미터는 바인딩 사용)
            params: 바인딩 파라미터(선택)

        Returns:
            [{컬럼명: 값, ...}, ...]

        Raises:
            ExecutorError: 실행 실패 시
        """
        conn = self._get_connection(label)
        cur = conn.cursor()
        try:
            # params 가 없으면 vars 인자를 아예 넘기지 않는다.
            # (psycopg2 는 vars 가 주어지면 SQL 내 리터럴 '%' 를 파라미터
            #  자리표시자로 해석해 "list index out of range" 를 유발한다.)
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchall()
            return [dict(zip(columns, row)) for row in rows]
        except Exception as e:  # noqa: BLE001
            # 실패한 문장이 트랜잭션을 abort 상태로 남겨 같은 커넥션의
            # 후속 쿼리까지 오염("current transaction is aborted")시키므로
            # 반드시 롤백한다.
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                logger.warning("rollback 실패(%s)", label)
            raise ExecutorError(f"query 실패({label}): {e}") from e
        finally:
            cur.close()

    def execute(
        self,
        label: str,
        sql: str,
        params: Optional[Sequence[Any]] = None,
        commit: bool = True,
    ) -> int:
        """
        DML/DDL을 실행한다.

        Args:
            label: endpoint 라벨
            sql: 실행 문
            params: 바인딩 파라미터(선택)
            commit: 실행 후 커밋 여부

        Returns:
            영향 행 수(rowcount, 알 수 없으면 -1)

        Raises:
            ExecutorError: 실행 실패 시(롤백 시도)
        """
        conn = self._get_connection(label)
        cur = conn.cursor()
        try:
            # params 가 없으면 vars 인자를 넘기지 않는다(리터럴 '%' 오해석 방지).
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            rowcount = cur.rowcount
            if commit:
                conn.commit()
            return rowcount
        except Exception as e:  # noqa: BLE001
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                logger.warning("rollback 실패(%s)", label)
            raise ExecutorError(f"execute 실패({label}): {e}") from e
        finally:
            cur.close()

    def executescript(
        self,
        label: str,
        statements: Sequence[str],
        commit: bool = True,
    ) -> int:
        """
        여러 문장을 순차 실행한다.

        Args:
            label: endpoint 라벨
            statements: 실행할 문장 리스트
            commit: 전체 실행 후 커밋 여부

        Returns:
            실행 성공한 문장 수

        Raises:
            ExecutorError: 실행 실패 시(롤백 시도)
        """
        conn = self._get_connection(label)
        cur = conn.cursor()
        count = 0
        try:
            for stmt in statements:
                if not stmt or not stmt.strip():
                    continue
                cur.execute(stmt)
                count += 1
            if commit:
                conn.commit()
            return count
        except Exception as e:  # noqa: BLE001
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                logger.warning("rollback 실패(%s)", label)
            raise ExecutorError(
                f"executescript 실패({label}, {count}번째까지 성공): {e}"
            ) from e
        finally:
            cur.close()

    def close(self, label: Optional[str] = None) -> None:
        """
        커넥션을 닫는다.

        Args:
            label: 특정 endpoint만 닫으려면 지정. None이면 전체.
        """
        labels = [label] if label else list(self._connections.keys())
        for lb in labels:
            conn = self._connections.pop(lb, None)
            if conn is not None:
                try:
                    conn.close()
                    logger.info("커넥션 종료: %s", lb)
                except Exception:  # noqa: BLE001
                    logger.warning("커넥션 종료 실패: %s", lb)

    def __enter__(self) -> "DBExecutor":
        """컨텍스트 매니저 진입."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """컨텍스트 매니저 종료 시 전체 커넥션 정리."""
        self.close()
