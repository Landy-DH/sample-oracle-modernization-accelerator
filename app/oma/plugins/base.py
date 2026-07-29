"""
DB 플러그인 추상 베이스

소스/타겟 DB 연결을 추상화한다. 이번 단계는 "연결 중심 최소 구현"으로,
연결 수립/해제/커넥션 획득/스키마명/연결 테스트만 정의한다.
스키마 추출·SQL 검증·TC 실행 등은 해당 기능 구현 단계에서 확장한다.

자격증명(credentials)은 생성자로 주입한다 (Secrets Manager 또는 config에서 획득).
전역 변수/하드코딩을 사용하지 않는다 (15-coding-guidelines.md).

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - SourceDB, TargetDB 추상 베이스 (connect/disconnect/get_connection/
    get_schema_name/test_connection). 컨텍스트 매니저 지원
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class BaseDB(ABC):
    """
    소스/타겟 공통 DB 연결 추상 베이스

    Attributes:
        credentials: 접속 정보 dict (host, port, username, password 등)
        connection: 수립된 DB 커넥션 (connect 전에는 None)
    """

    def __init__(self, credentials: Dict[str, Any]) -> None:
        """
        초기화

        Args:
            credentials: 접속 정보 dict (Secrets Manager/Config에서 주입)
        """
        self.credentials = credentials
        self.connection: Optional[Any] = None

    @abstractmethod
    def connect(self) -> Any:
        """
        DB에 연결하고 커넥션을 반환한다 (self.connection에도 저장).

        Returns:
            DB 커넥션 객체

        Raises:
            DatabaseError: 연결 실패 시
        """
        raise NotImplementedError

    @abstractmethod
    def get_schema_name(self) -> str:
        """
        메타데이터 조회 대상 스키마명을 반환한다.

        Returns:
            스키마명
        """
        raise NotImplementedError

    @abstractmethod
    def get_sql_dialect(self) -> str:
        """
        SQL 방언 문자열을 반환한다 (oracle, postgres 등).

        Returns:
            방언 이름
        """
        raise NotImplementedError

    def get_connection(self) -> Any:
        """
        현재 커넥션을 반환한다 (없으면 connect() 수행).

        Returns:
            DB 커넥션 객체
        """
        if self.connection is None:
            self.connect()
        return self.connection

    def disconnect(self) -> None:
        """커넥션을 닫는다 (예외는 무시하고 상태만 정리)."""
        if self.connection is not None:
            try:
                self.connection.close()
            except Exception as e:  # 닫기 실패는 치명적이지 않음
                logger.warning("커넥션 종료 중 경고: %s", e)
            finally:
                self.connection = None

    def test_connection(self) -> bool:
        """
        연결 가능 여부를 테스트한다 (연결 후 즉시 해제).

        Returns:
            성공 여부
        """
        try:
            self.connect()
            return True
        except Exception as e:
            logger.error("연결 테스트 실패: %s", e)
            return False
        finally:
            self.disconnect()

    def __enter__(self) -> "BaseDB":
        """컨텍스트 매니저 진입 → 연결"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """컨텍스트 매니저 종료 → 연결 해제"""
        self.disconnect()


class SourceDB(BaseDB):
    """
    소스 DB(변환 원본: Oracle/EDB/Tibero) 추상 베이스

    관리자 계정으로 접속해 대상 스키마의 메타데이터를 조회한다.
    """


class TargetDB(BaseDB):
    """
    타겟 DB(변환 대상: PostgreSQL/MySQL) 추상 베이스

    서비스 계정으로 접속해 딕셔너리 생성용 스키마 정보를 조회한다.
    """
