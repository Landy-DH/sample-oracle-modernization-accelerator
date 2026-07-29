"""
LLMClient 단위 테스트 (Bedrock mock, 실제 API 호출 없음)

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - invoke/invoke_json/재시도/백오프/rate limit/응답파싱 테스트
"""

import io
import json

import pytest

from oma.converter.llm_client import LLMClient
from oma.utils.config import Config
from oma.utils.exceptions import LLMError


class _FakeBody:
    """invoke_model 응답의 body(스트림) 흉내"""

    def __init__(self, payload: dict):
        self._data = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._data


class ThrottlingException(Exception):
    """재시도 대상 예외 흉내 (클래스명이 판별에 사용됨 - 실제 Bedrock 예외명과 동일)"""


class _FakeBedrock:
    """invoke_model을 흉내내는 fake 클라이언트"""

    def __init__(self, text="hello", raise_times=0, exc=ThrottlingException):
        self._text = text
        self._raise_times = raise_times
        self._exc = exc
        self.calls = 0

    def invoke_model(self, modelId, body):
        self.calls += 1
        if self.calls <= self._raise_times:
            raise self._exc("temporary")
        payload = {"content": [{"type": "text", "text": self._text}]}
        return {"body": _FakeBody(payload)}


@pytest.fixture
def config(tmp_path):
    prop = tmp_path / "oma.properties"
    # rpm 매우 크게 → min_interval≈0 (테스트 지연 없음), base_delay=0 → 백오프 즉시
    prop.write_text(
        "BEDROCK_MODEL_ID=test-model\nBEDROCK_REGION=ap-northeast-2\n"
        "LLM_RPM_LIMIT=100000\nLLM_MAX_RETRIES=3\nLLM_RETRY_BASE_DELAY=0\n",
        encoding="utf-8",
    )
    return Config(str(prop))


def test_invoke_returns_text(config):
    """정상 응답에서 텍스트 추출"""
    client = LLMClient(config, bedrock_client=_FakeBedrock(text="converted SQL"))
    assert client.invoke("prompt") == "converted SQL"


def test_invoke_sends_model_id(config):
    """요청에 model_id와 messages가 실림"""
    fake = _FakeBedrock()
    client = LLMClient(config, bedrock_client=fake)
    client.invoke("hi", system="you are converter")
    assert fake.calls == 1


def test_invoke_json_parses(config):
    """JSON 응답 파싱"""
    payload = json.dumps({"converted_sql": "SELECT 1", "changes": []})
    client = LLMClient(config, bedrock_client=_FakeBedrock(text=payload))
    result = client.invoke_json("prompt")
    assert result["converted_sql"] == "SELECT 1"


def test_invoke_json_strips_code_fence(config):
    """코드펜스로 감싼 JSON도 파싱"""
    fenced = "```json\n{\"a\": 1}\n```"
    client = LLMClient(config, bedrock_client=_FakeBedrock(text=fenced))
    assert client.invoke_json("p") == {"a": 1}


def test_invoke_json_invalid_raises(config):
    """JSON이 아니면 LLMError"""
    client = LLMClient(config, bedrock_client=_FakeBedrock(text="not json"))
    with pytest.raises(LLMError):
        client.invoke_json("p")


def test_invoke_json_allows_control_chars_in_string(config):
    """문자열 값에 이스케이프 안 된 개행(XML/CDATA)이 있어도 파싱한다(strict=False)."""
    # fixed_sql 안에 실제 개행 문자를 그대로 담은 응답(모델이 흔히 생성)
    raw = '{"fixed_sql": "<select>\n  SELECT 1\n</select>", "changed": true}'
    client = LLMClient(config, bedrock_client=_FakeBedrock(text=raw))
    result = client.invoke_json("p")
    assert "\n" in result["fixed_sql"]
    assert result["changed"] is True


def test_retry_then_success(config):
    """throttling 2회 후 성공 → 총 3콜"""
    fake = _FakeBedrock(text="ok", raise_times=2)
    client = LLMClient(config, bedrock_client=fake)
    assert client.invoke("p") == "ok"
    assert fake.calls == 3


def test_retry_exhausted_raises(config):
    """계속 throttling → 재시도 소진 후 LLMError (max_retries+1 콜)"""
    fake = _FakeBedrock(raise_times=99)
    client = LLMClient(config, bedrock_client=fake)
    with pytest.raises(LLMError):
        client.invoke("p")
    assert fake.calls == 4  # 최초 1 + 재시도 3


def test_non_retryable_fails_fast(config):
    """재시도 대상이 아닌 예외는 즉시 실패 (1콜)"""

    class _ValidationException(Exception):
        pass

    fake = _FakeBedrock(raise_times=99, exc=_ValidationException)
    client = LLMClient(config, bedrock_client=fake)
    with pytest.raises(LLMError):
        client.invoke("p")
    assert fake.calls == 1


def test_calculate_backoff_caps(config):
    """백오프는 지수적으로 증가하고 상한(300)에 걸림"""
    client = LLMClient(config, bedrock_client=_FakeBedrock())
    client.base_delay = 2
    assert client.calculate_backoff(0) == 2
    assert client.calculate_backoff(1) == 4
    assert client.calculate_backoff(2) == 8
    assert client.calculate_backoff(20) == 300  # 상한


def test_bad_response_shape_raises(config):
    """content 구조가 없으면 LLMError"""

    class _BadBedrock:
        def invoke_model(self, modelId, body):
            return {"body": _FakeBody({"unexpected": True})}

    client = LLMClient(config, bedrock_client=_BadBedrock())
    with pytest.raises(LLMError):
        client.invoke("p")


def test_client_error_code_retryable(config):
    """botocore 스타일 ClientError(response.Error.Code)로 재시도 판별"""

    class _ClientError(Exception):
        def __init__(self, *args):
            super().__init__(*args)
            self.response = {"Error": {"Code": "ThrottlingException"}}

    fake = _FakeBedrock(raise_times=1, exc=_ClientError)
    client = LLMClient(config, bedrock_client=fake)
    assert client.invoke("p") is not None
    assert fake.calls == 2
