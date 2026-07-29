"""
실패 분석기 — 검증 결과를 오류유형으로 분류해 repair-plan을 만든다

입력: reports/validation-details.json (검증 상세), testcases/*.json (mapper/sql_id),
      fragmented/mapping.json (statement_type 조회)
출력: repair-plan.json (유형 번호 + 영향 조각 frag_id 리스트 + 대표 에러),
      failure-analysis.json (집계), failure-report.md (사람용 보고서)

설계: design/20-iterative-repair-loop.md §2

frag_id 구성 원칙(리뷰 반영):
  - (mapper, sql_id)는 tc_id 역파싱이 아니라 testcases/{tc_id}.json의 mapper/sql_id
    필드에서 직접 읽는다(언더스코어 조인 애매성 회피).
  - statement_type은 mapping.json에서 (mapper, sql_id)로 조회하되, 후보가 여럿이면
    실행가능 타입(select/insert/update/delete)을 우선한다(resultMap/select id 충돌 대응).

변경 이력:
2026-07-28 | OMA Team | 초기 생성
  - FailureAnalyzer: analyze() → RepairPlan(types[]) + 집계/보고서 렌더
  - TC json에서 mapper/sql_id 직접 로드, statement_type 실행가능 우선 해소
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from oma.repair import classifier

logger = logging.getLogger(__name__)

# 실행 가능한 statement 태그(같은 id 충돌 시 우선 선택)
_EXECUTABLE_TYPES = ("select", "insert", "update", "delete")


class FailureAnalyzer:
    """
    검증 실패를 오류유형으로 분류하고 repair-plan을 생성한다.

    Attributes:
        report_dir: 리포트 디렉토리(REPORT_DIR)
        testcase_dir: 테스트케이스 디렉토리(TESTCASE_DIR)
        mapping_path: fragmented/mapping.json 경로
    """

    def __init__(
        self, report_dir: str, testcase_dir: str, mapping_path: str
    ) -> None:
        """
        초기화.

        Args:
            report_dir: 리포트 디렉토리
            testcase_dir: 테스트케이스 디렉토리
            mapping_path: fragmented/mapping.json 경로
        """
        self.report_dir = report_dir
        self.testcase_dir = testcase_dir
        self.mapping_path = mapping_path
        self._type_index: Optional[Dict[Tuple[str, str], List[str]]] = None

    def analyze(self) -> Dict[str, Any]:
        """
        검증 상세를 읽어 repair-plan(dict)을 만든다.

        Returns:
            {"summary", "types": [...]} 형태의 repair-plan dict

        Raises:
            FileNotFoundError: validation-details.json이 없을 때
        """
        details_path = os.path.join(self.report_dir, "validation-details.json")
        if not os.path.isfile(details_path):
            raise FileNotFoundError(f"검증 상세가 없습니다: {details_path}")

        with open(details_path, "r", encoding="utf-8") as f:
            details = json.load(f)

        tcs = details.get("test_cases", [])
        total = len(tcs)
        fails = [t for t in tcs if t.get("status") == "failed"]

        # 그룹별로 영향 조각을 모은다
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for tc in fails:
            note = tc.get("note") or ""
            group, category = classifier.classify(note, tc.get("failure_type"))
            frag = self._build_fragment_ref(tc, category, note)
            groups.setdefault(group, []).append(frag)

        types = self._build_types(groups)
        plan = {
            "run_id": details.get("run_id"),
            "generated_from": "reports/validation-details.json",
            "summary": {
                "total": total,
                "passed": total - len(fails),
                "failed": len(fails),
            },
            "types": types,
        }
        return plan

    def _build_types(
        self, groups: Dict[str, List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """그룹별 조각 목록을 repair-plan의 types[]로 변환한다(안정 번호순)."""
        types: List[Dict[str, Any]] = []
        for group in classifier.GROUP_ORDER:
            frags = groups.get(group)
            if not frags:
                continue
            nature, action = classifier.GROUP_META[group]
            # 대표 카테고리/에러(최빈 카테고리)
            cat_counts: Dict[str, int] = {}
            for fr in frags:
                cat_counts[fr["category"]] = cat_counts.get(fr["category"], 0) + 1
            rep_category = max(cat_counts, key=cat_counts.get)
            rep_error = next(
                (fr["error"] for fr in frags if fr["category"] == rep_category
                 and fr.get("error")),
                "",
            )
            types.append({
                "no": classifier.category_number(group),
                "group": group,
                "nature": nature,
                "action": action,
                "count": len(frags),
                "category_breakdown": dict(
                    sorted(cat_counts.items(), key=lambda kv: -kv[1])
                ),
                "representative_error": rep_error[:200],
                "fragments": frags,
            })
        return types

    def _build_fragment_ref(
        self, tc: Dict[str, Any], category: str, note: str
    ) -> Dict[str, Any]:
        """
        실패 TC로부터 조각 참조(frag_id 포함)를 만든다.

        Args:
            tc: 검증 상세의 test_case 항목
            category: 분류된 카테고리
            note: 에러 메시지

        Returns:
            {mapper, sql_id, statement_type, frag_id, tc_id, category, error}
        """
        tc_id = tc.get("tc_id", "")
        mapper, sql_id = self._lookup_mapper_sqlid(tc_id, tc)
        stype = self._resolve_statement_type(mapper, sql_id)
        frag_id = (
            f"{mapper}__{stype}__{sql_id}"
            if mapper and stype and sql_id else None
        )
        return {
            "tc_id": tc_id,
            "mapper": mapper,
            "sql_id": sql_id,
            "statement_type": stype,
            "frag_id": frag_id,
            "category": category,
            "error": note[:300],
        }

    def _lookup_mapper_sqlid(
        self, tc_id: str, tc: Dict[str, Any]
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        (mapper, sql_id)를 얻는다. TC json의 필드를 우선, 없으면 상세 항목 폴백.

        tc_id 역파싱은 하지 않는다(언더스코어 조인 애매성).
        """
        # 1) 상세 항목 자체에 있으면 사용
        mapper = tc.get("mapper")
        sql_id = tc.get("sql_id")
        if mapper and sql_id:
            return mapper, sql_id
        # 2) testcases/{tc_id}.json에서 읽기(신뢰 소스)
        tc_path = os.path.join(self.testcase_dir, f"{tc_id}.json")
        if os.path.isfile(tc_path):
            try:
                with open(tc_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("mapper"), data.get("sql_id")
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("TC json 읽기 실패: %s - %s", tc_path, e)
        return mapper, sql_id

    def _resolve_statement_type(
        self, mapper: Optional[str], sql_id: Optional[str]
    ) -> Optional[str]:
        """
        mapping.json에서 (mapper, sql_id)의 statement_type을 얻는다.

        후보가 여럿이면(resultMap/select id 충돌) 실행가능 타입을 우선한다.
        실행가능 후보가 없으면 첫 후보를 반환(그룹 E로 별도 처리됨).
        """
        if not mapper or not sql_id:
            return None
        index = self._load_type_index()
        candidates = index.get((mapper, sql_id))
        if not candidates:
            return None
        for stype in candidates:
            if stype in _EXECUTABLE_TYPES:
                return stype
        return candidates[0]

    def _load_type_index(self) -> Dict[Tuple[str, str], List[str]]:
        """mapping.json을 (mapper, sql_id) → [statement_type,...]로 인덱싱(캐시)."""
        if self._type_index is not None:
            return self._type_index
        index: Dict[Tuple[str, str], List[str]] = {}
        if os.path.isfile(self.mapping_path):
            with open(self.mapping_path, "r", encoding="utf-8") as f:
                mapping = json.load(f)
            for info in mapping.get("mappers", {}).values():
                mname = info.get("mapper_name")
                for fr in info.get("fragments", []):
                    key = (mname, fr.get("sql_id"))
                    index.setdefault(key, []).append(fr.get("statement_type"))
        else:
            logger.warning("mapping.json 없음: %s", self.mapping_path)
        self._type_index = index
        return index

    # ------------------------------------------------------------- 렌더링

    @staticmethod
    def render_report(plan: Dict[str, Any]) -> str:
        """repair-plan을 사람용 마크다운 보고서로 렌더링한다."""
        s = plan["summary"]
        lines: List[str] = []
        a = lines.append
        a("# 검증 실패 오류유형 보고서 (repair-plan)")
        a("")
        a("## 전체 결과")
        a("")
        a("| 구분 | 건수 | 비율 |")
        a("|------|-----:|-----:|")
        tot = s["total"] or 1
        a(f"| 전체 TC | {s['total']} | 100% |")
        a(f"| ✅ 통과 | {s['passed']} | {s['passed']/tot*100:.1f}% |")
        a(f"| ❌ 실패 | {s['failed']} | {s['failed']/tot*100:.1f}% |")
        a("")
        a("## 오류유형 (번호 = 안정 식별자)")
        a("")
        a("| 번호 | 그룹 | 건수 | 성격 | 조치 | 대표 에러 |")
        a("|-----:|------|-----:|------|------|-----------|")
        for t in plan["types"]:
            err = (t["representative_error"] or "").replace("\n", " ")[:60]
            a(f"| {t['no']} | {t['group']} | {t['count']} | {t['nature']} "
              f"| {t['action']} | {err} |")
        a("")
        a("> `repair` 조치 유형은 `scripts/repair_type.py --type <번호>`로 수정. "
          "`none`(오탐)은 조치 불필요.")
        a("")
        a("## 유형별 영향 매퍼")
        a("")
        for t in plan["types"]:
            mappers: Dict[str, int] = {}
            for fr in t["fragments"]:
                m = fr.get("mapper") or "?"
                mappers[m] = mappers.get(m, 0) + 1
            top = ", ".join(
                f"{m}({c})"
                for m, c in sorted(mappers.items(), key=lambda kv: -kv[1])[:8]
            )
            a(f"- **{t['no']}. {t['group']}** ({t['count']}건): {top}")
        return "\n".join(lines)
