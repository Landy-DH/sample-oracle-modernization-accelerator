"""
OMA DB 플러그인 패키지

소스/타겟 DB 연결을 추상화한다. 팩토리로 DB 타입에 맞는 플러그인을 생성한다.

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - base(SourceDB/TargetDB), OracleSource, PostgresTarget, factory export

2026-07-28 | OMA Team | EPAS 소스 지원 (조합 B)
  - EpasSource export 추가
"""

from oma.plugins.base import BaseDB, SourceDB, TargetDB
from oma.plugins.factory import create_source, create_target
from oma.plugins.source_epas import EpasSource
from oma.plugins.source_oracle import OracleSource
from oma.plugins.target_postgres import PostgresTarget

__all__ = [
    "BaseDB",
    "SourceDB",
    "TargetDB",
    "EpasSource",
    "OracleSource",
    "PostgresTarget",
    "create_source",
    "create_target",
]
