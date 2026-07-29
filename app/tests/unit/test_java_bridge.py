"""
JavaValidationBridge 단위 테스트 (subprocess mock)

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - 요청 구성(JDBC URL)/배치 검증/타임아웃/에러/빈입력 테스트

2026-07-28 | OMA Team | EPAS 소스 JDBC URL 분기 테스트 추가 (조합 B)
  - source_type=epas 면 소스 URL이 jdbc:postgresql + org.postgresql.Driver
"""

import json
import subprocess
from unittest.mock import patch

import pytest

from oma.validation.java_bridge import JavaValidationBridge
from oma.utils.exceptions import ValidationError

_SRC_CREDS = {"host": "10.0.0.1", "port": 1521, "sid": "ORCLPDB1",
              "username": "system", "password": "pw"}
_TGT_CREDS = {"host": "aurora.example.com", "port": 5432, "database": "appdb",
              "username": "appdb", "password": "pw"}


def _bridge(**kw):
    defaults = dict(
        jar_path="x.jar", source_mapper_dir="/src", target_mapper_dir="/tgt",
        source_credentials=_SRC_CREDS, target_credentials=_TGT_CREDS,
    )
    defaults.update(kw)
    return JavaValidationBridge(**defaults)


def test_build_request_structure():
    """요청 JSON에 매퍼 디렉토리/DB설정/TC 포함"""
    b = _bridge()
    req = b.build_request([{"test_case_id": "tc1"}])
    assert req["sourceMapperDir"] == "/src"
    assert req["targetMapperDir"] == "/tgt"
    assert req["testCases"] == [{"test_case_id": "tc1"}]


def test_oracle_url_uses_service_name():
    """Oracle URL은 service_name(//host:port/service) 형식"""
    b = _bridge()
    src = b.build_request([])["source"]
    assert src["url"] == "jdbc:oracle:thin:@//10.0.0.1:1521/ORCLPDB1"
    assert src["driver"] == "oracle.jdbc.OracleDriver"


def test_postgres_url():
    """PostgreSQL URL 형식"""
    b = _bridge()
    tgt = b.build_request([])["target"]
    assert tgt["url"] == "jdbc:postgresql://aurora.example.com:5432/appdb"
    assert tgt["driver"] == "org.postgresql.Driver"


def test_epas_source_url_uses_postgresql_driver():
    """source_type=epas 면 소스 URL이 postgresql 프로토콜/드라이버"""
    epas_creds = {"host": "db-thepop", "port": 5446, "database": "dgscm",
                  "username": "oma_user", "password": "pw"}
    b = _bridge(source_credentials=epas_creds, source_type="epas")
    src = b.build_request([])["source"]
    assert src["url"] == "jdbc:postgresql://db-thepop:5446/dgscm"
    assert src["driver"] == "org.postgresql.Driver"


def test_default_source_type_is_oracle():
    """source_type 미지정 시 기존 Oracle 동작 유지 (하위호환)"""
    b = _bridge()
    src = b.build_request([])["source"]
    assert src["url"].startswith("jdbc:oracle:thin:@//")


def test_validate_batch_parses_result():
    """정상 실행 시 결과 JSON 파싱"""
    b = _bridge()
    fake_out = json.dumps([
        {"tcId": "tc1", "status": "ok"},
        {"tcId": "tc2", "status": "ok"},
    ])
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=fake_out, stderr="")
        results = b.validate_batch([{"test_case_id": "tc1"}, {"test_case_id": "tc2"}])
    assert len(results) == 2
    assert results[0]["tcId"] == "tc1"


def test_validate_batch_empty_short_circuits():
    """빈 TC 목록은 Java 호출 없이 빈 리스트"""
    b = _bridge()
    with patch("subprocess.run") as mock_run:
        assert b.validate_batch([]) == []
        mock_run.assert_not_called()


def test_validate_batch_sends_input():
    """subprocess에 요청 JSON이 stdin으로 전달됨"""
    b = _bridge()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="[]", stderr="")
        b.validate_batch([{"test_case_id": "tc1"}])
        _, kwargs = mock_run.call_args
        sent = json.loads(kwargs["input"])
        assert sent["testCases"][0]["test_case_id"] == "tc1"


def test_nonzero_returncode_raises():
    """returncode != 0 이면 ValidationError"""
    b = _bridge()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr='{"error":"boom"}')
        with pytest.raises(ValidationError):
            b.validate_batch([{"test_case_id": "tc1"}])


def test_timeout_raises():
    """타임아웃 시 ValidationError"""
    b = _bridge(timeout=5)
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("java", 5)):
        with pytest.raises(ValidationError):
            b.validate_batch([{"test_case_id": "tc1"}])


def test_missing_jar_raises():
    """java/JAR 없으면 ValidationError"""
    b = _bridge()
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        with pytest.raises(ValidationError):
            b.validate_batch([{"test_case_id": "tc1"}])


def test_invalid_output_raises():
    """출력이 JSON이 아니면 ValidationError"""
    b = _bridge()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="not json", stderr="")
        with pytest.raises(ValidationError):
            b.validate_batch([{"test_case_id": "tc1"}])


def test_from_config(tmp_path):
    """from_config: MAPPER_WORK_DIR 기반 경로 구성"""
    from oma.utils.config import Config
    prop = tmp_path / "oma.properties"
    prop.write_text(
        "OMA_BASE_DIR=/base\nAPPLICATION_NAME=wms\n"
        "PROJECT_WORK_DIR=${OMA_BASE_DIR}/projects/${APPLICATION_NAME}\n"
        "MAPPER_WORK_DIR=${PROJECT_WORK_DIR}/mappers\n",
        encoding="utf-8",
    )
    cfg = Config(str(prop))
    b = JavaValidationBridge.from_config(cfg, _SRC_CREDS, _TGT_CREDS)
    assert b.source_mapper_dir == "/base/projects/wms/mappers/original"
    assert b.target_mapper_dir == "/base/projects/wms/mappers/merged"


def test_from_config_propagates_source_type(tmp_path):
    """from_config: SOURCE_DB_TYPE가 브리지 source_type으로 전달됨"""
    from oma.utils.config import Config
    prop = tmp_path / "oma.properties"
    prop.write_text(
        "OMA_BASE_DIR=/base\nAPPLICATION_NAME=wms\n"
        "SOURCE_DB_TYPE=epas\n"
        "PROJECT_WORK_DIR=${OMA_BASE_DIR}/projects/${APPLICATION_NAME}\n"
        "MAPPER_WORK_DIR=${PROJECT_WORK_DIR}/mappers\n",
        encoding="utf-8",
    )
    cfg = Config(str(prop))
    b = JavaValidationBridge.from_config(cfg, _SRC_CREDS, _TGT_CREDS)
    assert b.source_type == "epas"
