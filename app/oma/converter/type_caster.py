"""
타입 캐스팅 적용 모듈

딕셔너리(cast_hint)에 근거해 MyBatis 바인드 변수(#{var})에 PostgreSQL 명시적
캐스팅(::INTEGER 등)을 결정론적으로 적용한다.

설계 원칙 (15-coding-guidelines.md 준수):
  - SQL을 정규식으로 파싱하지 않는다. "어느 #{var}가 어느 컬럼인지"의 매핑은
    상위 로직(LLM 변환 단계)이 제공하며, 이 모듈은 주어진 매핑에 대해 딕셔너리
    기반으로 정확한 캐스팅을 적용/검증한다 (검증 가능한 결정론적 엔진).
  - 문자열 치환은 정규식이 아닌 str 탐색 기반. 멱등성 보장(이미 캐스팅된 것 재적용 X).

주요 기능:
  - apply_bind_cast: 특정 바인드 변수(#{var})에 컬럼 타입에 맞는 캐스팅 추가
  - cast_for_column: 컬럼 딕셔너리 엔트리로부터 캐스팅 구문/경고 판단
  - build_type_casts: (bind_var -> column) 매핑으로 전체 캐스팅 계획/리포트 생성

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - TypeCaster 구현: cast_for_column/apply_bind_cast/build_type_casts
  - 멱등 캐스팅(::TYPE 중복 방지), CHAR(n) TRIM 경고, 미발견 컬럼 경고
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from oma.dictionary.loader import DictionaryLoader

logger = logging.getLogger(__name__)

# 캐스팅 불필요한 문자열 계열 타입
_NO_CAST_TYPES = frozenset(
    {"character varying", "varchar", "text", "json", "jsonb", "uuid"}
)
# 고정 길이 문자 타입 (CHAR): 캐스팅 불필요하나 TRIM/패딩 경고 대상
_FIXED_CHAR_TYPES = frozenset({"character", "char", "bpchar"})


@dataclass
class CastResult:
    """단일 바인드 변수 캐스팅 판단 결과"""

    variable: str
    column: Optional[str]
    column_type: Optional[str]
    cast_applied: Optional[str]  # 적용된 캐스팅 구문(::TYPE) 또는 None
    reason: str
    warning: Optional[str] = None


@dataclass
class TypeCastReport:
    """전체 캐스팅 적용 리포트"""

    casts: List[CastResult] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class TypeCaster:
    """
    딕셔너리 기반 타입 캐스팅 엔진

    Attributes:
        loader: DictionaryLoader (컬럼 타입/캐스팅 힌트 조회)
    """

    def __init__(self, loader: DictionaryLoader) -> None:
        """
        초기화

        Args:
            loader: 로드된 DictionaryLoader
        """
        self.loader = loader

    def cast_for_column(self, table_column: str) -> CastResult:
        """
        컬럼에 대한 캐스팅 판단을 반환한다 (딕셔너리 조회).

        Args:
            table_column: "table.column" 키

        Returns:
            CastResult (cast_applied/warning 등). SQL은 건드리지 않음
        """
        entry = self.loader.lookup(table_column)
        if not entry.get("found"):
            return CastResult(
                variable="",
                column=table_column,
                column_type=None,
                cast_applied=None,
                reason="딕셔너리에 없는 컬럼 (캐스팅 생략, 수동 검토 권장)",
                warning=f"컬럼을 딕셔너리에서 찾을 수 없음: {table_column}",
            )

        data_type = (entry.get("data_type") or "").lower()
        cast_hint = entry.get("cast_hint") or {}

        # 고정 길이 CHAR: 캐스팅은 안 하되 패딩/TRIM 경고
        if data_type in _FIXED_CHAR_TYPES or cast_hint.get("needs_trim"):
            return CastResult(
                variable="",
                column=table_column,
                column_type=data_type,
                cast_applied=None,
                reason="CHAR 고정 길이: 캐스팅 불필요",
                warning=(
                    f"CHAR 타입({table_column}): PostgreSQL은 패딩 비교가 엄격 "
                    "(자바에서 패딩 전달 또는 TRIM 고려)"
                ),
            )

        # 문자열 계열: 캐스팅 불필요
        if data_type in _NO_CAST_TYPES:
            return CastResult(
                variable="",
                column=table_column,
                column_type=data_type,
                cast_applied=None,
                reason="문자열 타입, 캐스팅 불필요",
            )

        # 숫자/날짜 등: cast_hint의 구문 사용
        cast_syntax = cast_hint.get("cast_syntax")
        if cast_hint.get("needs_cast_from_string") and cast_syntax:
            return CastResult(
                variable="",
                column=table_column,
                column_type=data_type,
                cast_applied=cast_syntax,
                reason=f"{data_type} 타입, 명시적 캐스팅 필요",
            )

        return CastResult(
            variable="",
            column=table_column,
            column_type=data_type,
            cast_applied=None,
            reason=f"{data_type}: 캐스팅 규칙 없음 (생략)",
        )

    def apply_bind_cast(
        self, sql: str, bind_var: str, cast_syntax: str
    ) -> str:
        """
        SQL 내 특정 바인드 변수 #{bind_var}에 캐스팅을 추가한다 (멱등).

        정규식 대신 문자열 탐색으로 정확히 "#{bind_var}" 토큰을 찾고, 바로 뒤에
        이미 동일 캐스팅이 있으면 건너뛴다. #{bind_var, jdbcType=...} 같이
        옵션이 붙은 형태는 안전을 위해 건드리지 않는다.

        Args:
            sql: 대상 SQL 문자열
            bind_var: 바인드 변수명 (중괄호/샵 제외, 예: "userId")
            cast_syntax: 추가할 캐스팅 (예: "::INTEGER")

        Returns:
            캐스팅이 적용된 SQL
        """
        if not cast_syntax:
            return sql

        token = "#{" + bind_var + "}"
        result: List[str] = []
        i = 0
        token_len = len(token)
        while True:
            idx = sql.find(token, i)
            if idx == -1:
                result.append(sql[i:])
                break
            end = idx + token_len
            result.append(sql[i:end])
            # 멱등: 바로 뒤에 이미 같은 캐스팅이 있으면 추가 안 함
            if not sql.startswith(cast_syntax, end):
                result.append(cast_syntax)
            i = end

        return "".join(result)

    def build_type_casts(
        self, sql: str, bind_to_column: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        (바인드변수 -> 컬럼) 매핑에 따라 SQL에 캐스팅을 적용하고 리포트를 만든다.

        Args:
            sql: 원본 SQL(조각)
            bind_to_column: {"userId": "users.user_id", ...} 매핑

        Returns:
            {"converted_sql": str, "type_casts": [CastResult...], "warnings": [str...]}
            (type_casts는 dict로 직렬화)
        """
        report = TypeCastReport()
        converted = sql

        for bind_var, table_column in bind_to_column.items():
            cast = self.cast_for_column(table_column)
            cast.variable = bind_var

            if cast.cast_applied:
                converted = self.apply_bind_cast(
                    converted, bind_var, cast.cast_applied
                )
            if cast.warning:
                report.warnings.append(cast.warning)

            report.casts.append(cast)

        return {
            "converted_sql": converted,
            "type_casts": [self._cast_to_dict(c) for c in report.casts],
            "warnings": report.warnings,
        }

    @staticmethod
    def _cast_to_dict(cast: CastResult) -> Dict[str, Any]:
        """CastResult를 직렬화 가능한 dict로 변환한다."""
        return {
            "variable": cast.variable,
            "column": cast.column,
            "column_type": cast.column_type,
            "cast_applied": cast.cast_applied,
            "reason": cast.reason,
            "warning": cast.warning,
        }
