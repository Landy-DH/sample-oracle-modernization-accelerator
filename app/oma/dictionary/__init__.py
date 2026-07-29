"""
OMA 스키마 딕셔너리 패키지

타겟 DB 메타데이터 기반 딕셔너리 생성(builder)과 조회(loader)를 제공한다.

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - DictionaryBuilder, DictionaryLoader export
"""

from oma.dictionary.builder import DictionaryBuilder
from oma.dictionary.loader import DictionaryLoader

__all__ = ["DictionaryBuilder", "DictionaryLoader"]
