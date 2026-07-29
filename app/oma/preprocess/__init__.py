"""
OMA 전처리 패키지

변환 전 매퍼 복사본에 대한 전처리(특수 변수/OGNL 선치환)를 제공한다.

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - SpecialVariableSubstitutor export
"""

from oma.preprocess.special_variables import (
    SpecialVariableSubstitutor,
    SubstitutionResult,
)

__all__ = ["SpecialVariableSubstitutor", "SubstitutionResult"]
