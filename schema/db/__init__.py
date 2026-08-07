"""
schema 단계 DB 접속 모듈 패키지

시크릿 기반 접속 전용 계층.
  - secrets.py    : Secrets Manager 조회(자격증명 이름 → dict)
  - connection.py : 시크릿 dict → DB 커넥션(oracle/postgres 드라이버 선택)
  - executor.py   : DBExecutor - 소스/타겟 구분 없이 쿼리 실행 공통 인터페이스

변경 이력:
2026-08-05 | OMA Team | 초기 생성
"""

from db.executor import DBExecutor, QueryResult
from db.secrets import SecretsManager, get_secret

__all__ = ["DBExecutor", "QueryResult", "SecretsManager", "get_secret"]
