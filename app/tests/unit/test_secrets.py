"""
SecretsManager / get_secret 단위 테스트 (mock 사용)

변경 이력:
2026-07-26 | OMA Team | 초기 생성
  - get_secret 편의 함수 및 SecretsManager 캐싱/에러 처리 테스트
"""

import json
from unittest.mock import Mock, patch

import pytest

from oma.utils.exceptions import DatabaseError
from oma.utils.secrets import SecretsManager, get_secret


@patch("boto3.client")
def test_get_secret(mock_boto_client) -> None:
    """편의 함수 get_secret: SecretString(JSON)을 dict로 반환"""
    mock_client = Mock()
    mock_client.get_secret_value.return_value = {
        "SecretString": '{"host": "localhost", "port": 5432}'
    }
    mock_boto_client.return_value = mock_client

    secret = get_secret("test-secret", "us-east-1")

    assert secret["host"] == "localhost"
    assert secret["port"] == 5432


def test_injected_client_used() -> None:
    """주입된 클라이언트를 사용하고 boto3 없이 동작"""
    mock_client = Mock()
    mock_client.get_secret_value.return_value = {
        "SecretString": json.dumps({"user": "svc"})
    }
    mgr = SecretsManager(region="ap-northeast-2", boto_client=mock_client)

    assert mgr.get_secret("s1")["user"] == "svc"


def test_caching_avoids_second_call() -> None:
    """같은 시크릿 재조회 시 캐시에서 반환 (API 1회만 호출)"""
    mock_client = Mock()
    mock_client.get_secret_value.return_value = {
        "SecretString": json.dumps({"k": "v"})
    }
    mgr = SecretsManager(region="ap-northeast-2", boto_client=mock_client)

    mgr.get_secret("dup")
    mgr.get_secret("dup")

    assert mock_client.get_secret_value.call_count == 1


def test_missing_secret_string_raises() -> None:
    """SecretString이 없으면 DatabaseError"""
    mock_client = Mock()
    mock_client.get_secret_value.return_value = {"SecretBinary": b"x"}
    mgr = SecretsManager(region="ap-northeast-2", boto_client=mock_client)

    with pytest.raises(DatabaseError):
        mgr.get_secret("bin-secret")


def test_invalid_json_raises() -> None:
    """SecretString이 JSON이 아니면 DatabaseError"""
    mock_client = Mock()
    mock_client.get_secret_value.return_value = {"SecretString": "not-json"}
    mgr = SecretsManager(region="ap-northeast-2", boto_client=mock_client)

    with pytest.raises(DatabaseError):
        mgr.get_secret("bad-json")


def test_client_error_wrapped() -> None:
    """조회 예외는 DatabaseError로 래핑"""
    mock_client = Mock()
    mock_client.get_secret_value.side_effect = RuntimeError("access denied")
    mgr = SecretsManager(region="ap-northeast-2", boto_client=mock_client)

    with pytest.raises(DatabaseError):
        mgr.get_secret("no-access")
