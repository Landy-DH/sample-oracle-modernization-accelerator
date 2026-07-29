"""
OMA (Oracle Migration Assistant)

Oracle/EDB/Tibero MyBatis 매퍼를 PostgreSQL/MySQL로 자동 변환하는 도구.

전체 파이프라인 (Phase 1-7):
  Dictionary(타겟 스키마 딕셔너리 생성) → Fragment(매퍼를 SQL ID별 조각으로 분할)
  → Convert(LLM 기반 구문/형변환 + TC 생성) → Merge(조각을 원본 구조로 재조립)
  → Validate(소스/타겟 실행 결과 비교) → Copy(타겟 워크스페이스로 반영)

하위 패키지:
  utils      - 설정/시크릿/로깅/예외 (공용 기반)
  plugins    - 소스/타겟 DB 연결 (Oracle/PostgreSQL, 팩토리)
  dictionary - 타겟 스키마 딕셔너리 생성/조회
  fragmenter - 매퍼 XML 분할
  converter  - LLM 변환, SQL 분석, 타입 캐스팅
  testcase   - 동적 SQL 테스트 케이스 생성
  merger     - 변환 조각 재조립
  validation - 변환 결과 검증 (Java 브리지 등)
  workflow   - 체크포인트 및 전체 플로우 오케스트레이션

변경 이력:
2026-07-27 | OMA Team | 최초 패키지 설명 추가
"""
