"""
LLM API 클라이언트 모듈

AWS Bedrock Claude API 호출
Rate limit 준수 (RPM 50), exponential backoff 재시도 포함

변경 이력:
[날짜] [작성자] | 템플릿 생성
  - LLMClient 클래스 스켈레톤
  - call_llm() 메서드 구조
  - Rate limit, 재시도 로직 구조
"""

import time
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class LLMClient:
    """
    AWS Bedrock Claude API 클라이언트

    Rate limit 준수, exponential backoff 재시도 포함
    """

    def __init__(self, config, bedrock_client=None):
        """
        초기화

        Args:
            config: Config 객체
            bedrock_client: boto3 bedrock client (테스트 시 mock 주입 가능)
        """
        self.config = config
        self.bedrock_client = bedrock_client or self._create_client()

        # Rate limit 설정
        self.rpm_limit = config.get_int('LLM_RPM_LIMIT', 50)
        self.last_request_time = 0
        self.min_interval = 60.0 / self.rpm_limit

        # 재시도 설정
        self.max_retries = config.get_int('LLM_MAX_RETRIES', 3)
        self.base_delay = config.get_int('LLM_RETRY_BASE_DELAY', 2)
        self.timeout = config.get_int('LLM_TIMEOUT_SECONDS', 120)

    def _create_client(self):
        """
        Bedrock client 생성

        TODO:
        1. boto3.client('bedrock-runtime', region_name=...)
        2. 반환
        """
        # TODO: 구현
        pass

    def call_llm(self, prompt: str, retry_count: int = 0) -> Dict[str, Any]:
        """
        LLM API 호출

        Rate limit 준수, 재시도 로직 포함

        Args:
            prompt: 변환 프롬프트
            retry_count: 현재 재시도 횟수 (내부용)

        Returns:
            Dict: LLM 응답 (converted_sql, type_casts, changes 등)

        Raises:
            ConversionError: 재시도 3회 후에도 실패 시

        TODO:
        1. _respect_rate_limit() 호출
        2. bedrock_client.invoke_model() 호출
        3. 응답 파싱 (JSON)
        4. RateLimitError 발생 시 → 백오프 후 재시도
        5. TimeoutError 발생 시 → retry_count < max_retries면 재시도
        6. 기타 에러 → 즉시 실패
        """
        # TODO: 구현
        pass

    def _respect_rate_limit(self):
        """
        Rate limit 준수

        마지막 요청 이후 min_interval 지나지 않았으면 대기

        TODO:
        1. elapsed = time.time() - self.last_request_time
        2. if elapsed < self.min_interval: sleep(min_interval - elapsed)
        3. self.last_request_time = time.time()
        """
        # TODO: 구현
        pass

    def calculate_backoff(self, retry_count: int) -> float:
        """
        Exponential backoff 계산

        Args:
            retry_count: 재시도 횟수

        Returns:
            대기 시간 (초)

        TODO:
        1. base_delay * (2 ** retry_count)
        2. 최대 300초 (5분)로 제한
        """
        # TODO: 구현
        pass
