"""
OMA 매퍼 분할 패키지

MyBatis 매퍼 XML을 SQL ID별 조각으로 분할한다.

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - MapperSplitter, Fragment, MapperSplitResult export
"""

from oma.fragmenter.splitter import Fragment, MapperSplitResult, MapperSplitter

__all__ = ["MapperSplitter", "Fragment", "MapperSplitResult"]
