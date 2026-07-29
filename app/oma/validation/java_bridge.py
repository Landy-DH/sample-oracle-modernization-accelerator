"""
Java 검증 브리지 모듈

Java Validator(oma-validator.jar)를 subprocess로 호출해 TC 검증을 수행한다.
Java는 MyBatis getBoundSql로 동적 SQL을 완성하고 소스/타겟 DB에서 실행하며,
Python은 요청 JSON을 구성하고 결과 JSON을 받는다 (stdin/stdout 통신).

성능: TC마다 JVM/매퍼 로딩을 반복하지 않도록, 한 번의 프로세스 호출에 여러 TC를
배치로 전달한다 (JAR이 배치 요청을 지원).

설계 원칙:
  - JDBC 접속 정보는 Secrets Manager/Config에서 얻어 요청에 주입 (하드코딩 금지)
  - Oracle은 service_name 기반 URL 사용 (검증 결과: 소스가 PDB)
  - 자격증명은 로그에 남기지 않는다

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - JavaValidationBridge: build_request/validate_batch/_run_jar
  - 시크릿→JDBC URL 변환(oracle service_name, postgres), 타임아웃/에러 처리
  - jar/디렉토리 주입 가능 (테스트 용이)

2026-07-28 | OMA Team | EPAS 소스 지원 (design/19-multisource-target-guide.md 조합 B)
  - source_type 주입: _source_db_config()가 소스 방언별 JDBC URL 분기
  - epas → jdbc:postgresql URL + org.postgresql.Driver (Oracle service_name과 분리)
  - from_config가 config의 SOURCE_DB_TYPE를 브리지에 전달
"""

import json
import logging
import subprocess
from typing import Any, Dict, List, Optional

from oma.utils.config import Config
from oma.utils.exceptions import ValidationError

logger = logging.getLogger(__name__)

# 기본 Java 프로세스 타임아웃(초). -1 = 무제한 (실전 대규모 배치 대비).
# 개별 쿼리 타임아웃으로 제어하고, 전체 상한은 필요 시에만 옵트인.
_DEFAULT_TIMEOUT = -1
# JDBC 드라이버 클래스
_ORACLE_DRIVER = "oracle.jdbc.OracleDriver"
_POSTGRES_DRIVER = "org.postgresql.Driver"
_MYSQL_DRIVER = "com.mysql.cj.jdbc.Driver"


class JavaValidationBridge:
    """
    Java Validator 호출 브리지

    Attributes:
        jar_path: oma-validator.jar 경로
        source_mapper_dir: 원본(소스) 매퍼 디렉토리
        target_mapper_dir: 변환된(타겟) 매퍼 디렉토리
        timeout: Java 프로세스 타임아웃(초)
    """

    def __init__(
        self,
        jar_path: str,
        source_mapper_dir: str,
        target_mapper_dir: str,
        source_credentials: Dict[str, Any],
        target_credentials: Dict[str, Any],
        timeout: int = _DEFAULT_TIMEOUT,
        java_bin: str = "java",
        query_timeout: int = 0,
        source_type: str = "oracle",
    ) -> None:
        """
        초기화 (자격증명은 주입)

        Args:
            jar_path: JAR 경로
            source_mapper_dir: 소스 매퍼 디렉토리 (원본 매퍼)
            target_mapper_dir: 타겟 매퍼 디렉토리 (변환된 매퍼)
            source_credentials: 소스 DB 접속 정보 (host/port/sid|database/username/password)
            target_credentials: 타겟 DB 접속 정보 (host/port/database/username/password)
            timeout: Java 프로세스 전체 타임아웃(초)
            java_bin: java 실행 파일 경로
            query_timeout: 개별 SQL 실행 타임아웃(초). 0이면 Java 기본값
            source_type: 소스 DB 타입 (oracle/epas) - JDBC URL/드라이버 분기용
        """
        self.jar_path = jar_path
        self.source_mapper_dir = source_mapper_dir
        self.target_mapper_dir = target_mapper_dir
        self.source_credentials = source_credentials
        self.target_credentials = target_credentials
        self.timeout = timeout
        self.java_bin = java_bin
        self.query_timeout = query_timeout
        self.source_type = str(source_type).lower()

    @classmethod
    def from_config(
        cls,
        config: Config,
        source_credentials: Dict[str, Any],
        target_credentials: Dict[str, Any],
        jar_path: Optional[str] = None,
    ) -> "JavaValidationBridge":
        """
        Config 기반으로 브리지를 생성한다.

        Args:
            config: Config 객체
            source_credentials: 소스 DB 접속 정보
            target_credentials: 타겟 DB 접속 정보
            jar_path: JAR 경로 (없으면 기본 위치)

        Returns:
            JavaValidationBridge
        """
        mapper_work = config.get("MAPPER_WORK_DIR")
        jar = jar_path or config.get(
            "VALIDATOR_JAR_PATH",
            "java-validator/target/oma-validator.jar",
        )
        return cls(
            jar_path=jar,
            source_mapper_dir=f"{mapper_work}/original",
            target_mapper_dir=f"{mapper_work}/merged",
            source_credentials=source_credentials,
            target_credentials=target_credentials,
            # 프로세스 전체 타임아웃 기본 -1(무제한). 개별 쿼리 타임아웃으로 제어.
            timeout=config.get_int("VALIDATION_PROCESS_TIMEOUT", -1),
            query_timeout=config.get_int("VALIDATION_QUERY_TIMEOUT", 0),
            source_type=config.get("SOURCE_DB_TYPE", "oracle"),
        )

    def build_request(self, test_cases: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Java 검증 요청 JSON을 구성한다.

        Args:
            test_cases: TC dict 리스트 (generator/converter 산출물)

        Returns:
            요청 dict (sourceMapperDir/targetMapperDir/source/target/testCases)
        """
        return {
            "sourceMapperDir": self.source_mapper_dir,
            "targetMapperDir": self.target_mapper_dir,
            "source": self._source_db_config(),
            "target": self._target_db_config(),
            "testCases": test_cases,
            "queryTimeoutSeconds": self.query_timeout,
        }

    def _source_db_config(self) -> Dict[str, str]:
        """
        소스 JDBC 접속 설정을 소스 타입별로 만든다.

        - oracle: service_name 기반 URL (jdbc:oracle:thin:@//host:port/service)
        - epas  : PostgreSQL 와이어 프로토콜 (jdbc:postgresql://host:port/database)

        Returns:
            url/user/password/driver 를 담은 dict
        """
        c = self.source_credentials
        if self.source_type == "epas":
            # EPAS는 PG 프로토콜 → postgresql JDBC 드라이버 사용
            database = c.get("database") or c.get("sid")
            url = f"jdbc:postgresql://{c.get('host')}:{c.get('port')}/{database}"
            driver = _POSTGRES_DRIVER
        else:
            service = c.get("sid") or c.get("service_name")
            # PDB 대응: service_name 형식 URL
            url = f"jdbc:oracle:thin:@//{c.get('host')}:{c.get('port')}/{service}"
            driver = _ORACLE_DRIVER
        return {
            "url": url,
            "user": c.get("username"),
            "password": c.get("password"),
            "driver": driver,
        }

    def _target_db_config(self) -> Dict[str, str]:
        """타겟(PostgreSQL) JDBC 접속 설정을 만든다."""
        c = self.target_credentials
        url = f"jdbc:postgresql://{c.get('host')}:{c.get('port')}/{c.get('database')}"
        return {
            "url": url,
            "user": c.get("username"),
            "password": c.get("password"),
            "driver": _POSTGRES_DRIVER,
        }

    def validate_batch(
        self, test_cases: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        TC 배치를 Java Validator로 검증한다 (단일 프로세스 호출).

        Args:
            test_cases: TC dict 리스트

        Returns:
            ValidationResult dict 리스트 (tcId/status/sourceResult/targetResult)

        Raises:
            ValidationError: Java 실행 실패/타임아웃/출력 파싱 실패 시
        """
        if not test_cases:
            return []

        request = self.build_request(test_cases)
        stdout = self._run_jar(json.dumps(request))

        try:
            return json.loads(stdout)
        except json.JSONDecodeError as e:
            raise ValidationError(
                "Java 검증 출력을 JSON으로 파싱할 수 없습니다",
                {"error": str(e), "preview": stdout[:200]},
            ) from e

    def _run_jar(self, input_json: str) -> str:
        """
        JAR을 subprocess로 실행하고 stdout을 반환한다.

        Args:
            input_json: stdin으로 전달할 요청 JSON

        Returns:
            stdout 문자열

        Raises:
            ValidationError: 실행 실패/타임아웃 시
        """
        logger.info("Java 검증 실행: %s", self.jar_path)
        # timeout이 0 이하이면 무제한(None). 실전은 수천 SQL이라 전체 시간 예측이
        # 어려우므로 기본 무제한, 개별 쿼리 타임아웃으로 제어. 필요 시에만 전체 상한.
        proc_timeout = self.timeout if self.timeout and self.timeout > 0 else None
        try:
            proc = subprocess.run(
                [self.java_bin, "-jar", self.jar_path],
                input=input_json,
                capture_output=True,
                text=True,
                timeout=proc_timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise ValidationError(
                "Java 검증이 타임아웃되었습니다",
                {"timeout": proc_timeout},
            ) from e
        except FileNotFoundError as e:
            raise ValidationError(
                "java 실행 파일 또는 JAR을 찾을 수 없습니다",
                {"java_bin": self.java_bin, "jar": self.jar_path},
            ) from e

        if proc.returncode != 0:
            # stderr에 error JSON이 담김 (자격증명 없음)
            raise ValidationError(
                "Java 검증 프로세스가 실패했습니다",
                {"returncode": proc.returncode, "stderr": proc.stderr[:500]},
            )
        return proc.stdout
