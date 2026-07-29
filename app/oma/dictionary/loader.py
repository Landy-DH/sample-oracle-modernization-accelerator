"""
스키마 딕셔너리 로더 모듈

builder가 생성한 schema_dictionary.json을 로드하고 "table.column" 키로 조회한다.
LLM 변환 단계에서 컬럼 타입/캐스팅 힌트를 조회하는 진입점이다.

조회 실패 시 예외를 던지지 않고 {"found": False}를 반환한다
(01-migration-principles.md: 조회 실패해도 변환은 계속 진행).

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - DictionaryLoader 구현: load/lookup + 로드 결과 캐싱
  - lookup은 대소문자 무관 조회, 미발견 시 {"found": False}
"""

import json
import logging
import os
from typing import Any, Dict, Optional

from oma.utils.exceptions import ConfigError

logger = logging.getLogger(__name__)


class DictionaryLoader:
    """
    스키마 딕셔너리 로더

    JSON 딕셔너리를 1회 로드해 메모리에 캐싱하고, "table.column" 키로 조회한다.

    Attributes:
        file_path: 로드할 딕셔너리 파일 경로 (선택)
    """

    def __init__(self, file_path: Optional[str] = None) -> None:
        """
        초기화

        Args:
            file_path: 딕셔너리 파일 경로. 주면 즉시 로드하지 않고 load() 호출 시 사용
        """
        self.file_path = file_path
        self._dictionary: Optional[Dict[str, Any]] = None

    def load(self, file_path: Optional[str] = None) -> Dict[str, Any]:
        """
        딕셔너리 JSON을 로드한다 (이미 로드했으면 캐시 반환).

        Args:
            file_path: 로드할 경로. None이면 생성자에 준 file_path 사용

        Returns:
            로드된 딕셔너리

        Raises:
            ConfigError: 경로 미지정, 파일 없음, JSON 파싱 실패 시
        """
        if self._dictionary is not None:
            return self._dictionary

        path = file_path or self.file_path
        if not path:
            raise ConfigError("딕셔너리 파일 경로가 지정되지 않았습니다")

        if not os.path.isfile(path):
            raise ConfigError(
                "딕셔너리 파일을 찾을 수 없습니다", {"file_path": path}
            )

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            raise ConfigError(
                "딕셔너리 파일을 로드할 수 없습니다",
                {"file_path": path, "error": str(e)},
            ) from e

        self.file_path = path
        self._dictionary = data
        logger.info("딕셔너리 로드 완료: %s (%d개 컬럼)", path, len(data))
        return self._dictionary

    def lookup(self, table_column: str) -> Dict[str, Any]:
        """
        "table.column" 키로 컬럼 정보를 조회한다 (대소문자 무관).

        조회 성공 시 딕셔너리 엔트리에 found=True를 더해 반환하고,
        실패 시 {"found": False}를 반환한다 (예외 없음).

        Args:
            table_column: "table.column" 형식의 키

        Returns:
            found 필드를 포함한 조회 결과
        """
        dictionary = self.load()
        key = table_column.lower()

        entry = dictionary.get(key)
        if entry is None:
            logger.debug("딕셔너리 조회 실패: %s", table_column)
            return {"found": False}

        # 원본 엔트리를 훼손하지 않도록 복사본에 found 추가
        result = dict(entry)
        result["found"] = True
        return result

    def has(self, table_column: str) -> bool:
        """
        해당 키가 딕셔너리에 존재하는지 여부 (대소문자 무관).

        Args:
            table_column: "table.column" 형식의 키

        Returns:
            존재 여부
        """
        return table_column.lower() in self.load()
