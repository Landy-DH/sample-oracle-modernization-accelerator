"""
AWS Secrets Manager 조회 모듈 (schema 단계 전용)

DB 자격증명을 시크릿 "이름"으로만 참조하여 조회한다.
자격증명은 절대 코드/설정 파일에 두지 않으며, 시크릿 값은 로그에 남기지 않는다.

app/oma/utils/secrets.py 와 동일한 계약을 따르되, schema 모듈이
독립적으로 동작하도록 자체 구현으로 둔다.

변경 이력:
2026-08-05 | OMA Team | 초기 생성
  - SecretsManager 클래스: get_secret() + 인스턴스 캐싱, boto3 지연 임포트
  - get_secret(secret_name, region) 편의 함수
"""

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class SecretError(Exception):
    """시크릿 조회/파싱 오류."""


class SecretsManager:
    """
    AWS Secrets Manager 조회 및 캐싱 클래스.

    boto3 클라이언트를 주입받을 수 있어 테스트가 용이하다.

    Attributes:
        region: AWS region 이름
    """

    def __init__(self, region: str, boto_client: Optional[Any] = None) -> None:
        """
        Args:
            region: AWS region (예: ap-northeast-2)
            boto_client: 주입할 boto3 secretsmanager 클라이언트(선택, 테스트용)
        """
        self.region = region
        self._client = boto_client
        self._cache: Dict[str, Dict[str, Any]] = {}

    def _get_client(self) -> Any:
        """
        boto3 클라이언트를 지연 생성/반환한다.

        Returns:
            secretsmanager 클라이언트

        Raises:
            SecretError: boto3 임포트/클라이언트 생성 실패 시
        """
        if self._client is not None:
            return self._client
        try:
            import boto3  # 지연 임포트
        except ImportError as e:
            raise SecretError(f"boto3를 임포트할 수 없습니다: {e}") from e
        self._client = boto3.client("secretsmanager", region_name=self.region)
        return self._client

    def get_secret(self, secret_name: str) -> Dict[str, Any]:
        """
        시크릿을 조회해 dict로 반환한다(캐싱 적용).

        Args:
            secret_name: 시크릿 이름

        Returns:
            시크릿 내용(JSON 파싱된 dict)

        Raises:
            SecretError: 조회 실패 또는 JSON 파싱 실패 시
        """
        if secret_name in self._cache:
            logger.debug("시크릿 캐시 히트: %s", secret_name)
            return self._cache[secret_name]

        client = self._get_client()
        logger.info("Secrets Manager 조회: %s", secret_name)
        try:
            response = client.get_secret_value(SecretId=secret_name)
        except Exception as e:  # noqa: BLE001 - 값 노출 방지 위해 메시지만 사용
            raise SecretError(
                f"시크릿 조회 실패: {secret_name} ({e})"
            ) from e

        secret_string = response.get("SecretString")
        if secret_string is None:
            raise SecretError(
                f"SecretString이 비어 있습니다(바이너리 미지원): {secret_name}"
            )
        try:
            secret = json.loads(secret_string)
        except json.JSONDecodeError as e:
            raise SecretError(
                f"시크릿 JSON 파싱 실패: {secret_name} ({e})"
            ) from e

        self._cache[secret_name] = secret
        return secret


def get_secret(secret_name: str, region: str) -> Dict[str, Any]:
    """
    시크릿 조회 편의 함수(일회성).

    Args:
        secret_name: 시크릿 이름
        region: AWS region

    Returns:
        시크릿 내용(dict)

    Raises:
        SecretError: 조회/파싱 실패 시
    """
    return SecretsManager(region=region).get_secret(secret_name)
