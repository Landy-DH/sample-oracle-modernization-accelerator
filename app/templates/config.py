"""
설정 파일 로더

oma.properties를 로드하고 설정 값을 제공

변경 이력:
[날짜] [작성자] | 템플릿 생성
  - Config 클래스 스켈레톤
  - load(), get() 메서드 구조
"""

import os
from typing import Any, Optional


class Config:
    """
    OMA 설정 관리 클래스

    oma.properties 파일을 로드하고 설정 값을 제공
    환경 변수 치환 (${VAR}) 지원
    """

    def __init__(self, config_file: str, region: Optional[str] = None):
        """
        초기화

        Args:
            config_file: oma.properties 파일 경로
            region: AWS region (선택)
        """
        self.config_file = config_file
        self.region = region
        self.config = {}

        self._load()

    def _load(self):
        """
        설정 파일 로드

        TODO:
        1. config_file 읽기
        2. 주석 제거 (# 또는 ;로 시작하는 줄)
        3. key=value 파싱
        4. 환경 변수 치환 (${VAR} → os.environ['VAR'])
        5. self.config에 저장
        """
        # TODO: 구현
        pass

    def get(self, key: str, default: Any = None) -> Any:
        """
        설정 값 조회

        Args:
            key: 설정 키
            default: 기본 값

        Returns:
            설정 값 또는 기본 값

        TODO:
        1. self.config에서 key 조회
        2. 없으면 default 반환
        3. 타입 변환 (int, bool, list 등)
        """
        # TODO: 구현
        pass

    def get_int(self, key: str, default: int = 0) -> int:
        """정수 값 조회"""
        value = self.get(key, default)
        return int(value) if value is not None else default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """불린 값 조회"""
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('true', 'yes', '1')
        return default

    def get_list(self, key: str, separator: str = ',', default: list = None) -> list:
        """리스트 값 조회"""
        value = self.get(key, default)
        if isinstance(value, str):
            return [item.strip() for item in value.split(separator)]
        return default or []
