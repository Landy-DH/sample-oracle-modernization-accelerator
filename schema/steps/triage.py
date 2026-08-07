"""
변환대상 판별 스텝 (2차)

DMS SC 산출물의 스키마 노드 통계(Schemas.<SCHEMA>)를 파싱하여
LLM 재생성이 필요한 오브젝트를 가려낸다.

판별 기준(사용자 확정):
  LLM 대상 = 오브젝트에 다음 중 하나라도 해당
    (1) statistic.countErrorNodes > 0  (변환 실패 노드 존재)
    (2) statistic.messageActions 중 CRITICAL severity 코드가 붙음
        (severity 는 action-items 사전(-aid)의 severityType 로 판정)

산출물 구조(실측):
  content.treeNodeStatistics : 오브젝트 트리(재귀). 각 노드 statistic 에
    objectType, countErrorNodes, messageActions[{code, nodeName}] 포함.
  content.actionItemsDescriptors / -aid 파일 : code → {severityType, topic, ...}

변경 이력:
2026-08-05 | OMA Team | 초기 생성
  - Triage.select_targets(): countErrorNodes>0 또는 CRITICAL 코드 보유 판별
"""

import json
import logging
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# LLM 대상으로 볼 오브젝트 타입(테이블/컬럼/제약/인덱스/시퀀스는 DMS DDL 신뢰)
_CODE_OBJECT_TYPES = {
    "PROCEDURE",
    "FUNCTION",
    "PACKAGE",
    "PACKAGE BODY",
    "TRIGGER",
    "TYPE",
    "TYPE BODY",
    "VIEW",
    "MATERIALIZED VIEW",
}


class TriageError(Exception):
    """변환대상 판별 오류."""


class Triage:
    """
    산출물 통계 기반 변환대상 판별기.

    Attributes:
        critical_only: CRITICAL severity 만 대상 근거로 인정할지 여부
        code_types_only: PL/SQL 계열 오브젝트 타입으로 제한할지 여부
    """

    def __init__(
        self,
        critical_only: bool = True,
        code_types_only: bool = True,
    ) -> None:
        """
        Args:
            critical_only: messageActions 판정 시 CRITICAL severity 만 인정
            code_types_only: 판별 대상을 PL/SQL 계열 타입으로 제한
                (테이블/인덱스 등 구조 오브젝트는 DMS DDL 로 처리)
        """
        self.critical_only = critical_only
        self.code_types_only = code_types_only

    def _load_severity_map(self, aid_path: Optional[str]) -> Dict[str, str]:
        """
        action-items 사전(-aid)에서 code → severityType 매핑을 만든다.

        Args:
            aid_path: -aid JSON 로컬 경로(없으면 빈 맵)

        Returns:
            {code: severityType}
        """
        if not aid_path:
            return {}
        try:
            with open(aid_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("aid 사전 로드 실패(%s): %s", aid_path, e)
            return {}
        sev: Dict[str, str] = {}
        if isinstance(data, dict):
            for code, desc in data.items():
                if isinstance(desc, dict):
                    sev[str(code)] = desc.get("severityType", "")
        return sev

    def _walk(self, node: Dict[str, Any]):
        """
        treeNodeStatistics 노드를 재귀 순회한다.

        Args:
            node: 트리 노드

        Yields:
            각 노드(dict)
        """
        yield node
        for child in node.get("children", []) or []:
            yield from self._walk(child)

    def select_targets(
        self,
        schema_stats_path: str,
        aid_path: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        LLM 재생성 대상 오브젝트 목록을 반환한다.

        Args:
            schema_stats_path: Schemas.<SCHEMA> 통계 JSON 로컬 경로
            aid_path: action-items 사전(-aid) 로컬 경로(severity 판정용)

        Returns:
            [{"object_type", "object_name", "reasons": [...],
              "error_nodes": int, "critical_codes": [...]}]

        Raises:
            TriageError: 통계 파일 로드 실패 시
        """
        try:
            with open(schema_stats_path, "r", encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            raise TriageError(f"통계 파일 로드 실패({schema_stats_path}): {e}") from e

        content = doc.get("content", doc)
        roots = content.get("treeNodeStatistics", [])
        severity_map = self._load_severity_map(aid_path)

        targets: List[Dict[str, Any]] = []
        for root in roots:
            for node in self._walk(root):
                stat = node.get("statistic", {}) or {}
                obj_type = stat.get("objectType")
                if not obj_type:
                    continue
                if self.code_types_only and obj_type not in _CODE_OBJECT_TYPES:
                    continue

                reasons: List[str] = []

                # 기준 (1): 변환 실패 노드
                err = stat.get("countErrorNodes")
                error_nodes = int(err) if err not in (None, "") else 0
                if error_nodes > 0:
                    reasons.append(f"countErrorNodes={error_nodes}")

                # 기준 (2): CRITICAL 액션아이템 코드
                critical_codes: Set[str] = set()
                for ma in stat.get("messageActions", []) or []:
                    code = str(ma.get("code", ""))
                    if not code:
                        continue
                    sev = severity_map.get(code, "")
                    if not self.critical_only or sev == "CRITICAL":
                        if sev == "CRITICAL":
                            critical_codes.add(code)
                if critical_codes:
                    reasons.append(
                        "critical_codes=" + ",".join(sorted(critical_codes))
                    )

                if reasons:
                    name = node.get("name", "").split(".")[-1]
                    targets.append(
                        {
                            "object_type": obj_type,
                            "object_name": name,
                            "reasons": reasons,
                            "error_nodes": error_nodes,
                            "critical_codes": sorted(critical_codes),
                        }
                    )

        logger.info(
            "변환대상 판별: %d개 (기준: countErrorNodes>0 또는 CRITICAL)",
            len(targets),
        )
        for t in targets:
            logger.info(
                "  - %s %s (%s)",
                t["object_type"],
                t["object_name"],
                "; ".join(t["reasons"]),
            )
        return targets
