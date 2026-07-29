"""
SQL 크기/복잡도 분석 모듈

SQL 조각의 문자 수, 토큰 추정치, 복잡도를 산출하고 변환 전략을 분류한다.
LLM 토큰 제한 대응(청킹/수동 검토)의 판단 근거를 제공한다.

중요: 정규식으로 SQL을 파싱하지 않는다 (15-coding-guidelines.md 하드 룰).
      JOIN/<if>/<choose> 등은 대소문자 정규화 후 단순 부분문자열 카운팅으로만 센다.
      의미 단위 SQL 분할(청킹)은 이 모듈의 책임이 아니며, 변환기 단계에서
      구조 기반(비정규식) 방식으로 별도 처리한다.

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - SqlAnalyzer 구현: analyze/classify_complexity/select_conversion_strategy
  - 복잡도 = JOIN + <if>*2 + <choose>*3 + <foreach>*2 (단순 카운팅)
"""

import logging
from typing import Any, Dict

from oma.utils.config import Config

logger = logging.getLogger(__name__)

# 토큰 추정: 대략 3 char = 1 token
_CHARS_PER_TOKEN = 3

# 복잡도 분류 임계값
_COMPLEXITY_SIMPLE_MAX = 10
_COMPLEXITY_MODERATE_MAX = 30
_COMPLEXITY_COMPLEX_MAX = 100

# 복잡도 레벨 상수
LEVEL_SIMPLE = "simple"
LEVEL_MODERATE = "moderate"
LEVEL_COMPLEX = "complex"
LEVEL_VERY_COMPLEX = "very_complex"

# 변환 전략 상수
STRATEGY_STANDARD = "standard"
STRATEGY_STANDARD_COMPRESSED = "standard_with_compression"
STRATEGY_CHUNKED = "chunked"
STRATEGY_MANUAL_REVIEW = "manual_review"

# 기본 대용량 임계값 (문자 수)
_DEFAULT_LARGE_THRESHOLD = 50000


class SqlAnalyzer:
    """
    SQL 크기 및 복잡도 분석기

    Attributes:
        config: Config 객체
        large_threshold: 대용량 판정 문자 수 임계값
    """

    def __init__(self, config: Config) -> None:
        """
        초기화

        Args:
            config: Config 객체
        """
        self.config = config
        self.large_threshold = config.get_int(
            "LLM_LARGE_SQL_THRESHOLD", _DEFAULT_LARGE_THRESHOLD
        )

    def analyze(self, sql_content: str) -> Dict[str, Any]:
        """
        SQL 조각의 크기/복잡도를 분석한다.

        Args:
            sql_content: SQL(또는 매퍼 조각) 문자열

        Returns:
            {char_count, token_estimate, is_large, join_count, if_count,
             choose_count, foreach_count, complexity, complexity_level, strategy}
        """
        char_count = len(sql_content)
        token_estimate = char_count // _CHARS_PER_TOKEN

        upper = sql_content.upper()
        join_count = upper.count("JOIN")
        # MyBatis 동적 태그는 원본 대소문자 그대로 카운팅 (여는 태그 기준)
        if_count = sql_content.count("<if")
        choose_count = sql_content.count("<choose")
        foreach_count = sql_content.count("<foreach")

        complexity = (
            join_count
            + if_count * 2
            + choose_count * 3
            + foreach_count * 2
        )
        level = self.classify_complexity(complexity)
        is_large = char_count > self.large_threshold

        analysis = {
            "char_count": char_count,
            "token_estimate": token_estimate,
            "is_large": is_large,
            "join_count": join_count,
            "if_count": if_count,
            "choose_count": choose_count,
            "foreach_count": foreach_count,
            "complexity": complexity,
            "complexity_level": level,
        }
        analysis["strategy"] = self.select_conversion_strategy(analysis)
        return analysis

    @staticmethod
    def classify_complexity(score: int) -> str:
        """
        복잡도 점수를 레벨로 분류한다.

        Args:
            score: 복잡도 점수

        Returns:
            'simple' | 'moderate' | 'complex' | 'very_complex'
        """
        if score < _COMPLEXITY_SIMPLE_MAX:
            return LEVEL_SIMPLE
        if score < _COMPLEXITY_MODERATE_MAX:
            return LEVEL_MODERATE
        if score < _COMPLEXITY_COMPLEX_MAX:
            return LEVEL_COMPLEX
        return LEVEL_VERY_COMPLEX

    @staticmethod
    def select_conversion_strategy(analysis: Dict[str, Any]) -> str:
        """
        크기/복잡도에 따라 변환 전략을 선택한다.

        - 크지 않음 → standard
        - 크지만 단순/보통 → standard_with_compression
        - 크고 복잡 → chunked
        - 크고 매우 복잡 → manual_review

        Args:
            analysis: analyze() 결과 (strategy 제외)

        Returns:
            전략 문자열
        """
        if not analysis["is_large"]:
            return STRATEGY_STANDARD

        level = analysis["complexity_level"]
        if level in (LEVEL_SIMPLE, LEVEL_MODERATE):
            return STRATEGY_STANDARD_COMPRESSED
        if level == LEVEL_COMPLEX:
            return STRATEGY_CHUNKED
        return STRATEGY_MANUAL_REVIEW
