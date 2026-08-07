"""
Bedrock 호출 클라이언트 (2차 LLM 변환용)

oma.properties 의 Bedrock/LLM 설정을 주입받아 Anthropic Messages API 를
Bedrock invoke_model 로 호출한다. RPM 제한, 타임아웃, 지수 백오프 재시도를
설정 기반으로 처리한다(하드코딩 금지).

설정 키(config.get 로 주입):
  BEDROCK_REGION, BEDROCK_MODEL_ID
  LLM_RPM_LIMIT, LLM_TIMEOUT_SECONDS, LLM_MAX_RETRIES,
  LLM_RETRY_BASE_DELAY, LLM_MAX_OUTPUT_TOKENS

변경 이력:
2026-08-05 | OMA Team | 초기 생성
  - invoke(): RPM 제한 + 지수 백오프 재시도, config 주입식 설정
"""

import json
import logging
import time
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

_ANTHROPIC_VERSION = "bedrock-2023-05-31"


class BedrockError(Exception):
    """Bedrock 호출 오류."""


class BedrockClient:
    """
    Bedrock Anthropic 모델 호출기(RPM 제한·재시도 포함).

    Attributes:
        model_id: Bedrock 모델 ID
        region: Bedrock region
        rpm_limit: 분당 최대 호출 수(0 이하면 제한 없음)
        timeout_seconds: read 타임아웃(초)
        max_retries: 재시도 횟수
        retry_base_delay: 지수 백오프 기본 지연(초)
        max_output_tokens: 응답 최대 토큰
    """

    def __init__(
        self,
        model_id: str,
        region: str,
        rpm_limit: int = 0,
        timeout_seconds: int = 300,
        max_retries: int = 3,
        retry_base_delay: int = 2,
        max_output_tokens: int = 16000,
        client: Optional[Any] = None,
    ) -> None:
        """
        Args:
            model_id: Bedrock 모델 ID(예: global.anthropic.claude-opus-4-8)
            region: Bedrock region
            rpm_limit: 분당 호출 상한(0 이하 = 무제한)
            timeout_seconds: read 타임아웃(초)
            max_retries: 실패 재시도 횟수
            retry_base_delay: 백오프 기본 지연(초)
            max_output_tokens: 응답 최대 토큰
            client: 주입할 bedrock-runtime 클라이언트(선택, 테스트용)
        """
        self.model_id = model_id
        self.region = region
        self.rpm_limit = rpm_limit
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.max_output_tokens = max_output_tokens
        self._client = client
        # RPM 제어용 최근 호출 타임스탬프(monotonic)
        self._call_times: List[float] = []

    @classmethod
    def from_config(cls, config: Any, client: Optional[Any] = None) -> "BedrockClient":
        """
        Config 객체에서 설정을 읽어 클라이언트를 만든다.

        Args:
            config: get/get_int/require 를 제공하는 Config
            client: 주입할 bedrock-runtime 클라이언트(선택)

        Returns:
            BedrockClient 인스턴스
        """
        return cls(
            model_id=config.require("BEDROCK_MODEL_ID"),
            region=config.get("BEDROCK_REGION") or config.require("AWS_REGION"),
            rpm_limit=config.get_int("LLM_RPM_LIMIT", 0),
            timeout_seconds=config.get_int("LLM_TIMEOUT_SECONDS", 300),
            max_retries=config.get_int("LLM_MAX_RETRIES", 3),
            retry_base_delay=config.get_int("LLM_RETRY_BASE_DELAY", 2),
            max_output_tokens=config.get_int("LLM_MAX_OUTPUT_TOKENS", 16000),
            client=client,
        )

    def _bedrock(self) -> Any:
        """bedrock-runtime 클라이언트를 지연 생성/반환한다."""
        if self._client is not None:
            return self._client
        try:
            import boto3
            from botocore.config import Config as BotoConfig
        except ImportError as e:
            raise BedrockError(f"boto3 임포트 실패: {e}") from e
        boto_config = BotoConfig(
            read_timeout=self.timeout_seconds,
            connect_timeout=10,
            retries={"max_attempts": 1},  # 재시도는 이 클래스가 직접 관리
        )
        self._client = boto3.client(
            service_name="bedrock-runtime",
            region_name=self.region,
            config=boto_config,
        )
        return self._client

    def _throttle(self) -> None:
        """RPM 제한을 위해 필요 시 대기한다(monotonic 기준 60초 창)."""
        if self.rpm_limit <= 0:
            return
        now = time.monotonic()
        window_start = now - 60.0
        # 60초 이전 호출 기록 제거
        self._call_times = [t for t in self._call_times if t > window_start]
        if len(self._call_times) >= self.rpm_limit:
            # 가장 오래된 호출이 창을 벗어날 때까지 대기
            sleep_for = 60.0 - (now - self._call_times[0])
            if sleep_for > 0:
                logger.info("RPM 제한 대기: %.1fs", sleep_for)
                time.sleep(sleep_for)
        self._call_times.append(time.monotonic())

    def invoke(self, prompt: str, max_tokens: Optional[int] = None) -> str:
        """
        단일 user 프롬프트로 모델을 호출하고 텍스트 응답을 반환한다.

        Args:
            prompt: user 메시지 내용
            max_tokens: 응답 최대 토큰(미지정 시 max_output_tokens)

        Returns:
            모델 응답 텍스트(공백 트림)

        Raises:
            BedrockError: 모든 재시도 실패 시
        """
        body = json.dumps(
            {
                "anthropic_version": _ANTHROPIC_VERSION,
                "max_tokens": max_tokens or self.max_output_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
        )
        client = self._bedrock()
        last_err: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                resp = client.invoke_model(modelId=self.model_id, body=body)
                payload = json.loads(resp["body"].read())
                return payload["content"][0]["text"].strip()
            except Exception as e:  # noqa: BLE001
                last_err = e
                delay = self.retry_base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "Bedrock 호출 실패(%d/%d): %s → %ds 후 재시도",
                    attempt,
                    self.max_retries,
                    str(e)[:150],
                    delay,
                )
                if attempt < self.max_retries:
                    time.sleep(delay)

        raise BedrockError(f"Bedrock 호출 실패({self.max_retries}회): {last_err}")
