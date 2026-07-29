"""
스키마 딕셔너리 생성 모듈

PostgreSQL 메타데이터 추출 및 딕셔너리 JSON 생성

변경 이력:
[날짜] [작성자] | 템플릿 생성
  - DictionaryBuilder 클래스 스켈레톤
  - build(), extract_metadata(), collect_samples() 구조
"""

import json
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class DictionaryBuilder:
    """
    스키마 딕셔너리 생성기

    PostgreSQL information_schema에서 메타데이터 추출
    """

    def __init__(self, config):
        """
        초기화

        Args:
            config: Config 객체
        """
        self.config = config
        self.connection = None

    def build(self) -> Dict[str, Any]:
        """
        딕셔너리 생성

        Returns:
            Dict: {
                "users.user_id": {
                    "table": "users",
                    "column": "user_id",
                    "data_type": "integer",
                    ...
                },
                ...
            }

        TODO:
        1. DB 연결 (Secrets Manager 사용)
        2. extract_metadata() 호출
        3. collect_samples() 호출
        4. generate_cast_hints() 호출
        5. save_to_file() 호출
        6. 반환
        """
        # TODO: 구현
        pass

    def extract_metadata(self) -> List[Dict]:
        """
        메타데이터 추출

        information_schema.columns 조회

        Returns:
            List[Dict]: [
                {
                    "table_name": "users",
                    "column_name": "user_id",
                    "data_type": "integer",
                    "is_nullable": "NO",
                    ...
                },
                ...
            ]

        TODO:
        1. SELECT table_name, column_name, data_type, ...
           FROM information_schema.columns
           WHERE table_schema = ?
        2. 결과 리스트로 반환
        """
        # TODO: 구현
        pass

    def collect_samples(self, metadata: List[Dict]) -> Dict[str, Any]:
        """
        샘플 데이터 수집

        각 테이블에서 LIMIT 1로 샘플 조회

        Args:
            metadata: extract_metadata() 결과

        Returns:
            Dict: 테이블별 샘플 데이터

        TODO:
        1. 테이블별로 SELECT * FROM table LIMIT 1
        2. 결과를 딕셔너리로 변환
        """
        # TODO: 구현
        pass

    def generate_cast_hints(
        self, metadata: List[Dict], samples: Dict
    ) -> Dict[str, Any]:
        """
        타입별 캐스팅 힌트 생성

        Args:
            metadata: 메타데이터
            samples: 샘플 데이터

        Returns:
            Dict: {
                "users.user_id": {
                    "table": "users",
                    "column": "user_id",
                    "data_type": "integer",
                    "sample_value": 12345,
                    "cast_hint": {
                        "needs_cast_from_string": true,
                        "cast_syntax": "::INTEGER"
                    }
                },
                ...
            }

        TODO:
        1. 각 컬럼에 대해 타입 분석
        2. integer, bigint, numeric → needs_cast_from_string: true
        3. character(n) → needs_trim: true
        4. timestamp, date → 날짜 캐스팅 문법
        """
        # TODO: 구현
        pass

    def save_to_file(self, dictionary: Dict[str, Any], file_path: str):
        """
        딕셔너리를 파일로 저장

        Args:
            dictionary: 생성된 딕셔너리
            file_path: 저장 경로

        TODO:
        1. JSON으로 직렬화
        2. 파일에 저장 (indent=2)
        """
        # TODO: 구현
        pass
