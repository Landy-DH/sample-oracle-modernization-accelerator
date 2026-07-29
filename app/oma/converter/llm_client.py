"""
LLM API 클라이언트 모듈

AWS Bedrock의 Claude 모델을 호출한다 (Anthropic Messages API 포맷).
Rate limit(RPM) 준수, 지수 백오프 재시도, 타임아웃, JSON 응답 파싱을 포함한다.

전역 변수를 쓰지 않으며, bedrock 클라이언트를 주입할 수 있어 테스트가 용이하다.
자격증명/응답 본문은 로그에 남기지 않는다.

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - LLMClient 구현: invoke(텍스트), invoke_json(JSON 파싱)
  - _respect_rate_limit(RPM), calculate_backoff(지수, 상한), 재시도 루프
  - throttling/일시 오류만 재시도, 그 외는 즉시 실패

2026-07-28 | OMA Team | 변환 병렬화 대응: rate limiter thread-safe화
  - 원인: Phase4를 ThreadPoolExecutor로 병렬 실행 시 여러 워커가
    _last_request_time을 락 없이 공유 → RPM 제한이 깨져 throttling 유발.
  - 수정: _rate_lock(threading.Lock)으로 _respect_rate_limit 임계구역 보호.
    lock 안에서 필요한 만큼 sleep해 요청 간 min_interval을 직렬로 강제.

2026-07-28 | OMA Team | invoke_json 제어문자 허용(조각 수정 파싱 실패 대응)
  - 원인: 모델이 XML/CDATA를 fixed_sql 문자열 안에 넣을 때 개행을 이스케이프
    없이 그대로 담아 json.loads가 "Invalid control character" 예외 발생.
  - 수정: json.loads(..., strict=False)로 문자열 내부 제어문자를 허용.
    구조 오류는 여전히 예외 → 실제 손상만 실패로 처리.
"""

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional

from oma.utils.config import Config
from oma.utils.exceptions import LLMError

logger = logging.getLogger(__name__)

# 백오프 상한 (초)
_MAX_BACKOFF_SECONDS = 300
# 기본 출력 토큰 상한 (응답 생성용; 입력+출력 총합 제한과 별개)
_DEFAULT_MAX_OUTPUT_TOKENS = 8192
# 재시도 대상 예외 이름 (Bedrock/네트워크 일시 오류)
_RETRYABLE_ERROR_NAMES = frozenset(
    {
        "ThrottlingException",
        "TooManyRequestsException",
        "ServiceUnavailableException",
        "ModelTimeoutException",
        "InternalServerException",
        "ModelNotReadyException",
        "ReadTimeoutError",
        "ConnectTimeoutError",
    }
)


class LLMClient:
    """
    AWS Bedrock Claude 클라이언트

    Attributes:
        config: Config 객체
        model_id: Bedrock 모델 ID
        rpm_limit: 분당 요청 수 제한
    """

    def __init__(self, config: Config, bedrock_client: Optional[Any] = None) -> None:
        """
        초기화

        Args:
            config: Config 객체
            bedrock_client: 주입할 boto3 bedrock-runtime 클라이언트 (선택, 테스트용)
        """
        self.config = config
        self._client = bedrock_client
        self.model_id = config.get("BEDROCK_MODEL_ID")

        self.rpm_limit = config.get_int("LLM_RPM_LIMIT", 50)
        self.min_interval = 60.0 / self.rpm_limit if self.rpm_limit > 0 else 0.0
        self._last_request_time = 0.0
        # 병렬 변환(ThreadPoolExecutor)에서 RPM 직렬 강제용
        self._rate_lock = threading.Lock()

        self.max_retries = config.get_int("LLM_MAX_RETRIES", 3)
        self.base_delay = config.get_int("LLM_RETRY_BASE_DELAY", 2)
        self.max_output_tokens = config.get_int(
            "LLM_MAX_OUTPUT_TOKENS", _DEFAULT_MAX_OUTPUT_TOKENS
        )

    def _get_client(self) -> Any:
        """
        bedrock-runtime 클라이언트를 지연 생성/반환한다.

        Returns:
            boto3 bedrock-runtime 클라이언트

        Raises:
            LLMError: boto3 임포트/클라이언트 생성 실패 시
        """
        if self._client is not None:
            return self._client

        try:
            import boto3
            from botocore.config import Config as BotoConfig
        except ImportError as e:
            raise LLMError("boto3를 임포트할 수 없습니다", {"error": str(e)}) from e

        region = self.config.get("BEDROCK_REGION") or self.config.get("AWS_REGION")
        # boto3 기본 read_timeout(60s)은 대형 조각 응답에 부족 → LLM_TIMEOUT_SECONDS 반영.
        # 재시도는 우리 로직에서 처리하므로 botocore 자체 재시도는 끈다(중복 방지).
        timeout = self.config.get_int("LLM_TIMEOUT_SECONDS", 120)
        boto_config = BotoConfig(
            read_timeout=timeout,
            connect_timeout=30,
            retries={"max_attempts": 0},
        )
        self._client = boto3.client(
            "bedrock-runtime", region_name=region, config=boto_config
        )
        return self._client

    def invoke(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        프롬프트를 보내고 응답 텍스트를 반환한다 (재시도 포함).

        Args:
            prompt: 사용자 프롬프트
            system: 시스템 프롬프트 (선택)
            max_tokens: 출력 토큰 상한 (선택)

        Returns:
            모델이 생성한 텍스트

        Raises:
            LLMError: 재시도 후에도 실패하거나 응답 파싱 실패 시
        """
        body = self._build_body(prompt, system, max_tokens)
        response_body = self._invoke_with_retry(body)
        return self._extract_text(response_body)

    def invoke_json(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        응답 텍스트를 JSON으로 파싱해 반환한다.

        모델이 코드펜스(```json ... ```)로 감싸도 벗겨내고 파싱한다.

        Args:
            prompt: 사용자 프롬프트
            system: 시스템 프롬프트 (선택)
            max_tokens: 출력 토큰 상한 (선택)

        Returns:
            파싱된 dict

        Raises:
            LLMError: JSON 파싱 실패 시
        """
        text = self.invoke(prompt, system, max_tokens)
        cleaned = self._strip_code_fence(text)
        try:
            # strict=False: 모델이 XML/CDATA를 문자열 값에 넣을 때 이스케이프하지 않은
            # 개행/탭 등 제어문자를 허용한다(구조 오류는 여전히 예외).
            return json.loads(cleaned, strict=False)
        except json.JSONDecodeError as e:
            raise LLMError(
                "LLM 응답을 JSON으로 파싱할 수 없습니다",
                {"error": str(e), "preview": cleaned[:200]},
            ) from e

    def _build_body(
        self, prompt: str, system: Optional[str], max_tokens: Optional[int]
    ) -> Dict[str, Any]:
        """
        Anthropic Messages API 요청 본문을 만든다.

        Args:
            prompt: 사용자 프롬프트
            system: 시스템 프롬프트 (선택)
            max_tokens: 출력 토큰 상한 (선택)

        Returns:
            요청 본문 dict
        """
        body: Dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens or self.max_output_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system
        return body

    def _invoke_with_retry(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """
        rate limit 준수 + 지수 백오프 재시도로 모델을 호출한다.

        Args:
            body: 요청 본문

        Returns:
            파싱된 응답 본문 dict

        Raises:
            LLMError: 최대 재시도 후에도 실패 시
        """
        client = self._get_client()
        payload = json.dumps(body)
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            self._respect_rate_limit()
            try:
                response = client.invoke_model(
                    modelId=self.model_id, body=payload
                )
                raw = response["body"].read()
                return json.loads(raw)
            except Exception as e:
                last_error = e
                if not self._is_retryable(e) or attempt >= self.max_retries:
                    break
                delay = self.calculate_backoff(attempt)
                logger.warning(
                    "LLM 호출 실패 (재시도 %d/%d, %.1fs 후): %s",
                    attempt + 1, self.max_retries, delay, type(e).__name__,
                )
                time.sleep(delay)

        raise LLMError(
            "LLM 호출에 실패했습니다 (재시도 소진)",
            {"attempts": self.max_retries + 1, "error": str(last_error)},
        )

    @staticmethod
    def _is_retryable(error: Exception) -> bool:
        """
        재시도 가능한 오류인지 판단한다 (예외 클래스명 기반).

        Args:
            error: 발생한 예외

        Returns:
            재시도 가능 여부
        """
        name = type(error).__name__
        if name in _RETRYABLE_ERROR_NAMES:
            return True
        # botocore ClientError는 response의 에러 코드로 판별
        response = getattr(error, "response", None)
        if isinstance(response, dict):
            code = response.get("Error", {}).get("Code")
            if code in _RETRYABLE_ERROR_NAMES:
                return True
        return False

    def _respect_rate_limit(self) -> None:
        """
        마지막 요청 이후 min_interval이 지나지 않았으면 대기한다.

        병렬 변환에서 여러 워커가 동시에 호출해도 RPM이 지켜지도록 락으로
        임계구역을 보호한다. 락을 잡은 채 sleep하므로 요청 예약 간격이
        직렬화되고, 워커 수와 무관하게 분당 요청 수가 rpm_limit을 넘지 않는다.
        """
        if self.min_interval <= 0:
            return
        with self._rate_lock:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last_request_time = time.time()

    def calculate_backoff(self, retry_count: int) -> float:
        """
        지수 백오프 대기 시간을 계산한다 (상한 적용).

        Args:
            retry_count: 현재 재시도 인덱스(0부터)

        Returns:
            대기 시간(초)
        """
        delay = self.base_delay * (2 ** retry_count)
        return float(min(delay, _MAX_BACKOFF_SECONDS))

    @staticmethod
    def _extract_text(response_body: Dict[str, Any]) -> str:
        """
        Anthropic Messages 응답 본문에서 텍스트를 추출한다.

        content 블록들 중 type=text의 text를 이어붙인다.

        Args:
            response_body: invoke_model 응답을 파싱한 dict

        Returns:
            텍스트

        Raises:
            LLMError: 예상 구조가 아닐 때
        """
        content = response_body.get("content")
        if not isinstance(content, list):
            raise LLMError(
                "LLM 응답 형식이 올바르지 않습니다",
                {"keys": list(response_body.keys())},
            )
        parts: List[str] = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "".join(parts)

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        """
        마크다운 코드펜스(```json ... ```)를 제거한다 (정규식 미사용).

        Args:
            text: 원본 텍스트

        Returns:
            펜스가 제거된 텍스트
        """
        stripped = text.strip()
        if not stripped.startswith("```"):
            return stripped

        # 첫 줄(``` 또는 ```json)과 마지막 ``` 제거
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
