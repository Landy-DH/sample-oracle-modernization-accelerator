"""
DB 플러그인 단위 테스트 (드라이버/시크릿 mock, 실제 DB 불필요)

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - Oracle service_name→SID 폴백, Postgres 연결, factory 선택/자격증명 획득 테스트

2026-07-28 | OMA Team | EPAS 소스 지원 테스트 추가 (조합 B)
  - EpasSource psycopg2 연결(폴백 없음)/스키마/방언, factory epas 선택 테스트
"""

import sys
import types
from unittest.mock import MagicMock

import pytest

from oma.plugins import create_source, create_target
from oma.plugins.source_epas import EpasSource
from oma.plugins.source_oracle import OracleSource
from oma.plugins.target_postgres import PostgresTarget
from oma.utils.config import Config
from oma.utils.exceptions import ConfigError, DatabaseError


# ---- Oracle: service_name → SID 폴백 ----------------------------------------

@pytest.fixture
def fake_oracledb(monkeypatch):
    """oracledb 모듈을 대체하는 fake. makedsn/connect 동작을 제어한다."""
    mod = types.ModuleType("oracledb")

    def makedsn(host, port, **kwargs):
        # 어떤 모드(service_name/sid)로 호출됐는지 dsn 문자열에 담아 반환
        mode = "service_name" if "service_name" in kwargs else "sid"
        return f"{host}:{port}/{mode}={list(kwargs.values())[0]}"

    mod.makedsn = makedsn
    mod._connect_behavior = {}  # dsn substring -> raise? 설정용
    mod._calls = []

    def connect(user, password, dsn):
        mod._calls.append(dsn)
        if "service_name" in dsn and mod._connect_behavior.get("service_name_fail"):
            raise RuntimeError("ORA-12505: service_name not registered")
        if "sid=" in dsn and mod._connect_behavior.get("sid_fail"):
            raise RuntimeError("ORA-12505: SID not registered")
        conn = MagicMock(name="oracle_conn")
        return conn

    mod.connect = connect
    monkeypatch.setitem(sys.modules, "oracledb", mod)
    return mod


def _oracle_creds():
    return {
        "host": "10.0.0.1", "port": 1521, "sid": "ORCLPDB1",
        "username": "system", "password": "pw",
    }


def test_oracle_connect_service_name_first(fake_oracledb):
    """service_name이 성공하면 SID는 시도하지 않음"""
    src = OracleSource(_oracle_creds())
    src.connect()
    assert len(fake_oracledb._calls) == 1
    assert "service_name" in fake_oracledb._calls[0]


def test_oracle_fallback_to_sid(fake_oracledb):
    """service_name 실패 시 SID로 폴백하여 성공"""
    fake_oracledb._connect_behavior["service_name_fail"] = True
    src = OracleSource(_oracle_creds())
    conn = src.connect()
    assert conn is not None
    assert len(fake_oracledb._calls) == 2
    assert "service_name" in fake_oracledb._calls[0]
    assert "sid=" in fake_oracledb._calls[1]


def test_oracle_all_modes_fail_raises(fake_oracledb):
    """둘 다 실패하면 DatabaseError (시도 내역 포함)"""
    fake_oracledb._connect_behavior["service_name_fail"] = True
    fake_oracledb._connect_behavior["sid_fail"] = True
    src = OracleSource(_oracle_creds())
    with pytest.raises(DatabaseError) as exc:
        src.connect()
    assert "attempts" in exc.value.context


def test_oracle_schema_name_uppercased(fake_oracledb):
    """target_schema가 대문자로 반환됨"""
    creds = _oracle_creds()
    creds["target_schema"] = "wms_app"
    assert OracleSource(creds).get_schema_name() == "WMS_APP"


def test_oracle_dialect(fake_oracledb):
    assert OracleSource(_oracle_creds()).get_sql_dialect() == "oracle"


# ---- Postgres ---------------------------------------------------------------

@pytest.fixture
def fake_psycopg2(monkeypatch):
    """psycopg2 모듈 대체 fake"""
    mod = types.ModuleType("psycopg2")
    mod._calls = []

    def connect(**kwargs):
        mod._calls.append(kwargs)
        return MagicMock(name="pg_conn")

    mod.connect = connect
    monkeypatch.setitem(sys.modules, "psycopg2", mod)
    return mod


def _pg_creds():
    return {
        "host": "aurora.example.com", "port": 5432, "database": "appdb",
        "username": "appdb", "password": "pw",
    }


def test_postgres_connect(fake_psycopg2):
    """psycopg2.connect에 자격증명이 매핑됨"""
    tgt = PostgresTarget(_pg_creds())
    tgt.connect()
    call = fake_psycopg2._calls[0]
    assert call["host"] == "aurora.example.com"
    assert call["dbname"] == "appdb"
    assert call["connect_timeout"] == 10


def test_postgres_schema_from_username(fake_psycopg2):
    """schema 미지정 시 username을 스키마로 사용"""
    assert PostgresTarget(_pg_creds()).get_schema_name() == "appdb"


def test_postgres_get_connection_lazy(fake_psycopg2):
    """get_connection은 최초 1회만 연결"""
    tgt = PostgresTarget(_pg_creds())
    c1 = tgt.get_connection()
    c2 = tgt.get_connection()
    assert c1 is c2
    assert len(fake_psycopg2._calls) == 1


def test_postgres_connect_failure_wrapped(fake_psycopg2):
    """연결 예외는 DatabaseError로 래핑"""
    def boom(**kwargs):
        raise RuntimeError("could not connect")
    fake_psycopg2.connect = boom
    with pytest.raises(DatabaseError):
        PostgresTarget(_pg_creds()).connect()


# ---- EPAS (psycopg2, 폴백 없음) --------------------------------------------

def _epas_creds():
    return {
        "host": "db-thepop.example.com", "port": 5446, "database": "dgscm",
        "username": "oma_user", "password": "pw", "target_schema": "gscmadm",
    }


def test_epas_connect(fake_psycopg2):
    """EPAS는 psycopg2로 접속하며 database명을 dbname으로 매핑"""
    src = EpasSource(_epas_creds())
    src.connect()
    call = fake_psycopg2._calls[0]
    assert call["host"] == "db-thepop.example.com"
    assert call["dbname"] == "dgscm"
    assert call["connect_timeout"] == 10
    # Oracle과 달리 폴백 없이 단 1회 연결
    assert len(fake_psycopg2._calls) == 1


def test_epas_schema_from_target_schema(fake_psycopg2):
    """target_schema를 스키마로 사용 (Oracle과 달리 대문자화하지 않음)"""
    assert EpasSource(_epas_creds()).get_schema_name() == "gscmadm"


def test_epas_schema_falls_back_to_username(fake_psycopg2):
    """target_schema/schema 없으면 username 사용"""
    creds = {"host": "h", "port": 5446, "database": "d", "username": "appuser"}
    assert EpasSource(creds).get_schema_name() == "appuser"


def test_epas_dialect(fake_psycopg2):
    assert EpasSource(_epas_creds()).get_sql_dialect() == "epas"


def test_epas_get_connection_lazy(fake_psycopg2):
    """get_connection은 최초 1회만 연결"""
    src = EpasSource(_epas_creds())
    c1 = src.get_connection()
    c2 = src.get_connection()
    assert c1 is c2
    assert len(fake_psycopg2._calls) == 1


def test_epas_connect_failure_wrapped(fake_psycopg2):
    """연결 예외는 DatabaseError로 래핑"""
    def boom(**kwargs):
        raise RuntimeError("could not connect")
    fake_psycopg2.connect = boom
    with pytest.raises(DatabaseError):
        EpasSource(_epas_creds()).connect()


# ---- Factory ----------------------------------------------------------------

def _config(tmp_path, extra=""):
    prop = tmp_path / "oma.properties"
    prop.write_text(
        "SOURCE_DB_TYPE=oracle\nTARGET_DB_TYPE=postgres\n"
        "USE_SECRETS_MANAGER=true\nAWS_REGION=ap-northeast-2\n"
        "SOURCE_SECRET_NAME=oma-source-admin\n"
        "TARGET_SECRET_NAME=oma-target-service\n" + extra,
        encoding="utf-8",
    )
    return Config(str(prop))


def test_factory_create_target_uses_secret(tmp_path):
    """create_target: 시크릿에서 자격증명을 받아 PostgresTarget 생성"""
    cfg = _config(tmp_path)
    fake_mgr = MagicMock()
    fake_mgr.get_secret.return_value = _pg_creds()

    tgt = create_target(cfg, secrets_manager=fake_mgr)
    assert isinstance(tgt, PostgresTarget)
    fake_mgr.get_secret.assert_called_once_with("oma-target-service")
    assert tgt.get_schema_name() == "appdb"


def test_factory_create_source_uses_secret(tmp_path):
    """create_source: 시크릿 기반 OracleSource 생성"""
    cfg = _config(tmp_path)
    fake_mgr = MagicMock()
    fake_mgr.get_secret.return_value = _oracle_creds()

    src = create_source(cfg, secrets_manager=fake_mgr)
    assert isinstance(src, OracleSource)
    fake_mgr.get_secret.assert_called_once_with("oma-source-admin")


def test_factory_create_epas_source_uses_secret(tmp_path):
    """create_source: SOURCE_DB_TYPE=epas 면 시크릿 기반 EpasSource 생성"""
    cfg = _config(tmp_path, extra="")
    cfg.config["SOURCE_DB_TYPE"] = "epas"
    fake_mgr = MagicMock()
    fake_mgr.get_secret.return_value = _epas_creds()

    src = create_source(cfg, secrets_manager=fake_mgr)
    assert isinstance(src, EpasSource)
    fake_mgr.get_secret.assert_called_once_with("oma-source-admin")
    assert src.get_schema_name() == "gscmadm"


def test_factory_epas_local_credentials_use_database_key(tmp_path):
    """USE_SECRETS_MANAGER=false + epas: SOURCE_DATABASE가 database 키로 매핑됨"""
    prop = tmp_path / "oma.properties"
    prop.write_text(
        "SOURCE_DB_TYPE=epas\nUSE_SECRETS_MANAGER=false\n"
        "SOURCE_HOST=db-thepop\nSOURCE_PORT=5446\nSOURCE_DATABASE=dgscm\n"
        "SOURCE_ADMIN_USER=oma_user\nSOURCE_ADMIN_PASSWORD=pw\n"
        "SOURCE_TARGET_SCHEMA=gscmadm\n",
        encoding="utf-8",
    )
    cfg = Config(str(prop))
    src = create_source(cfg)
    assert isinstance(src, EpasSource)
    assert src.credentials["database"] == "dgscm"
    assert "sid" not in src.credentials
    assert src.get_schema_name() == "gscmadm"


def test_factory_unsupported_target_raises(tmp_path):
    """지원하지 않는 TARGET_DB_TYPE은 ConfigError"""
    cfg = _config(tmp_path, extra="")
    cfg.config["TARGET_DB_TYPE"] = "mysql"
    with pytest.raises(ConfigError):
        create_target(cfg, secrets_manager=MagicMock())


def test_factory_local_credentials_without_secrets(tmp_path):
    """USE_SECRETS_MANAGER=false 면 config 로컬 값으로 자격증명 구성"""
    prop = tmp_path / "oma.properties"
    prop.write_text(
        "TARGET_DB_TYPE=postgres\nUSE_SECRETS_MANAGER=false\n"
        "TARGET_HOST=localhost\nTARGET_PORT=5432\nTARGET_DATABASE=db\n"
        "TARGET_SCHEMA=myschema\nTARGET_USER=u\nTARGET_PASSWORD=p\n",
        encoding="utf-8",
    )
    cfg = Config(str(prop))
    tgt = create_target(cfg)
    assert tgt.credentials["host"] == "localhost"
    assert tgt.get_schema_name() == "myschema"
