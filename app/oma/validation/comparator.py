"""
검증 결과 비교 모듈

Java Validator가 반환한 소스(Oracle)/타겟(PostgreSQL) 실행 결과를 비교해
일치 여부와 실패 유형을 판정한다.

비교 항목 (우선순위):
  1. 실행 성공/스킵 여부 (한쪽만 실패 → 판정 불가)
  2. 행 수 (SELECT) 또는 영향 행 수 (DML)
  3. 컬럼 집합 (대소문자 무시)
  4. 값 (행별/컬럼별) — 완전 일치만 통과 (tolerance 없음)

원칙: 소스/타겟 결과는 완벽히 일치해야 한다. 근사 비교(tolerance)를 허용하지 않으며,
      CHAR 패딩 등 공백 차이도 불일치로 판정한다 (변환 오류를 놓치지 않기 위함).

실패 유형: execution_error / row_count_mismatch / column_mismatch /
          value_mismatch / skipped

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - ResultComparator.compare(): 성공/행수/컬럼/값 비교, 실패유형·심각도 분류
2026-07-27 | OMA Team | tolerance 제거 - 완전 일치 원칙
  - 숫자 근사 비교/공백 strip 제거. int/float 정확 동치만 허용
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 값 불일치 상세 최대 기록 수
_MAX_VALUE_DIFFS = 20

# 실패 유형 상수
FAIL_EXECUTION_ERROR = "execution_error"
FAIL_ROW_COUNT = "row_count_mismatch"
FAIL_COLUMN = "column_mismatch"
FAIL_VALUE = "value_mismatch"
STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


@dataclass
class Comparison:
    """단일 TC 비교 결과"""

    tc_id: str
    status: str  # passed | failed | skipped
    matched: bool = False
    failure_type: Optional[str] = None
    severity: Optional[str] = None
    row_count_matched: bool = True
    columns_matched: bool = True
    values_matched: bool = True
    source_rows: int = 0
    target_rows: int = 0
    differences: List[Dict[str, Any]] = field(default_factory=list)
    value_differences: List[Dict[str, Any]] = field(default_factory=list)
    note: Optional[str] = None


class ResultComparator:
    """
    소스/타겟 실행 결과 비교기 (완전 일치 원칙, tolerance 없음)
    """

    def __init__(self) -> None:
        """초기화 (설정 없음 — 항상 엄격 비교)."""

    def compare(self, validation_result: Dict[str, Any]) -> Comparison:
        """
        Java ValidationResult(dict)를 비교해 Comparison을 만든다.

        Args:
            validation_result: {tcId, status, sourceResult, targetResult}

        Returns:
            Comparison
        """
        tc_id = validation_result.get("tcId", "unknown")

        # Java 단계에서 이미 error 처리된 경우
        if validation_result.get("status") == "error":
            return Comparison(
                tc_id=tc_id, status=STATUS_FAILED,
                failure_type=FAIL_EXECUTION_ERROR, severity="high",
                matched=False,
                note=validation_result.get("errorMessage", "extraction/execution error"),
            )

        source = validation_result.get("sourceResult") or {}
        target = validation_result.get("targetResult") or {}

        # 스킵(프로시저 등): 양쪽 다 스킵이면 skipped
        if source.get("skipped") or target.get("skipped"):
            return Comparison(
                tc_id=tc_id, status=STATUS_SKIPPED, matched=False,
                note=source.get("skipReason") or target.get("skipReason"),
            )

        # 실행 성공 여부
        if not source.get("success") or not target.get("success"):
            return Comparison(
                tc_id=tc_id, status=STATUS_FAILED,
                failure_type=FAIL_EXECUTION_ERROR, severity="high", matched=False,
                source_rows=source.get("rowCount", 0),
                target_rows=target.get("rowCount", 0),
                note=self._exec_error_note(source, target),
            )

        return self._compare_success(tc_id, source, target)

    def _compare_success(
        self, tc_id: str, source: Dict[str, Any], target: Dict[str, Any]
    ) -> Comparison:
        """양쪽 실행이 성공한 경우의 상세 비교."""
        comp = Comparison(
            tc_id=tc_id, status=STATUS_PASSED, matched=True,
            source_rows=source.get("rowCount", 0),
            target_rows=target.get("rowCount", 0),
        )

        # 1. 행 수 비교
        if comp.source_rows != comp.target_rows:
            comp.row_count_matched = False
            comp.matched = False
            comp.failure_type = FAIL_ROW_COUNT
            comp.severity = "high"
            comp.differences.append({
                "type": FAIL_ROW_COUNT,
                "source": comp.source_rows,
                "target": comp.target_rows,
                "difference": comp.target_rows - comp.source_rows,
            })

        # 2. 컬럼 집합 비교 (대소문자 무시)
        src_cols = {c.lower() for c in source.get("columns", [])}
        tgt_cols = {c.lower() for c in target.get("columns", [])}
        if src_cols != tgt_cols:
            comp.columns_matched = False
            comp.matched = False
            if comp.failure_type is None:
                comp.failure_type = FAIL_COLUMN
                comp.severity = "critical"
            comp.differences.append({
                "type": FAIL_COLUMN,
                "missing_in_target": sorted(src_cols - tgt_cols),
                "extra_in_target": sorted(tgt_cols - src_cols),
            })

        # 3. 값 비교 (행별) — 컬럼이 일치할 때만 의미 있음
        if comp.columns_matched:
            self._compare_values(comp, source.get("rows", []), target.get("rows", []))

        # 샘플링된 경우 신뢰도 note
        if source.get("sampled") or target.get("sampled"):
            comp.note = "대용량 결과 - 샘플 비교 (신뢰도 medium)"

        if comp.matched:
            comp.status = STATUS_PASSED
        else:
            comp.status = STATUS_FAILED
        return comp

    def _compare_values(
        self, comp: Comparison,
        source_rows: List[Dict[str, Any]], target_rows: List[Dict[str, Any]],
    ) -> None:
        """행별/컬럼별 값을 비교해 불일치를 기록한다."""
        compare_count = min(len(source_rows), len(target_rows))
        mismatches = 0

        for idx in range(compare_count):
            s_row = source_rows[idx]
            t_row = target_rows[idx]
            # 컬럼명 대소문자 무시 매칭을 위해 소문자 키 맵 구성
            t_lower = {k.lower(): v for k, v in t_row.items()}
            for col, s_val in s_row.items():
                t_val = t_lower.get(col.lower())
                if not self._values_equal(s_val, t_val):
                    mismatches += 1
                    if len(comp.value_differences) < _MAX_VALUE_DIFFS:
                        comp.value_differences.append({
                            "row_index": idx,
                            "column": col,
                            "source_value": s_val,
                            "target_value": t_val,
                        })

        if mismatches > 0:
            comp.values_matched = False
            comp.matched = False
            if comp.failure_type is None:
                comp.failure_type = FAIL_VALUE
                comp.severity = "medium"

    def _values_equal(self, a: Any, b: Any) -> bool:
        """
        두 값이 완전히 동등한지 판단한다 (tolerance 없음, 엄격 비교).

        소스/타겟은 완벽히 일치해야 하며, 근사(tolerance)는 허용하지 않는다.
        - 숫자는 int/float 표현 차이(5 vs 5.0)만 동일로 보고, 값이 다르면 불일치
          (99.99 vs 99.989 → 불일치)
        - 문자열은 공백/패딩까지 그대로 비교 ("Y" vs "Y " → 불일치, CHAR 패딩 오류 탐지)
        - 타입이 달라도 값이 같으면(예: 5 vs "5") 표현 비교로 흡수하되, 근사는 없음

        Args:
            a: 소스 값
            b: 타겟 값

        Returns:
            완전 동등 여부
        """
        if a is None and b is None:
            return True
        if a is None or b is None:
            return False

        # 숫자 int/float 동치 (5 == 5.0) — 근사 아님, 정확 동치만
        a_num = self._to_exact_number(a)
        b_num = self._to_exact_number(b)
        if a_num is not None and b_num is not None:
            return a_num == b_num

        # 그 외에는 표현 문자열 그대로 비교 (strip 없음 — 패딩까지 엄격)
        return str(a) == str(b)

    @staticmethod
    def _to_exact_number(value: Any) -> Optional[float]:
        """
        int/float만 숫자로 취급해 반환한다 (문자열은 숫자로 강제 변환하지 않음).

        문자열 "5"와 숫자 5의 혼동을 막기 위해, 실제 숫자 타입만 대상으로 한다.
        bool은 숫자로 취급하지 않는다.
        """
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        return None

    @staticmethod
    def _exec_error_note(source: Dict[str, Any], target: Dict[str, Any]) -> str:
        """실행 실패 note를 구성한다 (어느 쪽 실패인지)."""
        parts = []
        if not source.get("success"):
            parts.append(f"source: {source.get('errorMessage', 'failed')}")
        if not target.get("success"):
            parts.append(f"target: {target.get('errorMessage', 'failed')}")
        return " | ".join(parts)

    @staticmethod
    def to_dict(comp: Comparison) -> Dict[str, Any]:
        """Comparison을 직렬화 가능한 dict로 변환한다."""
        return {
            "tc_id": comp.tc_id,
            "status": comp.status,
            "matched": comp.matched,
            "failure_type": comp.failure_type,
            "severity": comp.severity,
            "row_count_matched": comp.row_count_matched,
            "columns_matched": comp.columns_matched,
            "values_matched": comp.values_matched,
            "source_rows": comp.source_rows,
            "target_rows": comp.target_rows,
            "differences": comp.differences,
            "value_differences": comp.value_differences,
            "note": comp.note,
        }
