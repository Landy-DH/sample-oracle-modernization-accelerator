"""
DMS replication task 매핑/설정 빌더 (3차 full-load 보조)

table-mappings(선택 규칙 + 변형 규칙)과 replication task 설정을 JSON 으로
만든다. 순수 함수만 두어 dms_full_load 에서 재사용/테스트하기 쉽게 한다.

핵심: 소스 Oracle 은 오브젝트명이 대문자(MBR_B2B_MGR / TB_XXX / COL_XXX)이고
타겟 PostgreSQL(Aurora)은 소문자(mbr_b2b_mgr / tb_xxx / col_xxx)로 생성되므로,
schema/table/column 을 모두 소문자로 바꾸는 변형 규칙(convert-lowercase)을
기본 적용한다. 그렇지 않으면 DMS 가 대문자명으로 적재를 시도해 타겟과 불일치한다.

변경 이력:
2026-08-05 | OMA Team | 초기 생성(dms_full_load 에서 분리)
  - table_mappings(): selection + schema/table/column convert-lowercase 변형
  - task_settings(): full-load, TRUNCATE_BEFORE_LOAD
2026-08-05 | OMA Team | LobMaxSize 파라미터화(LOB truncation 대응)
  - 기본 32KB 는 대형 CLOB(수십~수백 KB)을 잘라 ORA-01406 유발 → 기본 1024KB,
    config(FULL_LOAD_LOB_MAX_KB)로 상향 가능
"""

import json
from typing import Any, Dict, List


def _selection_rule(schema: str, rule_id: str) -> Dict[str, Any]:
    """
    대상 스키마의 모든 테이블을 선택하는 selection 규칙을 만든다.

    Args:
        schema: 소스 스키마명(Oracle=대문자)
        rule_id: 규칙 id/name

    Returns:
        selection 규칙 dict
    """
    return {
        "rule-type": "selection",
        "rule-id": rule_id,
        "rule-name": rule_id,
        "object-locator": {"schema-name": schema, "table-name": "%"},
        "rule-action": "include",
        "filters": [],
    }


def _lowercase_rules(schema: str, start_id: int) -> List[Dict[str, Any]]:
    """
    schema/table/column 명을 소문자로 변환하는 transformation 규칙을 만든다.

    소스(대문자) → 타겟(소문자) 오브젝트명 정합을 위해 세 레벨 모두 변환한다.

    Args:
        schema: 소스 스키마명(Oracle=대문자)
        start_id: 변형 규칙 시작 id(이후 +1씩 증가)

    Returns:
        [schema, table, column] convert-lowercase 규칙 리스트
    """
    rules: List[Dict[str, Any]] = []

    # schema 레벨
    rules.append(
        {
            "rule-type": "transformation",
            "rule-id": str(start_id),
            "rule-name": str(start_id),
            "rule-target": "schema",
            "object-locator": {"schema-name": schema},
            "rule-action": "convert-lowercase",
        }
    )
    # table 레벨
    rules.append(
        {
            "rule-type": "transformation",
            "rule-id": str(start_id + 1),
            "rule-name": str(start_id + 1),
            "rule-target": "table",
            "object-locator": {"schema-name": schema, "table-name": "%"},
            "rule-action": "convert-lowercase",
        }
    )
    # column 레벨
    rules.append(
        {
            "rule-type": "transformation",
            "rule-id": str(start_id + 2),
            "rule-name": str(start_id + 2),
            "rule-target": "column",
            "object-locator": {
                "schema-name": schema,
                "table-name": "%",
                "column-name": "%",
            },
            "rule-action": "convert-lowercase",
        }
    )
    return rules


def table_mappings(schema: str, lowercase: bool = True) -> str:
    """
    table-mappings(JSON)을 만든다: 대상 스키마 전체 선택 + (옵션) 소문자 변형.

    Args:
        schema: 소스 스키마명(Oracle=대문자로 전달)
        lowercase: True 면 schema/table/column 소문자 변환 규칙 포함

    Returns:
        TableMappings JSON 문자열
    """
    rules: List[Dict[str, Any]] = [_selection_rule(schema, "1")]
    if lowercase:
        rules.extend(_lowercase_rules(schema, start_id=2))
    return json.dumps({"rules": rules})


def task_settings(lob_max_size_kb: int = 1024) -> str:
    """
    full-load 태스크 설정(JSON)을 만든다: TRUNCATE_BEFORE_LOAD.

    Args:
        lob_max_size_kb: Limited LOB 모드 최대 크기(KB). 이 크기를 넘는 LOB
            값은 잘린다. 소스 CLOB 실제 최대 길이보다 크게 잡아야 truncation
            (ORA-01406)으로 인한 테이블 적재 실패를 막을 수 있다.

    Returns:
        ReplicationTaskSettings JSON 문자열
    """
    return json.dumps(
        {
            "TargetMetadata": {
                # 타겟 스키마/제약은 1·2차에서 이미 생성됨 → 데이터만 적재
                "SupportLobs": True,
                "FullLobMode": False,
                "LobChunkSize": 64,
                "LimitedSizeLobMode": True,
                "LobMaxSize": lob_max_size_kb,
            },
            "FullLoadSettings": {
                # 재실행 안전: 적재 전 대상 테이블 행 truncate(스키마/제약 유지)
                "TargetTablePrepMode": "TRUNCATE_BEFORE_LOAD",
                "CreatePkAfterFullLoad": False,
                "StopTaskCachedChangesApplied": False,
                "StopTaskCachedChangesNotApplied": False,
                "MaxFullLoadSubTasks": 8,
                "TransactionConsistencyTimeout": 600,
                "CommitRate": 10000,
            },
            "Logging": {"EnableLogging": True},
        }
    )
