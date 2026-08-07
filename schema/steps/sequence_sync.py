"""
시퀀스 현재값 동기화 스텝 (2차)

DMS SC 가 생성한 타겟 시퀀스는 Oracle "생성 시점" START 값만 반영하므로,
운영 중 증가한 현재값이 반영되지 않는다. 소스(Oracle)의 현재값을 조회해
타겟(PostgreSQL) 시퀀스를 setval 로 맞춘다.

값 기준:
  - Oracle ALL_SEQUENCES.LAST_NUMBER 는 캐시를 반영한 "다음 할당 경계" 값이다
    (캐시 사용 시 실제 현재값보다 최대 cache_size 만큼 크다).
  - 충돌 방지를 위해 이 값을 타겟의 "다음 nextval 결과"로 설정한다:
      SELECT setval('<schema>.<seq>', <last_number>, false)
    → 다음 nextval 이 last_number 를 반환(중복 없음, 일부 건너뜀 허용).
  - 타겟에 존재하는 시퀀스만 대상(DDL 적용 이후 실행 전제).

파라미터 스타일: Oracle=:name, PostgreSQL=%s (드라이버별로 다름).

변경 이력:
2026-08-05 | OMA Team | 초기 생성
  - SequenceSync.sync(): 소스 last_number 조회 → 타겟 setval(.., false)
2026-08-05 | OMA Team | 순환 시퀀스 경계 초과 처리
  - 타겟 [min,max] 로 setval 값 클램프(max 초과 시 min 으로)
  - 원인: CYCLE 시퀀스가 랩된 last_number(예: max=999에 1000)를
    그대로 setval → "value out of bounds" 로 실패
  - pg_sequences 에서 min_value/max_value 조회, 상태 SYNCED_CLAMPED 구분
"""

import logging
from typing import Any, Dict, List

from db.executor import DBExecutor, ExecutorError

logger = logging.getLogger(__name__)

# 소스 시퀀스 현재값 조회(Oracle)
_SRC_SQL = (
    "SELECT sequence_name, last_number, increment_by "
    "FROM all_sequences WHERE sequence_owner = :owner"
)
# 타겟 존재 시퀀스 조회(PostgreSQL) - 경계값(min/max)까지 조회해 클램프에 사용
_TGT_LIST_SQL = (
    "SELECT sequencename, min_value, max_value "
    "FROM pg_sequences WHERE schemaname = %s"
)


class SequenceSyncError(Exception):
    """시퀀스 동기화 오류."""


class SequenceSync:
    """
    소스→타겟 시퀀스 현재값 동기화기.

    Attributes:
        executor: source/target 이 등록된 DBExecutor
        source_schema: Oracle 스키마(대문자)
        target_schema: PostgreSQL 스키마(소문자)
    """

    def __init__(
        self,
        executor: DBExecutor,
        source_schema: str,
        target_schema: str,
        source_label: str = "source",
        target_label: str = "target",
    ) -> None:
        """
        Args:
            executor: DBExecutor(source/target 등록되어 있어야 함)
            source_schema: Oracle 스키마명(대문자)
            target_schema: PostgreSQL 스키마명(소문자)
            source_label: 소스 endpoint 라벨
            target_label: 타겟 endpoint 라벨
        """
        self.executor = executor
        self.source_schema = source_schema
        self.target_schema = target_schema
        self.source_label = source_label
        self.target_label = target_label

    def sync(self) -> Dict[str, Any]:
        """
        소스 현재값으로 타겟 시퀀스를 동기화한다.

        Returns:
            {
              "source_count", "target_count", "synced", "missing_in_target",
              "failed", "details": [{"sequence","last_number","status"}]
            }

        Raises:
            SequenceSyncError: 소스/타겟 조회 실패 시
        """
        try:
            src_rows = self.executor.query(
                self.source_label, _SRC_SQL, [self.source_schema.upper()]
            )
        except ExecutorError as e:
            raise SequenceSyncError(f"소스 시퀀스 조회 실패: {e}") from e
        try:
            tgt_rows = self.executor.query(
                self.target_label, _TGT_LIST_SQL, [self.target_schema.lower()]
            )
        except ExecutorError as e:
            raise SequenceSyncError(f"타겟 시퀀스 조회 실패: {e}") from e

        # 타겟 존재 시퀀스명(소문자) → 경계값(min/max) 매핑
        target_bounds = {
            r["sequencename"].lower(): (r["min_value"], r["max_value"])
            for r in tgt_rows
        }

        synced = 0
        missing = 0
        failed = 0
        details: List[Dict[str, Any]] = []

        for row in src_rows:
            seq_name = row["SEQUENCE_NAME"]
            last_number = row["LAST_NUMBER"]
            tgt_name = seq_name.lower()

            if tgt_name not in target_bounds:
                missing += 1
                details.append(
                    {
                        "sequence": seq_name,
                        "last_number": last_number,
                        "status": "MISSING_IN_TARGET",
                    }
                )
                continue

            # 타겟 시퀀스 경계[min,max]로 클램프한다.
            #   - 순환(CYCLE) 시퀀스는 소스 LAST_NUMBER 가 max 를 초과한
            #     "랩(wrap) 직후" 상태(예: max=999, last_number=1000)일 수 있다.
            #     이 값을 그대로 setval 하면 범위 초과로 거부되므로,
            #     max 초과 시 다음 값이 min 부터 시작하도록 min 으로 맞춘다.
            #   - min 미만도 방어적으로 min 으로 올린다.
            tgt_min, tgt_max = target_bounds[tgt_name]
            set_value = int(last_number)
            clamped = False
            if set_value > int(tgt_max):
                set_value = int(tgt_min)
                clamped = True
            elif set_value < int(tgt_min):
                set_value = int(tgt_min)
                clamped = True

            # setval(<schema>.<seq>, <value>, false) → 다음 nextval = value
            # 식별자는 파라미터 바인딩 불가 → 안전한 이름만 조립(따옴표로 감쌈)
            qualified = f'"{self.target_schema.lower()}"."{tgt_name}"'
            setval_sql = "SELECT setval(%s, %s, false)"
            try:
                self.executor.query(
                    self.target_label, setval_sql, [qualified, set_value]
                )
                synced += 1
                status = "SYNCED_CLAMPED" if clamped else "SYNCED"
                details.append(
                    {
                        "sequence": seq_name,
                        "last_number": set_value,
                        "status": status,
                    }
                )
            except ExecutorError as e:
                failed += 1
                details.append(
                    {
                        "sequence": seq_name,
                        "last_number": last_number,
                        "status": f"FAILED: {str(e)[:150]}",
                    }
                )

        result = {
            "source_count": len(src_rows),
            "target_count": len(target_bounds),
            "synced": synced,
            "missing_in_target": missing,
            "failed": failed,
            "details": details,
        }
        logger.info(
            "시퀀스 동기화: 소스=%d 타겟=%d 동기화=%d 누락=%d 실패=%d",
            len(src_rows),
            len(target_bounds),
            synced,
            missing,
            failed,
        )
        for d in details:
            logger.info("  %s → %s (%s)", d["sequence"], d["last_number"], d["status"])
        return result
