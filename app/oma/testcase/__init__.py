"""
OMA 테스트 케이스 생성 패키지

동적 SQL 분기별 테스트 케이스를 생성한다.

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - TestCaseGenerator, TestCase export
"""

from oma.testcase.generator import TestCase, TestCaseGenerator

__all__ = ["TestCaseGenerator", "TestCase"]
