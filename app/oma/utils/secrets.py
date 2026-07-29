"""
AWS Secrets Manager 연동 모듈

DB 자격증명 등 시크릿을 AWS Secrets Manager에서 조회한다.
동일 시크릿의 반복 조회를 피하기 위해 인스턴스 단위 캐싱을 제공한다.

보안: 자격증명은 절대 하드코딩하지 않으며, 시크릿 값은 로그에 남기지 않는다.

변경 이력:
2026-07-26 | OMA Team | 초기 생성
  - SecretsManager 클래스 구현: get_secret() + 인스턴스 캐싱
  - 편의 함수 get_secret(secret_name, region) 제공 (구현 가이드 테스트 호환)
  - SecretString은 JSON으로 파싱해 Dict 반환
"""

import json
import logging
from typing import Any, Dict, Optional

from oma.utils.exceptions import DatabaseError

logger = logging.getLogger(__name__)


class SecretsManager:
    """
    AWS Secrets Manager 조회 및 캐싱 클래스

    boto3 클라이언트를 주입받을 수 있어 테스트가 용이하다.
    같은 secret_name을 여러 번 조회하면 캐시에서 반환한다.

    Attributes:
        region: AWS region 이름
    """

    def __init__(
        self, region: str, boto_client: Optional[Any] = None
    ) -> None:
        """
        초기화

        Args:
            region: AWS region (예: ap-northeast-2)
            boto_client: 주입할 boto3 secretsmanager 클라이언트 (선택, 테스트용)
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
            DatabaseError: boto3 임포트/클라이언트 생성 실패 시
        """
        if self._client is not None:
            return self._client

        try:
            import boto3  # 지연 임포트: 테스트 시 boto3 불필요
        except ImportError as e:
            raise DatabaseError(
                "boto3를 임포트할 수 없습니다",
                {"error": str(e)},
            ) from e

        self._client = boto3.client("secretsmanager", region_name=self.region)
        return self._client

    def get_secret(self, secret_name: str) -> Dict[str, Any]:
        """
        시크릿을 조회해 딕셔너리로 반환한다 (캐싱 적용)

        Args:
            secret_name: 시크릿 이름

        Returns:
            시크릿 내용 (JSON 파싱된 dict)

        Raises:
            DatabaseError: 조회 실패 또는 JSON 파싱 실패 시
        """
        if secret_name in self._cache:
            logger.debug("시크릿 캐시 히트: %s", secret_name)
            return self._cache[secret_name]

        client = self._get_client()
        logger.info("Secrets Manager 조회: %s", secret_name)

        try:
            response = client.get_secret_value(SecretId=secret_name)
        except Exception as e:
            # 시크릿 값은 절대 로그에 남기지 않는다
            raise DatabaseError(
                "시크릿 조회에 실패했습니다",
                {"secret_name": secret_name, "error": str(e)},
            ) from e

        secret_string = response.get("SecretString")
        if secret_string is None:
            raise DatabaseError(
                "SecretString이 비어 있습니다 (바이너리 시크릿 미지원)",
                {"secret_name": secret_name},
            )

        try:
            secret = json.loads(secret_string)
        except json.JSONDecodeError as e:
            raise DatabaseError(
                "시크릿을 JSON으로 파싱할 수 없습니다",
                {"secret_name": secret_name, "error": str(e)},
            ) from e

        self._cache[secret_name] = secret
        return secret


def get_secret(secret_name: str, region: str) -> Dict[str, Any]:
    """
    시크릿 조회 편의 함수

    간단한 일회성 조회를 위한 헬퍼. 반복 조회로 캐싱이 필요하면
    SecretsManager 인스턴스를 생성해 재사용할 것.

    Args:
        secret_name: 시크릿 이름
        region: AWS region

    Returns:
        시크릿 내용 (dict)

    Raises:
        DatabaseError: 조회/파싱 실패 시
    """
    manager = SecretsManager(region=region)
    return manager.get_secret(secret_name)
