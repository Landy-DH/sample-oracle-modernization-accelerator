"""
스키마 딕셔너리 생성 모듈

타겟 DB(PostgreSQL)의 information_schema에서 테이블/컬럼 메타데이터를 추출하고,
각 테이블의 샘플 데이터 1건과 형변환 힌트를 결합해 schema_dictionary.json을 생성한다.

딕셔너리 키는 "table.column"(소문자), 값은 타입/nullable/길이/샘플/캐스팅 힌트.
LLM이 이 딕셔너리를 조회해 정확한 형변환을 판단한다 (01-migration-principles.md 참고).

주의:
  - 식별자(테이블/스키마)는 psycopg2.sql.Identifier로 안전하게 조합 (인젝션 방지)
  - 정규식으로 SQL을 파싱하지 않음 (information_schema 조회만 사용)
  - DB 연결 정보는 Secrets Manager 또는 config에서 획득 (하드코딩 금지)

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - DictionaryBuilder 구현: build/extract_metadata/collect_samples/
    generate_cast_hints/save_to_file
  - connection 주입 가능 구조 (테스트 용이)
  - 캐스팅 힌트 규칙을 _NUMERIC_TYPES 등 모듈 상수로 분리
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from oma.utils.config import Config
from oma.utils.exceptions import DatabaseError

logger = logging.getLogger(__name__)

# 문자열 바인드 변수에 명시적 캐스팅이 필요한 숫자 계열 타입
# (data_type -> ::CAST 문법)
_NUMERIC_CAST_SYNTAX: Dict[str, str] = {
    "smallint": "::SMALLINT",
    "integer": "::INTEGER",
    "bigint": "::BIGINT",
    "numeric": "::NUMERIC",
    "decimal": "::NUMERIC",
    "real": "::REAL",
    "double precision": "::DOUBLE PRECISION",
}

# 날짜/시간 계열 타입 (리터럴/바인드에 캐스팅 권장)
_DATETIME_CAST_SYNTAX: Dict[str, str] = {
    "date": "::DATE",
    "timestamp without time zone": "::TIMESTAMP",
    "timestamp with time zone": "::TIMESTAMPTZ",
    "time without time zone": "::TIME",
    "time with time zone": "::TIMETZ",
}

# 고정 길이 문자 타입 (CHAR): PostgreSQL은 패딩 비교가 엄격 → TRIM 고려 필요
_FIXED_CHAR_TYPES = frozenset({"character", "char", "bpchar"})

# 각 테이블 샘플 조회 시 가져올 행 수
_SAMPLE_ROW_LIMIT = 1


class DictionaryBuilder:
    """
    스키마 딕셔너리 생성기

    PostgreSQL information_schema에서 메타데이터를 추출하고, 샘플/캐스팅 힌트를
    결합해 딕셔너리를 만든다. DB 커넥션은 주입하거나 config 기반으로 생성한다.

    Attributes:
        config: Config 객체
        schema: 대상 스키마명 (config의 TARGET_SCHEMA)
    """

    def __init__(
        self,
        config: Config,
        connection: Optional[Any] = None,
        target: Optional[Any] = None,
    ) -> None:
        """
        초기화

        커넥션/스키마 획득 우선순위:
          1. target 플러그인이 주어지면 그 커넥션과 get_schema_name() 사용
          2. connection이 주어지면 그것을 사용
          3. 둘 다 없으면 config의 TARGET_* 값으로 직접 연결

        Args:
            config: Config 객체
            connection: 주입할 DB 커넥션 (선택, 테스트용)
            target: TargetDB 플러그인 (선택). 커넥션+스키마를 제공
        """
        self.config = config
        self._target = target

        if target is not None:
            self._connection = target.get_connection()
            self.schema = target.get_schema_name()
        else:
            self._connection = connection
            self.schema = config.get("TARGET_SCHEMA", "public")

    def build(self) -> Dict[str, Any]:
        """
        딕셔너리 전체를 생성하고 파일로 저장한다.

        Returns:
            생성된 딕셔너리 ({"table.column": {...}})

        Raises:
            DatabaseError: 메타데이터/샘플 조회 실패 시
        """
        logger.info("스키마 딕셔너리 생성 시작 (schema=%s)", self.schema)

        metadata = self.extract_metadata()
        samples = self.collect_samples(metadata)
        dictionary = self.generate_cast_hints(metadata, samples)

        output_path = self.config.get("SCHEMA_DICT_PATH")
        if output_path:
            self.save_to_file(dictionary, output_path)

        logger.info("스키마 딕셔너리 생성 완료: %d개 컬럼", len(dictionary))
        return dictionary

    def _get_connection(self) -> Any:
        """
        DB 커넥션을 반환한다 (주입된 것 우선, 없으면 config 기반 생성).

        Returns:
            psycopg2 connection

        Raises:
            DatabaseError: psycopg2 임포트 또는 연결 실패 시
        """
        if self._connection is not None:
            return self._connection

        try:
            import psycopg2
        except ImportError as e:
            raise DatabaseError(
                "psycopg2를 임포트할 수 없습니다",
                {"error": str(e)},
            ) from e

        try:
            self._connection = psycopg2.connect(
                host=self.config.get("TARGET_HOST"),
                port=self.config.get("TARGET_PORT"),
                dbname=self.config.get("TARGET_DATABASE"),
                user=self.config.get("TARGET_USER"),
                password=self.config.get("TARGET_PASSWORD"),
            )
        except Exception as e:
            raise DatabaseError(
                "타겟 DB 연결에 실패했습니다",
                {"host": self.config.get("TARGET_HOST"), "error": str(e)},
            ) from e

        return self._connection

    def extract_metadata(self) -> List[Dict[str, Any]]:
        """
        information_schema.columns에서 컬럼 메타데이터를 추출한다.

        Returns:
            컬럼 메타데이터 리스트. 각 항목:
            table_name, column_name, data_type, is_nullable,
            character_maximum_length, numeric_precision, numeric_scale

        Raises:
            DatabaseError: 조회 실패 시
        """
        query = """
            SELECT table_name, column_name, data_type, is_nullable,
                   character_maximum_length, numeric_precision, numeric_scale
            FROM information_schema.columns
            WHERE table_schema = %s
            ORDER BY table_name, ordinal_position
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(query, (self.schema,))
                columns = [desc[0] for desc in cur.description]
                rows = cur.fetchall()
        except Exception as e:
            raise DatabaseError(
                "메타데이터 조회에 실패했습니다",
                {"schema": self.schema, "error": str(e)},
            ) from e

        metadata = [dict(zip(columns, row)) for row in rows]
        logger.info("메타데이터 추출 완료: %d개 컬럼", len(metadata))
        return metadata

    def collect_samples(
        self, metadata: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """
        각 테이블에서 샘플 1건을 조회한다.

        조회 실패한 테이블은 건너뛰고 경고만 남긴다 (전체 생성은 계속 진행).

        Args:
            metadata: extract_metadata() 결과

        Returns:
            {table_name: {column_name: sample_value}} 형태. 빈 테이블은 값이 {}
        """
        # psycopg2.sql은 식별자 안전 조합용 (문자열 포맷 금지)
        try:
            from psycopg2 import sql as pg_sql
        except ImportError as e:
            raise DatabaseError(
                "psycopg2를 임포트할 수 없습니다",
                {"error": str(e)},
            ) from e

        table_names = self._distinct_tables(metadata)
        conn = self._get_connection()
        samples: Dict[str, Dict[str, Any]] = {}

        for table in table_names:
            stmt = pg_sql.SQL("SELECT * FROM {}.{} LIMIT {}").format(
                pg_sql.Identifier(self.schema),
                pg_sql.Identifier(table),
                pg_sql.Literal(_SAMPLE_ROW_LIMIT),
            )
            try:
                with conn.cursor() as cur:
                    cur.execute(stmt)
                    row = cur.fetchone()
                    col_names = [desc[0] for desc in cur.description]
                samples[table] = dict(zip(col_names, row)) if row else {}
            except Exception as e:
                # 개별 테이블 실패는 치명적이지 않음 → 경고 후 계속
                logger.warning(
                    "샘플 조회 실패 (건너뜀): table=%s, error=%s", table, e
                )
                samples[table] = {}

        return samples

    @staticmethod
    def _distinct_tables(metadata: List[Dict[str, Any]]) -> List[str]:
        """
        메타데이터에서 중복 없는 테이블명 리스트를 순서 유지하며 추출한다.

        Args:
            metadata: 컬럼 메타데이터 리스트

        Returns:
            테이블명 리스트
        """
        seen: Dict[str, None] = {}
        for row in metadata:
            seen.setdefault(row["table_name"], None)
        return list(seen.keys())

    def generate_cast_hints(
        self,
        metadata: List[Dict[str, Any]],
        samples: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        컬럼별 캐스팅 힌트를 포함한 최종 딕셔너리를 생성한다.

        Args:
            metadata: 컬럼 메타데이터 리스트
            samples: collect_samples() 결과

        Returns:
            {"table.column": {table, column, data_type, is_nullable,
             char_max_length, numeric_precision, numeric_scale,
             sample_value, cast_hint}} 딕셔너리
        """
        dictionary: Dict[str, Any] = {}

        for row in metadata:
            table = row["table_name"]
            column = row["column_name"]
            data_type = (row.get("data_type") or "").lower()
            key = f"{table}.{column}".lower()

            sample_value = samples.get(table, {}).get(column)

            dictionary[key] = {
                "table": table,
                "column": column,
                "data_type": data_type,
                "is_nullable": row.get("is_nullable") == "YES",
                "char_max_length": row.get("character_maximum_length"),
                "numeric_precision": row.get("numeric_precision"),
                "numeric_scale": row.get("numeric_scale"),
                "sample_value": self._to_serializable(sample_value),
                "cast_hint": self._build_cast_hint(data_type),
            }

        return dictionary

    @staticmethod
    def _build_cast_hint(data_type: str) -> Dict[str, Any]:
        """
        data_type에 따른 캐스팅 힌트를 만든다.

        Args:
            data_type: 소문자 PostgreSQL 데이터 타입

        Returns:
            {needs_cast_from_string, cast_syntax, needs_trim, note} 힌트
        """
        hint: Dict[str, Any] = {
            "needs_cast_from_string": False,
            "cast_syntax": None,
            "needs_trim": False,
            "note": None,
        }

        if data_type in _NUMERIC_CAST_SYNTAX:
            hint["needs_cast_from_string"] = True
            hint["cast_syntax"] = _NUMERIC_CAST_SYNTAX[data_type]
            hint["note"] = (
                "리터럴은 숫자로, 바인드 변수는 명시적 캐스팅 권장"
            )
        elif data_type in _DATETIME_CAST_SYNTAX:
            hint["needs_cast_from_string"] = True
            hint["cast_syntax"] = _DATETIME_CAST_SYNTAX[data_type]
            hint["note"] = "날짜/시간 리터럴에 명시적 캐스팅 권장"
        elif data_type in _FIXED_CHAR_TYPES:
            hint["needs_trim"] = True
            hint["note"] = (
                "CHAR 고정 길이: PostgreSQL은 패딩 비교가 엄격 "
                "(자바에서 패딩 전달 또는 TRIM 고려)"
            )

        return hint

    @staticmethod
    def _to_serializable(value: Any) -> Any:
        """
        샘플 값을 JSON 직렬화 가능한 형태로 변환한다.

        date/datetime/Decimal 등은 str로 변환하고, 그 외 기본 타입은 그대로 둔다.

        Args:
            value: 원본 샘플 값

        Returns:
            JSON 직렬화 가능한 값
        """
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    def save_to_file(self, dictionary: Dict[str, Any], file_path: str) -> None:
        """
        딕셔너리를 JSON 파일로 저장한다 (디렉토리 자동 생성).

        Args:
            dictionary: 생성된 딕셔너리
            file_path: 저장 경로

        Raises:
            DatabaseError: 파일 쓰기 실패 시
        """
        directory = os.path.dirname(file_path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(dictionary, f, ensure_ascii=False, indent=2)
        except OSError as e:
            raise DatabaseError(
                "딕셔너리 파일 저장에 실패했습니다",
                {"file_path": file_path, "error": str(e)},
            ) from e

        logger.info("딕셔너리 저장 완료: %s", file_path)
