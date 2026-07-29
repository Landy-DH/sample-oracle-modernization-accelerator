"""
로깅 설정 모듈

콘솔 및 (선택적) 파일 핸들러를 갖춘 로거를 구성한다.
로그 레벨과 파일 경로는 Config에서 읽으며, 없으면 기본값을 사용한다.

사용하는 설정 키:
  LOG_LEVEL  : 로그 레벨 (DEBUG/INFO/WARNING/ERROR/CRITICAL, 기본 INFO)
  LOG_FILE   : 로그 파일 경로 (미설정 시 파일 핸들러 비활성화)
  LOG_FORMAT : 로그 포맷 문자열 (기본 _DEFAULT_FORMAT)

변경 이력:
2026-07-26 | OMA Team | 초기 생성
  - setup_logger(name, config) 구현: 콘솔 + 파일 핸들러
  - 핸들러 중복 등록 방지 (동일 로거 재설정 안전)
  - config 미주입 시 기본값으로 동작
"""

import logging
import os
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from oma.utils.config import Config

# 기본 로그 포맷 및 레벨
_DEFAULT_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DEFAULT_LEVEL = "INFO"
# 유효한 로그 레벨 이름 집합
_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def setup_logger(
    name: str, config: Optional["Config"] = None
) -> logging.Logger:
    """
    이름 있는 로거를 구성해 반환한다.

    콘솔 핸들러는 항상 추가하고, config에 LOG_FILE이 있으면 파일 핸들러도 추가한다.
    동일 로거에 대해 여러 번 호출해도 핸들러가 중복되지 않는다.

    Args:
        name: 로거 이름 (보통 __name__)
        config: 설정 객체 (선택). 없으면 기본값 사용

    Returns:
        구성된 logging.Logger
    """
    logger = logging.getLogger(name)

    level_name = _DEFAULT_LEVEL
    log_format = _DEFAULT_FORMAT
    log_file: Optional[str] = None

    if config is not None:
        level_name = str(config.get("LOG_LEVEL", _DEFAULT_LEVEL)).upper()
        log_format = str(config.get("LOG_FORMAT", _DEFAULT_FORMAT))
        log_file = config.get("LOG_FILE", None)

    if level_name not in _VALID_LEVELS:
        level_name = _DEFAULT_LEVEL

    level = getattr(logging, level_name)
    logger.setLevel(level)

    # 상위 로거로의 전파를 막아 중복 출력 방지
    logger.propagate = False

    formatter = logging.Formatter(log_format)

    if not _has_handler(logger, logging.StreamHandler):
        console = logging.StreamHandler()
        console.setLevel(level)
        console.setFormatter(formatter)
        logger.addHandler(console)

    if log_file:
        _add_file_handler(logger, log_file, level, formatter)

    return logger


def _has_handler(logger: logging.Logger, handler_type: type) -> bool:
    """
    로거에 특정 타입의 핸들러가 이미 있는지 확인한다.

    FileHandler는 StreamHandler의 하위 클래스이므로 정확한 타입 일치로 검사한다.

    Args:
        logger: 대상 로거
        handler_type: 확인할 핸들러 클래스

    Returns:
        존재 여부
    """
    return any(type(h) is handler_type for h in logger.handlers)


def _add_file_handler(
    logger: logging.Logger,
    log_file: str,
    level: int,
    formatter: logging.Formatter,
) -> None:
    """
    파일 핸들러를 추가한다 (이미 있으면 건너뜀, 디렉토리 자동 생성).

    Args:
        logger: 대상 로거
        log_file: 로그 파일 경로
        level: 로그 레벨
        formatter: 포맷터
    """
    if _has_handler(logger, logging.FileHandler):
        return

    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
