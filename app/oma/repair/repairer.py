"""
조각 수정기(Repairer) — 검증 에러를 근거로 변환 조각을 LLM으로 최소 수정한다

유형 번호(repair-plan.json의 no)를 받아 그 유형의 영향 조각 각각에 대해
`원본 조각 + 현재 변환 조각 + 검증 에러`를 LLM에 주고 수정본을 받아
converted/<frag_id>.xml을 덮어쓴다. 수정 전 .bak 백업 + report.json에 이력을 남긴다.

설계: design/20-iterative-repair-loop.md §3

원칙(HARD RULE):
  - 함수 매핑을 하드코딩하지 않는다. 유형 힌트는 데이터로 주고 재작성은 모델이 판단.
  - sed 금지 — 조각 수정은 LLM 응답으로만. XML 검증은 lxml.
  - merge는 원본 스켈레톤 주도라 기존 조각 편집만 유효(신설 불가).

변경 이력:
2026-07-28 | OMA Team | 초기 생성
  - FragmentRepairer: repair_type(no)/repair_fragment(frag). LLM 최소수정,
    .bak 백업 + report.json repair_history 갱신, XML 유효성 검증.

2026-07-28 | OMA Team | 에러 없는 조각 제외 + 대표 참조 승격
  - 원인: 유형 B에 value/row_count 불일치(note 빈값)가 섞여 --limit 샘플이
    에러 없는 조각을 집어 전량 스킵. LLM 근거 없는 호출 낭비.
  - 수정: dedup 시 에러 있는 참조 우선 승격, note 빈 조각은 대상 제외하고
    제외 건수 로그. 실행에러 계열만 실제 수정.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from lxml import etree

from oma.converter.llm_client import LLMClient
from oma.repair.prompts import build_repair_prompt, build_repair_system_prompt
from oma.utils.exceptions import LLMError

logger = logging.getLogger(__name__)


class RepairOutcome:
    """단일 조각 수정 결과."""

    def __init__(
        self, frag_id: str, status: str, fix_summary: str = "",
        error: Optional[str] = None,
    ) -> None:
        self.frag_id = frag_id
        self.status = status  # 'repaired' | 'skipped' | 'failed'
        self.fix_summary = fix_summary
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frag_id": self.frag_id, "status": self.status,
            "fix_summary": self.fix_summary, "error": self.error,
        }


class FragmentRepairer:
    """
    변환 조각 수정기.

    Attributes:
        converted_dir: 변환 조각 디렉토리
        original_dir: 원본(선치환) 매퍼 디렉토리 (문맥 참조용)
        fragmented_dir: 분할 조각 디렉토리 (소스 조각 참조용)
        llm_client: LLMClient
    """

    def __init__(
        self, converted_dir: str, fragmented_dir: str,
        llm_client: LLMClient, source_type: str = "oracle",
        target_type: str = "postgres",
    ) -> None:
        """
        초기화.

        Args:
            converted_dir: 변환 조각 디렉토리(수정 대상)
            fragmented_dir: 분할(소스) 조각 디렉토리(원본 조각 참조)
            llm_client: LLM 클라이언트
            source_type: 소스 DB 타입(방언 프롬프트)
            target_type: 타겟 DB 타입(방언 프롬프트)
        """
        self.converted_dir = converted_dir
        self.fragmented_dir = fragmented_dir
        self.llm_client = llm_client
        self._system_prompt = build_repair_system_prompt(source_type, target_type)

    def repair_type(
        self, plan: Dict[str, Any], type_no: int, limit: Optional[int] = None,
    ) -> List[RepairOutcome]:
        """
        repair-plan의 특정 유형 번호에 속한 조각들을 수정한다.

        같은 frag_id가 여러 TC로 중복될 수 있으므로 조각 단위로 중복 제거한다.
        각 조각의 대표 에러는 해당 조각의 첫 에러를 쓴다.

        Args:
            plan: repair-plan dict
            type_no: 수정할 유형 번호(no)
            limit: 최대 조각 수(대화형 샘플 확인용). None이면 전체.

        Returns:
            RepairOutcome 리스트
        """
        target = next((t for t in plan["types"] if t["no"] == type_no), None)
        if target is None:
            raise ValueError(f"유형 번호 {type_no}가 repair-plan에 없습니다")
        if target["action"] != "repair":
            raise ValueError(
                f"유형 {type_no}({target['group']})는 repair 대상이 아닙니다 "
                f"(action={target['action']})"
            )

        # frag_id 단위 중복 제거. 같은 조각에 여러 TC가 있으면 에러 메시지가 있는
        # 참조를 대표로 승격한다(값/행수 불일치는 note가 비어 LLM 근거가 없음).
        by_frag: Dict[str, Dict[str, Any]] = {}
        for fr in target["fragments"]:
            fid = fr.get("frag_id")
            if not fid:
                continue
            prev = by_frag.get(fid)
            if prev is None or (
                not (prev.get("error") or "").strip()
                and (fr.get("error") or "").strip()
            ):
                by_frag[fid] = fr

        uniq = list(by_frag.values())
        # 에러 메시지 없는 조각은 조각-수정 대상이 아니다(값/행수 불일치 = 결과 검증
        # 문제라 SQL만 보고 못 고침). 제외 건수는 로그로 남긴다(무단 누락 금지).
        actionable = [f for f in uniq if (f.get("error") or "").strip()]
        skipped_no_error = len(uniq) - len(actionable)
        if skipped_no_error:
            logger.info(
                "유형 %d: 에러 메시지 없는 조각 %d개 제외(값/행수 불일치 등, "
                "조각 수정 부적합)", type_no, skipped_no_error,
            )

        frags = actionable
        if limit is not None:
            frags = frags[:limit]

        logger.info(
            "유형 %d(%s) 수정 시작: 수정 대상 %d/%d개%s",
            type_no, target["group"], len(frags), len(uniq),
            f" (limit={limit})" if limit else "",
        )
        outcomes: List[RepairOutcome] = []
        for fr in frags:
            outcomes.append(self.repair_fragment(fr))
        return outcomes

    def repair_fragment(self, frag: Dict[str, Any]) -> RepairOutcome:
        """
        단일 조각을 LLM으로 수정하고 저장한다.

        Args:
            frag: repair-plan의 조각 참조(frag_id/error 등 포함)

        Returns:
            RepairOutcome
        """
        frag_id = frag["frag_id"]
        converted_path = os.path.join(self.converted_dir, f"{frag_id}.xml")
        source_path = os.path.join(self.fragmented_dir, f"{frag_id}.xml")

        if not os.path.isfile(converted_path):
            return RepairOutcome(
                frag_id, "failed", error=f"변환 조각 없음: {converted_path}"
            )

        current_sql = self._read(converted_path)
        source_sql = self._read(source_path) if os.path.isfile(source_path) else ""
        error = frag.get("error", "")

        try:
            result = self._invoke_llm(source_sql, current_sql, error)
        except LLMError as e:
            logger.error("수정 LLM 실패: %s - %s", frag_id, e)
            return RepairOutcome(frag_id, "failed", error=str(e))

        fixed_sql = result.get("fixed_sql") or ""
        fix_summary = result.get("fix_summary", "")

        if not fixed_sql.strip():
            return RepairOutcome(
                frag_id, "skipped", fix_summary="LLM이 수정본을 반환하지 않음"
            )

        # XML 유효성 검증(정규식 아님, lxml)
        try:
            etree.fromstring(fixed_sql.encode("utf-8"), self._parser())
        except etree.XMLSyntaxError as e:
            logger.error("수정 결과 XML 오류: %s - %s", frag_id, e)
            return RepairOutcome(
                frag_id, "failed", error=f"수정 결과 XML 파싱 실패: {e}"
            )

        # 변경 없음이면 skip
        if fixed_sql.strip() == current_sql.strip():
            return RepairOutcome(
                frag_id, "skipped", fix_summary="변경 사항 없음"
            )

        # 백업 후 저장 + report 갱신
        self._backup(converted_path)
        self._write(converted_path, fixed_sql)
        self._update_report(frag_id, error, fix_summary)
        logger.info("수정 완료: %s - %s", frag_id, fix_summary[:80])
        return RepairOutcome(frag_id, "repaired", fix_summary=fix_summary)

    # ------------------------------------------------------------- 내부

    def _invoke_llm(
        self, source_sql: str, current_sql: str, error: str
    ) -> Dict[str, Any]:
        """LLM에 수정을 요청하고 JSON 결과를 반환한다."""
        prompt = build_repair_prompt(source_sql, current_sql, error)
        return self.llm_client.invoke_json(prompt, system=self._system_prompt)

    def _update_report(self, frag_id: str, error: str, fix_summary: str) -> None:
        """
        converted/<frag_id>.report.json에 repair 이력을 추가한다.

        기존 8필드 스키마를 보존하고 repair_history 필드만 확장한다. TC는 재생성하지
        않는다(조각 XML만 수정).
        """
        report_path = os.path.join(self.converted_dir, f"{frag_id}.report.json")
        report: Dict[str, Any] = {}
        if os.path.isfile(report_path):
            try:
                with open(report_path, "r", encoding="utf-8") as f:
                    report = json.load(f)
            except (OSError, json.JSONDecodeError):
                report = {}
        history = report.get("repair_history") or []
        history.append({
            "error": error[:300],
            "fix_summary": fix_summary,
            "backup": f"{frag_id}.xml.bak",
        })
        report["repair_history"] = history
        report["status"] = "repaired"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _parser() -> "etree.XMLParser":
        """조각 파싱용 안전 파서(외부 DTD 차단, CDATA 보존)."""
        return etree.XMLParser(
            no_network=True, load_dtd=False, resolve_entities=False,
            strip_cdata=False, remove_blank_text=False,
        )

    @staticmethod
    def _read(path: str) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def _write(path: str, content: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    @staticmethod
    def _backup(path: str) -> None:
        """수정 전 현재 변환본을 .bak로 백업한다(기존 .bak는 보존)."""
        bak = f"{path}.bak"
        if not os.path.isfile(bak):
            with open(path, "r", encoding="utf-8") as src:
                content = src.read()
            with open(bak, "w", encoding="utf-8") as dst:
                dst.write(content)
