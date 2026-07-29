"""
OMA 검증 패키지

변환된 SQL의 정확성을 검증한다. Java Validator(MyBatis BoundSql로 동적 SQL을
완성 → 소스/타겟 DB 실행)와 통신하고, 결과를 비교/리포트한다.

구성:
  java_bridge  - Python↔Java(JAR) subprocess/JSON 통신
  comparator   - 소스 vs 타겟 결과 비교 (완전 일치)
  reporter     - 검증 리포트 생성 (콘솔/JSON/CSV)
  orchestrator - 검증 전체 플로우 제어 (TC로드→검증→비교→리포트)

변경 이력:
2026-07-27 | OMA Team | 최초 패키지 설명 추가
2026-07-27 | OMA Team | Bridge/Comparator/Reporter/Orchestrator export
"""

from oma.validation.comparator import Comparison, ResultComparator
from oma.validation.java_bridge import JavaValidationBridge
from oma.validation.orchestrator import ValidationOrchestrator
from oma.validation.reporter import ValidationReporter

__all__ = [
    "JavaValidationBridge",
    "ResultComparator",
    "Comparison",
    "ValidationReporter",
    "ValidationOrchestrator",
]
