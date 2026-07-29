"""
OMA 사전 검증(Pre-flight) 패키지

변환/검증 전에 매퍼를 스캔해 자동 처리 불가·사전 설정 필요 항목을 검출하고,
각 이슈를 어디에 어떻게 반영할지 가이드/설정 스텁을 생성한다.

변경 이력:
2026-07-27 | OMA Team | 초기 생성 (MapperScanner, PreflightReport)
2026-07-28 | OMA Team | PreflightGuide 추가 (조치 가이드/설정 스텁 생성)
"""

from oma.preflight.guide import PreflightGuide
from oma.preflight.scanner import MapperScanner, PreflightReport

__all__ = ["MapperScanner", "PreflightReport", "PreflightGuide"]
