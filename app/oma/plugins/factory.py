"""
DB 플러그인 팩토리

config의 SOURCE_DB_TYPE / TARGET_DB_TYPE 값에 따라 알맞은 플러그인을 생성하고,
자격증명을 Secrets Manager(USE_SECRETS_MANAGER=true) 또는 config에서 획득해 주입한다.

지원 현황:
  source: oracle (edb/tibero는 미구현 → 명확한 에러)
  target: postgres (mysql은 미구현 → 명확한 에러)

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - create_source / create_target 구현
  - 자격증명 획득: 시크릿 우선, 미사용 시 config의 SOURCE_*/TARGET_* 사용
  - SecretsManager 주입 가능 (테스트 용이)
"""

import logging
from typing import Any, Dict, Optional

from oma.plugins.base import SourceDB, TargetDB
from oma.plugins.source_epas import EpasSource
from oma.plugins.source_oracle import OracleSource
from oma.plugins.target_postgres import PostgresTarget
from oma.utils.config import Config
from oma.utils.exceptions import ConfigError
from oma.utils.secrets import SecretsManager

logger = logging.getLogger(__name__)

# DB 타입 → 플러그인 클래스
_SOURCE_PLUGINS = {
    "oracle": OracleSource,
    "epas": EpasSource,
}
_TARGET_PLUGINS = {
    "postgres": PostgresTarget,
}


def _resolve_credentials(
    config: Config,
    secret_name_key: str,
    local_keys: Dict[str, str],
    secrets_manager: Optional[SecretsManager],
) -> Dict[str, Any]:
    """
    자격증명을 획득한다 (시크릿 우선, 아니면 config 로컬 값).

    Args:
        config: Config 객체
        secret_name_key: 시크릿 이름이 담긴 config 키 (예: TARGET_SECRET_NAME)
        local_keys: 시크릿 미사용 시 매핑할 {표준키: config키} 딕셔너리
        secrets_manager: 주입된 SecretsManager (없으면 생성)

    Returns:
        표준 키(host/port/...)로 정규화된 자격증명 dict

    Raises:
        ConfigError: 시크릿 이름이 없을 때
    """
    if config.get_bool("USE_SECRETS_MANAGER", False):
        secret_name = config.get(secret_name_key)
        if not secret_name:
            raise ConfigError(
                "시크릿 이름이 설정되지 않았습니다", {"key": secret_name_key}
            )
        manager = secrets_manager or SecretsManager(region=config.get("AWS_REGION"))
        return manager.get_secret(secret_name)

    # 로컬 config 기반 (개발용)
    return {std: config.get(cfg_key) for std, cfg_key in local_keys.items()}


def create_source(
    config: Config, secrets_manager: Optional[SecretsManager] = None
) -> SourceDB:
    """
    SOURCE_DB_TYPE에 맞는 소스 플러그인을 생성한다.

    Args:
        config: Config 객체
        secrets_manager: 주입할 SecretsManager (선택)

    Returns:
        SourceDB 구현체

    Raises:
        ConfigError: 지원하지 않는 DB 타입일 때
    """
    db_type = str(config.get("SOURCE_DB_TYPE", "")).lower()
    plugin_cls = _SOURCE_PLUGINS.get(db_type)
    if plugin_cls is None:
        raise ConfigError(
            "지원하지 않는 SOURCE_DB_TYPE 입니다",
            {"db_type": db_type, "supported": list(_SOURCE_PLUGINS)},
        )

    # 소스 DB 접속 식별자 키: Oracle은 sid(service_name), EPAS는 database.
    # (시크릿 경로는 EpasSource.connect가 database→sid 폴백으로 흡수하므로 영향 없음)
    identifier_key = "database" if db_type == "epas" else "sid"
    credentials = _resolve_credentials(
        config,
        "SOURCE_SECRET_NAME",
        {
            "host": "SOURCE_HOST",
            "port": "SOURCE_PORT",
            identifier_key: "SOURCE_DATABASE",
            "username": "SOURCE_ADMIN_USER",
            "password": "SOURCE_ADMIN_PASSWORD",
            "target_schema": "SOURCE_TARGET_SCHEMA",
        },
        secrets_manager,
    )
    logger.info("소스 플러그인 생성: %s", db_type)
    return plugin_cls(credentials)


def create_target(
    config: Config, secrets_manager: Optional[SecretsManager] = None
) -> TargetDB:
    """
    TARGET_DB_TYPE에 맞는 타겟 플러그인을 생성한다.

    Args:
        config: Config 객체
        secrets_manager: 주입할 SecretsManager (선택)

    Returns:
        TargetDB 구현체

    Raises:
        ConfigError: 지원하지 않는 DB 타입일 때
    """
    db_type = str(config.get("TARGET_DB_TYPE", "")).lower()
    plugin_cls = _TARGET_PLUGINS.get(db_type)
    if plugin_cls is None:
        raise ConfigError(
            "지원하지 않는 TARGET_DB_TYPE 입니다",
            {"db_type": db_type, "supported": list(_TARGET_PLUGINS)},
        )

    credentials = _resolve_credentials(
        config,
        "TARGET_SECRET_NAME",
        {
            "host": "TARGET_HOST",
            "port": "TARGET_PORT",
            "database": "TARGET_DATABASE",
            "schema": "TARGET_SCHEMA",
            "username": "TARGET_USER",
            "password": "TARGET_PASSWORD",
        },
        secrets_manager,
    )
    logger.info("타겟 플러그인 생성: %s", db_type)
    return plugin_cls(credentials)
