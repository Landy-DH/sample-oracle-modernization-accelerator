"""
DictionaryLoader 단위 테스트

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - load/lookup/캐싱/에러 처리 테스트
"""

import json

import pytest

from oma.dictionary.loader import DictionaryLoader
from oma.utils.exceptions import ConfigError

_SAMPLE_DICT = {
    "users.user_id": {
        "table": "users",
        "column": "user_id",
        "data_type": "integer",
        "sample_value": 123,
        "cast_hint": {"needs_cast_from_string": True, "cast_syntax": "::INTEGER"},
    },
    "users.name": {
        "table": "users",
        "column": "name",
        "data_type": "character varying",
        "sample_value": "Alice",
        "cast_hint": {"needs_cast_from_string": False},
    },
}


@pytest.fixture
def dict_file(tmp_path):
    """샘플 딕셔너리 JSON 파일 경로"""
    path = tmp_path / "schema_dictionary.json"
    path.write_text(json.dumps(_SAMPLE_DICT), encoding="utf-8")
    return str(path)


def test_load(dict_file):
    """파일 로드 후 전체 딕셔너리 반환"""
    loader = DictionaryLoader(dict_file)
    d = loader.load()
    assert "users.user_id" in d
    assert len(d) == 2


def test_lookup_found(dict_file):
    """존재하는 컬럼 조회 시 found=True + 데이터"""
    loader = DictionaryLoader(dict_file)
    result = loader.lookup("users.user_id")
    assert result["found"] is True
    assert result["data_type"] == "integer"
    assert result["cast_hint"]["cast_syntax"] == "::INTEGER"


def test_lookup_case_insensitive(dict_file):
    """대소문자 무관 조회"""
    loader = DictionaryLoader(dict_file)
    assert loader.lookup("USERS.USER_ID")["found"] is True


def test_lookup_not_found(dict_file):
    """없는 컬럼은 found=False (예외 없음)"""
    loader = DictionaryLoader(dict_file)
    result = loader.lookup("unknown.column")
    assert result == {"found": False}


def test_lookup_does_not_mutate_source(dict_file):
    """lookup 결과에 found를 더해도 원본 딕셔너리는 불변"""
    loader = DictionaryLoader(dict_file)
    loader.lookup("users.user_id")
    assert "found" not in loader.load()["users.user_id"]


def test_has(dict_file):
    """has()는 존재 여부만 반환"""
    loader = DictionaryLoader(dict_file)
    assert loader.has("users.name") is True
    assert loader.has("users.missing") is False


def test_load_caches(dict_file):
    """load()는 최초 1회만 파일을 읽고 이후 캐시 반환"""
    loader = DictionaryLoader(dict_file)
    first = loader.load()
    second = loader.load()
    assert first is second  # 동일 객체 (재파싱 안 함)


def test_load_missing_path_raises():
    """경로 미지정 시 ConfigError"""
    loader = DictionaryLoader()
    with pytest.raises(ConfigError):
        loader.load()


def test_load_missing_file_raises(tmp_path):
    """없는 파일 경로는 ConfigError"""
    loader = DictionaryLoader(str(tmp_path / "nope.json"))
    with pytest.raises(ConfigError):
        loader.load()


def test_load_invalid_json_raises(tmp_path):
    """깨진 JSON은 ConfigError"""
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid", encoding="utf-8")
    loader = DictionaryLoader(str(bad))
    with pytest.raises(ConfigError):
        loader.load()
