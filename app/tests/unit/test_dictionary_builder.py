"""
DictionaryBuilder 단위 테스트 (DB 커넥션 mock)

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - 메타데이터/샘플/캐스팅 힌트/저장 테스트 (fake connection 주입)
"""

import datetime
import json
from typing import Any, List

import pytest
from psycopg2 import sql as pg_sql

from oma.dictionary.builder import DictionaryBuilder
from oma.utils.config import Config


def _last_identifier(composed: Any) -> str:
    """sql.Composed 안의 마지막 Identifier 문자열(테이블명)을 반환한다."""
    identifiers = [
        part.string
        for part in composed.seq
        if isinstance(part, pg_sql.Identifier)
    ]
    return identifiers[-1] if identifiers else ""


# ---- 테스트용 fake DB 커넥션 -------------------------------------------------

class _FakeCursor:
    """cursor context manager 흉내. execute 호출에 따라 결과를 돌려준다."""

    def __init__(self, meta_rows, sample_rows_by_table):
        self._meta_rows = meta_rows
        self._sample_rows_by_table = sample_rows_by_table
        self.description = None
        self._result: List[Any] = []
        self._single = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query, params=None):
        if isinstance(query, str):
            # 메타데이터 조회 (문자열 쿼리)
            self.description = [
                ("table_name",), ("column_name",), ("data_type",),
                ("is_nullable",), ("character_maximum_length",),
                ("numeric_precision",), ("numeric_scale",),
            ]
            self._result = self._meta_rows
        else:
            # 샘플 조회: sql.Composed 를 순회해 Identifier 에서 테이블명 추출
            # 형식: SELECT * FROM {schema}.{table} LIMIT {n}
            #  → Identifier 순서상 마지막이 테이블명
            table = _last_identifier(query)
            cols, row = self._sample_rows_by_table.get(table, ([], None))
            self.description = [(c,) for c in cols]
            self._single = row

    def fetchall(self):
        return self._result

    def fetchone(self):
        return self._single


class _FakeConnection:
    def __init__(self, meta_rows, sample_rows_by_table):
        self._meta_rows = meta_rows
        self._sample_rows_by_table = sample_rows_by_table

    def cursor(self):
        return _FakeCursor(self._meta_rows, self._sample_rows_by_table)


# ---- fixtures ---------------------------------------------------------------

@pytest.fixture
def meta_rows():
    """information_schema.columns 결과 (users, orders)"""
    return [
        ("users", "user_id", "integer", "NO", None, 32, 0),
        ("users", "name", "character varying", "YES", 100, None, None),
        ("users", "status", "character", "NO", 1, None, None),
        ("users", "created_at", "timestamp without time zone", "YES", None, None, None),
        ("orders", "order_id", "bigint", "NO", None, 64, 0),
        ("orders", "amount", "numeric", "YES", None, 10, 2),
    ]


@pytest.fixture
def sample_rows():
    """테이블별 샘플 1건"""
    return {
        "users": (
            ["user_id", "name", "status", "created_at"],
            (123, "Alice", "A", datetime.datetime(2026, 1, 1, 10, 0, 0)),
        ),
        "orders": (["order_id", "amount"], (9001, 199.99)),
    }


@pytest.fixture
def config(tmp_path):
    """TARGET_SCHEMA와 SCHEMA_DICT_PATH를 담은 Config"""
    prop = tmp_path / "oma.properties"
    dict_path = tmp_path / "output" / "schema_dictionary.json"
    prop.write_text(
        f"TARGET_SCHEMA=public\nSCHEMA_DICT_PATH={dict_path}\n",
        encoding="utf-8",
    )
    return Config(str(prop))


@pytest.fixture
def builder(config, meta_rows, sample_rows):
    conn = _FakeConnection(meta_rows, sample_rows)
    return DictionaryBuilder(config, connection=conn)


# ---- tests ------------------------------------------------------------------

def test_build_structure(builder: DictionaryBuilder):
    """build() 결과의 키/기본 필드 구조 확인"""
    dictionary = builder.build()

    assert "users.user_id" in dictionary
    entry = dictionary["users.user_id"]
    assert entry["data_type"] == "integer"
    assert entry["table"] == "users"
    assert entry["column"] == "user_id"
    assert entry["is_nullable"] is False
    assert "sample_value" in entry


def test_sample_values_collected(builder: DictionaryBuilder):
    """샘플 값이 컬럼별로 매핑됨"""
    d = builder.build()
    assert d["users.user_id"]["sample_value"] == 123
    assert d["users.name"]["sample_value"] == "Alice"
    # datetime은 문자열로 직렬화됨
    assert isinstance(d["users.created_at"]["sample_value"], str)


def test_numeric_cast_hint(builder: DictionaryBuilder):
    """숫자 타입은 needs_cast_from_string + cast_syntax"""
    d = builder.build()
    assert d["users.user_id"]["cast_hint"]["needs_cast_from_string"] is True
    assert d["users.user_id"]["cast_hint"]["cast_syntax"] == "::INTEGER"
    assert d["orders.order_id"]["cast_hint"]["cast_syntax"] == "::BIGINT"
    assert d["orders.amount"]["cast_hint"]["cast_syntax"] == "::NUMERIC"


def test_char_trim_hint(builder: DictionaryBuilder):
    """character(고정길이)는 needs_trim"""
    d = builder.build()
    assert d["users.status"]["cast_hint"]["needs_trim"] is True


def test_datetime_cast_hint(builder: DictionaryBuilder):
    """timestamp는 ::TIMESTAMP 캐스팅 힌트"""
    d = builder.build()
    hint = d["users.created_at"]["cast_hint"]
    assert hint["needs_cast_from_string"] is True
    assert hint["cast_syntax"] == "::TIMESTAMP"


def test_varchar_no_cast(builder: DictionaryBuilder):
    """varchar는 캐스팅/트림 불필요"""
    d = builder.build()
    hint = d["users.name"]["cast_hint"]
    assert hint["needs_cast_from_string"] is False
    assert hint["needs_trim"] is False


def test_save_to_file_written(builder: DictionaryBuilder, config: Config):
    """build() 후 JSON 파일이 생성되고 다시 로드 가능"""
    builder.build()
    path = config.get("SCHEMA_DICT_PATH")
    with open(path, encoding="utf-8") as f:
        loaded = json.load(f)
    assert "users.user_id" in loaded
    assert loaded["orders.amount"]["numeric_scale"] == 2


def test_build_with_target_plugin(config, meta_rows, sample_rows):
    """target 플러그인 주입 시 커넥션+스키마를 플러그인에서 가져옴"""
    conn = _FakeConnection(meta_rows, sample_rows)

    class _FakeTarget:
        def get_connection(self):
            return conn

        def get_schema_name(self):
            return "appdb"

    builder = DictionaryBuilder(config, target=_FakeTarget())
    assert builder.schema == "appdb"
    d = builder.build()
    assert d["users.user_id"]["data_type"] == "integer"


def test_sample_query_failure_is_skipped(config: Config, meta_rows):
    """샘플 조회가 실패해도 딕셔너리 생성은 계속됨 (sample_value=None)"""

    class _FailingSampleConn(_FakeConnection):
        def cursor(self):
            cur = _FakeCursor(self._meta_rows, self._sample_rows_by_table)
            original_execute = cur.execute

            def execute(query, params=None):
                if isinstance(query, str):
                    return original_execute(query, params)
                raise RuntimeError("permission denied")

            cur.execute = execute
            return cur

    builder = DictionaryBuilder(config, connection=_FailingSampleConn(meta_rows, {}))
    d = builder.build()
    assert d["users.user_id"]["sample_value"] is None
    assert len(d) == len(meta_rows)
