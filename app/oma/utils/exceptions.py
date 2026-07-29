"""
OMA 예외 클래스 모듈

모든 OMA 커스텀 예외의 정의. OMAError를 베이스로 하며,
각 모듈은 구체적인 하위 예외를 발생시켜야 한다 (광범위한 except 금지).

변경 이력:
2026-07-26 | OMA Team | 초기 생성
  - OMAError (베이스 예외) 구현
  - ConfigError, ConversionError, ValidationError, LLMError, DatabaseError 구현
  - 각 예외에 message + 선택적 context(dict) 지원
"""

from typing import Any, Dict, Optional


class OMAError(Exception):
    """
    모든 OMA 예외의 베이스 클래스

    message 외에 디버깅용 context(dict)를 선택적으로 담을 수 있다.

    Attributes:
        message: 사람이 읽을 수 있는 에러 메시지
        context: 에러 발생 시점의 부가 정보 (예: {'file': 'a.xml', 'sql_id': 'getUser'})
    """

    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        """
        초기화

        Args:
            message: 에러 메시지
            context: 부가 정보 딕셔너리 (선택)
        """
        super().__init__(message)
        self.message = message
        self.context = context or {}

    def __str__(self) -> str:
        """context가 있으면 함께 표시"""
        if self.context:
            return f"{self.message} | context={self.context}"
        return self.message


class ConfigError(OMAError):
    """설정 로드/파싱/조회 실패 (oma.properties 관련)"""


class ConversionError(OMAError):
    """SQL 변환 실패 (LLM 변환, 타입 캐스팅, 병합 등)"""


class ValidationError(OMAError):
    """변환 결과 검증 실패 (소스/타겟 결과 불일치 등)"""


class LLMError(OMAError):
    """LLM API 호출 실패 (Rate limit, timeout, 응답 파싱 실패 등)"""


class DatabaseError(OMAError):
    """데이터베이스 연결/조회/실행 실패"""
