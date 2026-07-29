"""
Config 클래스 단위 테스트

변경 이력:
2026-07-26 | OMA Team | 초기 생성
  - 로드/기본값/타입변환/변수치환/주석처리 테스트

2026-07-28 | OMA Team | EPAS 배포 반영
  - oma.properties의 SOURCE_DB_TYPE가 epas로 변경됨(조합 B 배포) → 기대값 갱신
"""

import os

import pytest

from oma.utils.config import Config
from oma.utils.exceptions import ConfigError

# 프로젝트 루트의 실제 oma.properties 경로
PROPERTIES_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "oma.properties"
)


@pytest.fixture
def config() -> Config:
    """실제 oma.properties 기반 Config 인스턴스"""
    return Config(PROPERTIES_PATH)


def test_config_load(config: Config) -> None:
    """기본 문자열 값 로드 (현재 배포 조합: EPAS→PostgreSQL)"""
    assert config.get("SOURCE_DB_TYPE") == "epas"
    assert config.get("TARGET_DB_TYPE") == "postgres"


def test_config_get_with_default(config: Config) -> None:
    """없는 키는 default 반환"""
    assert config.get("NONEXISTENT", "default") == "default"
    assert config.get("NONEXISTENT") is None


def test_config_int_conversion(config: Config) -> None:
    """숫자 문자열은 int로 자동 변환"""
    assert config.get("MAX_WORKERS") == 7
    assert isinstance(config.get("MAX_WORKERS"), int)


def test_config_inline_comment_stripped(config: Config) -> None:
    """인라인 주석(' #...')은 값에서 제거됨"""
    # LLM_RPM_LIMIT=50    # Requests per minute
    assert config.get("LLM_RPM_LIMIT") == 50


def test_config_variable_substitution(config: Config) -> None:
    """${OMA_BASE_DIR} 참조가 다른 설정 키로 치환됨"""
    base = config.get("OMA_BASE_DIR")
    mapper_dir = config.get("MAPPER_WORK_DIR")
    assert "${" not in str(mapper_dir)
    assert str(mapper_dir).startswith(str(base))
    assert str(mapper_dir).endswith("/mappers")


def test_config_per_project_work_dir(config: Config) -> None:
    """작업 경로가 projects/<APPLICATION_NAME> 아래로 구성됨 (멀티 프로젝트)"""
    app = config.get("APPLICATION_NAME")
    project_dir = config.get("PROJECT_WORK_DIR")
    assert "${" not in str(project_dir)
    assert str(project_dir).endswith(f"/projects/{app}")

    # 모든 산출물 경로가 프로젝트 작업 디렉토리 아래에 위치
    for key in ("MAPPER_WORK_DIR", "SCHEMA_DICT_PATH", "TESTCASE_DIR",
                "REPORT_DIR", "CHECKPOINT_PATH"):
        value = str(config.get(key))
        assert "${" not in value
        assert value.startswith(str(project_dir))


def test_config_section_header_ignored(config: Config) -> None:
    """[COMMON], [oma] 섹션 헤더는 무시되고 키만 관리됨"""
    assert "[COMMON]" not in config.config
    assert "[oma]" not in config.config
    # 섹션 안의 키가 정상 로드되는지 (값 자체는 프로젝트마다 다를 수 있음)
    assert config.get("APPLICATION_NAME")


def test_get_bool(config: Config) -> None:
    """불린 조회"""
    assert config.get_bool("USE_SECRETS_MANAGER") is True
    assert config.get_bool("NONEXISTENT", True) is True
    assert config.get_bool("NONEXISTENT", False) is False


def test_get_int_invalid_raises(config: Config) -> None:
    """정수 변환 불가 시 ConfigError"""
    with pytest.raises(ConfigError):
        config.get_int("SOURCE_DB_TYPE")


def test_get_list(tmp_path) -> None:
    """구분자 기반 리스트 조회"""
    prop = tmp_path / "t.properties"
    prop.write_text("DBS=oracle, edb ,tibero\n", encoding="utf-8")
    cfg = Config(str(prop))
    assert cfg.get_list("DBS") == ["oracle", "edb", "tibero"]
    assert cfg.get_list("MISSING") == []


def test_missing_file_raises() -> None:
    """존재하지 않는 파일은 ConfigError"""
    with pytest.raises(ConfigError):
        Config("/nonexistent/path/oma.properties")


def test_env_var_substitution(tmp_path, monkeypatch) -> None:
    """설정 키에 없으면 환경 변수로 치환"""
    monkeypatch.setenv("MY_ENV_HOST", "db.example.com")
    prop = tmp_path / "t.properties"
    prop.write_text("HOST=${MY_ENV_HOST}\n", encoding="utf-8")
    cfg = Config(str(prop))
    assert cfg.get("HOST") == "db.example.com"


def test_unresolved_variable_preserved(tmp_path) -> None:
    """해결 불가능한 ${VAR}는 원본 유지"""
    prop = tmp_path / "t.properties"
    prop.write_text("X=${TOTALLY_UNKNOWN_VAR}\n", encoding="utf-8")
    cfg = Config(str(prop))
    assert cfg.get("X") == "${TOTALLY_UNKNOWN_VAR}"
