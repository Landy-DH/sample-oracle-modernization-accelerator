"""
setup_logger 단위 테스트

변경 이력:
2026-07-26 | OMA Team | 초기 생성
  - 콘솔/파일 핸들러 구성 및 중복 방지, 파일 출력 테스트
"""

import logging

from oma.utils.config import Config
from oma.utils.logger import setup_logger


def test_console_handler_default() -> None:
    """config 없이 콘솔 핸들러가 구성됨"""
    logger = setup_logger("oma.test.console_default")
    assert logger.level == logging.INFO
    assert any(type(h) is logging.StreamHandler for h in logger.handlers)


def test_no_duplicate_handlers() -> None:
    """반복 호출해도 핸들러가 중복되지 않음"""
    logger = setup_logger("oma.test.dup")
    count = len(logger.handlers)
    setup_logger("oma.test.dup")
    assert len(logger.handlers) == count


def test_file_handler_and_level(tmp_path) -> None:
    """LOG_FILE 설정 시 파일 핸들러 추가 및 실제 기록"""
    prop = tmp_path / "log.properties"
    log_path = tmp_path / "logs" / "oma.log"
    prop.write_text(
        f"LOG_LEVEL=DEBUG\nLOG_FILE={log_path}\n", encoding="utf-8"
    )
    cfg = Config(str(prop))

    logger = setup_logger("oma.test.file", cfg)
    assert logger.level == logging.DEBUG
    assert any(type(h) is logging.FileHandler for h in logger.handlers)

    logger.info("hello-oma")
    for h in logger.handlers:
        h.flush()

    assert log_path.exists()
    assert "hello-oma" in log_path.read_text(encoding="utf-8")


def test_invalid_level_falls_back_to_info(tmp_path) -> None:
    """잘못된 LOG_LEVEL은 INFO로 폴백"""
    prop = tmp_path / "log.properties"
    prop.write_text("LOG_LEVEL=BOGUS\n", encoding="utf-8")
    cfg = Config(str(prop))

    logger = setup_logger("oma.test.badlevel", cfg)
    assert logger.level == logging.INFO
