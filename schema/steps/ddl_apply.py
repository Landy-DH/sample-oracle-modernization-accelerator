"""
DDL 타겟 적용 스텝 (2차 시작점)

DMS SC 가 생성한 변환 DDL(.sql)을 문장 단위로 분할하여 타겟 PostgreSQL 에
적용한다. 이로써 타겟 DB 에 오브젝트(테이블/인덱스/시퀀스/제약/프로시저 등)를
생성한다. 프로시저 등 로직 미완성 오브젝트는 이후 LLM 재생성으로 덮어쓴다.

용도(중요):
  1차 변환 DDL(DMS SC 산출물 전체)은 DMS SC 의 export-to-target(apply changes)
  으로 반영한다. 본 모듈은 **2차 LLM 이 생성한 단일 오브젝트 구문**을 타겟에
  반영하는 용도다(전체 스크립트 일괄 반영용 아님).

특징:
  - $$ dollar-quote 블록을 인식해 세미콜론 분리 오류를 피한다.
  - "already exists"/"duplicate" 오류는 idempotent skip(재실행 안전).
  - 실패 문장은 수집하여 반환(중단하지 않음). commit 은 문장 단위.
  - DBExecutor(target) 를 통해 실행(psycopg2).

정규식으로 SQL 을 파싱하지 않는다(단순 라인 스캔 + $$ 토글).

변경 이력:
2026-08-05 | OMA Team | 초기 생성
  - split_statements($$ 인식), apply(): 문장별 실행/skip/실패 수집
2026-08-05 | OMA Team | 용도 명확화
  - 전체 스크립트 반영은 DMS export-to-target 담당. 본 모듈은 LLM 생성 구문 전용
"""

import logging
from typing import Any, Dict, List

from db.executor import DBExecutor, ExecutorError

logger = logging.getLogger(__name__)

# idempotent skip 대상 오류 키워드(소문자) - 오브젝트 이미 존재
_SKIP_MARKERS = ("already exists", "duplicate")


class DDLApplyError(Exception):
    """DDL 적용 오류."""


def split_statements(ddl: str) -> List[str]:
    """
    DDL 텍스트를 개별 문장으로 분할한다($$ dollar-quote 인식).

    Args:
        ddl: 전체 DDL 텍스트

    Returns:
        문장 리스트(주석/빈 문장 제외 전 단계, 세미콜론 기준)
    """
    statements: List[str] = []
    current: List[str] = []
    in_dollar = False

    for line in ddl.split("\n"):
        stripped = line.strip()
        # $$ 출현 횟수가 홀수면 블록 토글
        if stripped.count("$$") % 2 == 1:
            in_dollar = not in_dollar
        current.append(line)
        if not in_dollar and stripped.endswith(";"):
            stmt = "\n".join(current).strip()
            if stmt and stmt != ";":
                statements.append(stmt)
            current = []

    if current:
        stmt = "\n".join(current).strip()
        if stmt and stmt != ";":
            statements.append(stmt)
    return statements


class DDLApplier:
    """
    변환 DDL 타겟 적용기.

    Attributes:
        executor: 타겟이 등록된 DBExecutor
        target_label: 타겟 endpoint 라벨
    """

    def __init__(self, executor: DBExecutor, target_label: str = "target") -> None:
        """
        Args:
            executor: DBExecutor(target endpoint 등록되어 있어야 함)
            target_label: 타겟 endpoint 라벨
        """
        self.executor = executor
        self.target_label = target_label

    @staticmethod
    def _is_skippable(error_msg: str) -> bool:
        """
        idempotent skip 대상 오류인지 판정한다.

        Args:
            error_msg: 오류 메시지

        Returns:
            already exists/duplicate 계열이면 True
        """
        low = error_msg.lower()
        return any(m in low for m in _SKIP_MARKERS)

    def apply_file(self, ddl_sql_path: str) -> Dict[str, Any]:
        """
        DDL 파일을 읽어 타겟에 적용한다.

        Args:
            ddl_sql_path: 변환 DDL(.sql) 로컬 경로

        Returns:
            적용 결과 요약

        Raises:
            DDLApplyError: 파일 읽기 실패 시
        """
        try:
            with open(ddl_sql_path, "r", encoding="utf-8", errors="replace") as f:
                ddl = f.read()
        except OSError as e:
            raise DDLApplyError(f"DDL 파일 읽기 실패({ddl_sql_path}): {e}") from e
        return self.apply_text(ddl)

    def apply_text(self, ddl: str) -> Dict[str, Any]:
        """
        DDL 텍스트를 문장 단위로 타겟에 적용한다.

        Args:
            ddl: DDL 전체 텍스트

        Returns:
            {
              "total", "applied", "skipped", "failed",
              "failed_statements": [{"stmt": <앞 200자>, "error": ...}],
            }
        """
        statements = split_statements(ddl)
        applied = 0
        skipped = 0
        failed_statements: List[Dict[str, str]] = []

        for stmt in statements:
            s = stmt.strip()
            if not s or s.startswith("--"):
                continue
            try:
                self.executor.execute(self.target_label, s)
                applied += 1
            except ExecutorError as e:
                msg = str(e)
                if self._is_skippable(msg):
                    skipped += 1
                else:
                    failed_statements.append({"stmt": s[:200], "error": msg[:300]})

        result = {
            "total": len(statements),
            "applied": applied,
            "skipped": skipped,
            "failed": len(failed_statements),
            "failed_statements": failed_statements,
        }
        logger.info(
            "DDL 적용: total=%d applied=%d skipped=%d failed=%d",
            result["total"],
            applied,
            skipped,
            result["failed"],
        )
        for f in failed_statements:
            logger.warning("  실패: %s ... => %s", f["stmt"][:80], f["error"][:120])
        return result
