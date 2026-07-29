# OMA (Oracle Migration Assistant) 아키텍처 설계

## 요구사항

### 지원 DB
**소스 (확장 가능)**:
- Oracle
- EDB Postgres (Oracle 호환 모드)
- Tibero
- (향후 추가 가능)

**타겟**:
- PostgreSQL
- MySQL

### 핵심 기능
1. 소스 DB 스키마 추출 → 타겟 DB 딕셔너리 생성
2. MyBatis 매퍼 변환 (소스 SQL → 타겟 SQL)
3. 형변환 자동 추가
4. 테스트 케이스 생성
5. 검증

### DB 접속 전략
**소스 DB**:
- 관리자 계정으로 접속 (예: SYSTEM, postgres)
- 대상 스키마(유저)의 메타데이터 조회
- 샘플 데이터 조회

**타겟 DB**:
- 대상 유저 계정으로 직접 접속
- 스키마 메타데이터 조회 및 딕셔너리 생성
- TC 실행 및 검증

### 크리덴셜 관리
- **AWS Secrets Manager** 사용
- 소스/타겟 DB 별로 별도 시크릿
- 런타임에 boto3로 동적 조회
- 시크릿 이름: 추후 확정 (예: `oma/source/oracle`, `oma/target/postgres`)

---

## 1. 프로그래밍 언어 선택

### Python (권장) ✅

**선택 이유**:
1. **Bedrock 통합 용이**: boto3 SDK 성숙
2. **DB 드라이버 풍부**: cx_Oracle, psycopg2, mysql-connector, pymysql
3. **빠른 개발**: 스크립트 언어, 동적 타이핑
4. **XML 파싱**: lxml, ElementTree
5. **JSON 처리**: 네이티브 지원
6. **멀티프로세싱**: multiprocessing 라이브러리
7. **에코시스템**: pandas (데이터 처리), jinja2 (템플릿)

**단점**:
- 타입 안전성 낮음 (→ type hints 사용)
- 실행 파일 배포 복잡 (→ Docker 사용)

### Java (대안)

**장점**:
- 타입 안전
- MyBatis 네이티브 파싱
- 엔터프라이즈 성숙도

**단점**:
- Bedrock SDK 상대적으로 무거움
- 개발 속도 느림
- DB별 JDBC 드라이버 관리

### 결론: **Python 3.10+**

---

## 2. DB 접속 방식

### 옵션 A: 네이티브 CLI 툴 (비추천)

```bash
# Oracle
sqlplus user/pass@host:port/sid

# PostgreSQL
psql -h host -U user -d database

# MySQL
mysql -h host -u user -p database
```

**단점**:
- 설치 복잡 (특히 Oracle Instant Client)
- 버전 관리 어려움
- 출력 파싱 필요
- 에러 처리 어려움

### 옵션 B: Python DB 드라이버 (권장) ✅

```python
# Oracle
import cx_Oracle

# PostgreSQL
import psycopg2

# MySQL
import mysql.connector
```

**장점**:
- pip로 간단 설치
- 네이티브 Python 객체 반환
- 에러 처리 표준화
- 트랜잭션 관리 용이
- 연결 풀링 지원

**선택**:
- **Oracle**: `cx_Oracle` (또는 `oracledb` - 신규 thin 모드)
- **PostgreSQL**: `psycopg2-binary`
- **MySQL**: `mysql-connector-python`
- **Tibero**: `jaydebeapi` (JDBC 브릿지) 또는 Tibero Python 드라이버

---

## 3. 전체 아키텍처

### 3.1 Plugin 아키텍처

```
┌─────────────────────────────────────────┐
│            OMA Core Engine              │
│  - 워크플로우 오케스트레이션              │
│  - LLM 호출 (Bedrock)                   │
│  - 매퍼 분할/병합                        │
│  - TC 생성                               │
└─────────────────────────────────────────┘
           ↓                    ↓
    ┌──────────┐         ┌─────────────┐
    │  Source  │         │   Target    │
    │ Plugins  │         │  Plugins    │
    └──────────┘         └─────────────┘
         ↓                      ↓
    ┌─────────┐           ┌──────────┐
    │ Oracle  │           │PostgreSQL│
    │   EDB   │           │  MySQL   │
    │ Tibero  │           └──────────┘
    └─────────┘
```

### 3.2 디렉토리 구조

```
oma/
├── oma/                          # Python 패키지
│   ├── __init__.py
│   ├── core/                     # 코어 엔진
│   │   ├── __init__.py
│   │   ├── workflow.py           # 전체 워크플로우
│   │   ├── mapper_parser.py      # MyBatis XML 파싱
│   │   ├── mapper_splitter.py    # 매퍼 분할
│   │   ├── mapper_merger.py      # 매퍼 병합
│   │   ├── llm_client.py         # Bedrock LLM 호출
│   │   └── test_case_generator.py # TC 생성
│   │
│   ├── sources/                  # 소스 DB 플러그인
│   │   ├── __init__.py
│   │   ├── base.py               # 추상 베이스 클래스
│   │   ├── oracle.py             # Oracle 구현
│   │   ├── edb.py                # EDB Postgres 구현
│   │   └── tibero.py             # Tibero 구현
│   │
│   ├── targets/                  # 타겟 DB 플러그인
│   │   ├── __init__.py
│   │   ├── base.py               # 추상 베이스 클래스
│   │   ├── postgres.py           # PostgreSQL 구현
│   │   └── mysql.py              # MySQL 구현
│   │
│   ├── converters/               # 변환 규칙
│   │   ├── __init__.py
│   │   ├── oracle_to_postgres.py # Oracle→PG 규칙
│   │   ├── oracle_to_mysql.py    # Oracle→MySQL 규칙
│   │   ├── edb_to_postgres.py    # EDB→PG 규칙
│   │   └── rules/                # 변환 규칙 정의
│   │       ├── functions.yaml    # 함수 매핑
│   │       ├── types.yaml        # 타입 매핑
│   │       └── syntax.yaml       # 구문 매핑
│   │
│   ├── validation/               # 검증
│   │   ├── __init__.py
│   │   ├── syntax_validator.py
│   │   └── tc_executor.py        # TC 실행 및 비교
│   │
│   └── utils/                    # 유틸리티
│       ├── __init__.py
│       ├── config.py             # 설정 로드
│       ├── logger.py
│       ├── secrets.py            # AWS Secrets Manager
│       └── db_utils.py
│
├── rules/                        # 변환 규칙 파일 (외부화)
│   ├── oracle_to_postgres/
│   │   ├── functions.yaml
│   │   ├── types.yaml
│   │   └── syntax.yaml
│   └── oracle_to_mysql/
│       ├── functions.yaml
│       ├── types.yaml
│       └── syntax.yaml
│
├── prompts/                      # LLM 프롬프트 템플릿
│   ├── conversion_base.txt
│   ├── conversion_postgres.txt
│   └── conversion_mysql.txt
│
├── tests/                        # 테스트
│   ├── test_sources/
│   ├── test_targets/
│   └── test_converters/
│
├── scripts/                      # 실행 스크립트
│   ├── run_conversion.py         # 메인 실행
│   ├── generate_dictionary.py   # 딕셔너리 생성만
│   └── validate_results.py       # 검증만
│
├── config/
│   └── oma.properties            # 설정 파일
│
├── requirements.txt              # Python 의존성
├── setup.py
├── Dockerfile                    # 배포용
└── README.md
```

---

## 4. 핵심 추상화 레이어

### 4.1 Source Plugin Base Class

```python
# oma/sources/base.py
from abc import ABC, abstractmethod
from typing import Dict, List, Any

class SourceDB(ABC):
    """소스 DB 추상 베이스
    
    소스 DB는 관리자 계정으로 접속하여
    대상 스키마(유저)의 메타데이터를 조회합니다.
    """
    
    def __init__(self, config: Dict[str, str]):
        self.config = config
        self.connection = None
        self.admin_user = config.get('admin_user')  # 관리자 계정
        self.target_schema = config.get('target_schema')  # 대상 스키마
    
    @abstractmethod
    def connect(self) -> None:
        """DB 연결 (관리자 계정)"""
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        """DB 연결 해제"""
        pass
    
    @abstractmethod
    def extract_schema(self, schema_name: str) -> Dict[str, Any]:
        """스키마 메타데이터 추출
        
        Returns:
            {
                "tables": {
                    "table_name": {
                        "columns": {
                            "column_name": {
                                "data_type": "...",
                                "nullable": true/false,
                                ...
                            }
                        }
                    }
                }
            }
        """
        pass
    
    @abstractmethod
    def get_sample_data(self, table: str, limit: int = 1) -> List[Dict]:
        """샘플 데이터 조회"""
        pass
    
    @abstractmethod
    def get_sql_dialect(self) -> str:
        """SQL 방언 반환 (oracle, edb, tibero)"""
        pass
    
    def test_connection(self) -> bool:
        """연결 테스트"""
        try:
            self.connect()
            self.disconnect()
            return True
        except Exception as e:
            return False
```

### 4.2 Target Plugin Base Class

```python
# oma/targets/base.py
from abc import ABC, abstractmethod
from typing import Dict, List, Any

class TargetDB(ABC):
    """타겟 DB 추상 베이스
    
    타겟 DB는 대상 유저 계정으로 직접 접속합니다.
    """
    
    def __init__(self, config: Dict[str, str]):
        self.config = config
        self.connection = None
        self.user = config.get('user')  # 대상 유저
        self.schema = config.get('schema')  # 대상 스키마
    
    @abstractmethod
    def connect(self) -> None:
        """DB 연결 (대상 유저 계정)"""
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        """DB 연결 해제"""
        pass
    
    @abstractmethod
    def get_schema_info(self, schema_name: str) -> Dict[str, Any]:
        """타겟 DB 스키마 정보 (딕셔너리 생성용)
        
        Returns:
            {
                "table.column": {
                    "data_type": "integer",
                    "sample_value": 123,
                    "cast_hint": {...}
                }
            }
        """
        pass
    
    @abstractmethod
    def validate_sql(self, sql: str) -> bool:
        """SQL 구문 검증 (PREPARE 테스트)"""
        pass
    
    @abstractmethod
    def execute_test_case(self, sql: str, params: Dict) -> List[Dict]:
        """TC 실행"""
        pass
    
    @abstractmethod
    def get_sql_dialect(self) -> str:
        """SQL 방언 반환 (postgres, mysql)"""
        pass
    
    @abstractmethod
    def get_type_cast_syntax(self, target_type: str) -> str:
        """타입 캐스팅 구문 반환
        
        PostgreSQL: "::INTEGER"
        MySQL: ""  (CAST 함수 사용)
        """
        pass
```

### 4.3 Converter Base Class

```python
# oma/converters/base.py
from abc import ABC, abstractmethod
from typing import Dict, Any

class Converter(ABC):
    """소스→타겟 변환기 베이스"""
    
    def __init__(self, source_dialect: str, target_dialect: str):
        self.source_dialect = source_dialect
        self.target_dialect = target_dialect
        self.rules = self.load_rules()
    
    @abstractmethod
    def load_rules(self) -> Dict[str, Any]:
        """변환 규칙 로드 (YAML 파일에서)"""
        pass
    
    @abstractmethod
    def get_function_mapping(self) -> Dict[str, str]:
        """함수 매핑 반환
        
        Returns:
            {"NVL": "COALESCE", "DECODE": "CASE", ...}
        """
        pass
    
    @abstractmethod
    def get_type_mapping(self) -> Dict[str, str]:
        """타입 매핑 반환
        
        Returns:
            {"NUMBER": "NUMERIC", "VARCHAR2": "VARCHAR", ...}
        """
        pass
    
    @abstractmethod
    def requires_type_cast(self, data_type: str) -> bool:
        """형변환 필요 여부"""
        pass
    
    @abstractmethod
    def get_conversion_prompt_template(self) -> str:
        """LLM 프롬프트 템플릿 반환"""
        pass
```

---

## 5. AWS Secrets Manager 통합

### 5.1 Secrets 구조

**시크릿 이름** (확정):
```
# 소스 DB
oma-source-admin     # 관리자 계정 (스키마 추출용)
oma-source-service   # 서비스 계정 (선택적, 마이그레이션에서는 미사용)

# 타겟 DB
oma-target-admin     # 관리자 계정 (선택적, 마이그레이션에서는 미사용)
oma-target-service   # 서비스 계정 (스키마 작업용)
```

**마이그레이션에서 사용하는 시크릿**:
- 소스: `oma-source-admin` (관리자 권한으로 스키마 추출)
- 타겟: `oma-target-service` (일반 유저 권한으로 작업)

**시크릿 값 (JSON)**:

소스 DB:
```json
{
  "admin_user": "SYSTEM",
  "admin_password": "admin_password",
  "target_schema": "APPDB",
  "host": "10.0.139.149",
  "port": 1521,
  "service_name": "ORCLPDB1"
}
```

타겟 DB:
```json
{
  "user": "appdb",
  "password": "user_password",
  "schema": "appdb",
  "host": "omabox-stack-aurora-cluster.cluster-xxx.rds.amazonaws.com",
  "port": 5432,
  "database": "appdb"
}
```

### 5.2 Secrets Manager 유틸리티

```python
# oma/utils/secrets.py
import boto3
import json
from typing import Dict
from botocore.exceptions import ClientError

class SecretsManager:
    """AWS Secrets Manager 클라이언트"""
    
    def __init__(self, region_name: str):
        self.client = boto3.client(
            'secretsmanager',
            region_name=region_name
        )
    
    def get_secret(self, secret_name: str) -> Dict:
        """시크릿 조회
        
        Args:
            secret_name: 시크릿 이름 (예: "oma/source/oracle")
        
        Returns:
            시크릿 값 (JSON 파싱된 Dict)
        
        Raises:
            ClientError: 시크릿 조회 실패
        """
        try:
            response = self.client.get_secret_value(SecretId=secret_name)
            
            # JSON 파싱
            if 'SecretString' in response:
                return json.loads(response['SecretString'])
            else:
                # Binary secret (사용 안 함)
                raise ValueError(f"Binary secret not supported: {secret_name}")
        
        except ClientError as e:
            error_code = e.response['Error']['Code']
            
            if error_code == 'ResourceNotFoundException':
                raise ValueError(f"Secret not found: {secret_name}")
            elif error_code == 'InvalidRequestException':
                raise ValueError(f"Invalid request: {secret_name}")
            elif error_code == 'InvalidParameterException':
                raise ValueError(f"Invalid parameter: {secret_name}")
            elif error_code == 'DecryptionFailure':
                raise ValueError(f"Decryption failed: {secret_name}")
            elif error_code == 'InternalServiceError':
                raise RuntimeError(f"Internal service error: {secret_name}")
            else:
                raise
    
    def get_source_credentials(self, secret_name: str = "oma-source-admin") -> Dict:
        """소스 DB 크리덴셜 조회
        
        Args:
            secret_name: 시크릿 이름 (기본값: oma-source-admin)
        
        Returns:
            {
                "admin_user": "...",
                "admin_password": "...",
                "target_schema": "...",
                "host": "...",
                ...
            }
        """
        return self.get_secret(secret_name)
    
    def get_target_credentials(self, secret_name: str = "oma-target-service") -> Dict:
        """타겟 DB 크리덴셜 조회
        
        Args:
            secret_name: 시크릿 이름 (기본값: oma-target-service)
        
        Returns:
            {
                "user": "...",
                "password": "...",
                "schema": "...",
                "host": "...",
                ...
            }
        """
        return self.get_secret(secret_name)
```

### 5.3 설정 파일 통합

```python
# oma/utils/config.py
import configparser
from typing import Dict
from .secrets import SecretsManager

class Config:
    """설정 로더 (properties + Secrets Manager)"""
    
    def __init__(self, config_path: str, aws_region: str):
        self.config_path = config_path
        self.aws_region = aws_region
        self.secrets = SecretsManager(aws_region)
        self._load_config()
    
    def _load_config(self):
        """properties 파일 로드"""
        parser = configparser.ConfigParser()
        parser.read(self.config_path)
        
        # COMMON 섹션
        self.common = dict(parser['COMMON'])
    
    def get_source_config(self) -> Dict:
        """소스 DB 설정 (Secrets Manager에서 조회)"""
        source_type = self.common.get('SOURCE_DB_TYPE', 'oracle')
        secret_name = self.common.get('SOURCE_SECRET_NAME', 'oma-source-admin')
        
        # Secrets Manager에서 크리덴셜 조회
        credentials = self.secrets.get_source_credentials(secret_name)
        
        return {
            'db_type': source_type,
            'admin_user': credentials['admin_user'],
            'admin_password': credentials['admin_password'],
            'target_schema': credentials['target_schema'],
            'host': credentials['host'],
            'port': credentials['port'],
            'service_name': credentials.get('service_name'),  # Oracle
            'database': credentials.get('database'),  # PostgreSQL
        }
    
    def get_target_config(self) -> Dict:
        """타겟 DB 설정 (Secrets Manager에서 조회)"""
        target_type = self.common.get('TARGET_DB_TYPE', 'postgres')
        secret_name = self.common.get('TARGET_SECRET_NAME', 'oma-target-service')
        
        # Secrets Manager에서 크리덴셜 조회
        credentials = self.secrets.get_target_credentials(secret_name)
        
        return {
            'db_type': target_type,
            'user': credentials['user'],
            'password': credentials['password'],
            'schema': credentials['schema'],
            'host': credentials['host'],
            'port': credentials['port'],
            'database': credentials['database'],
        }
    
    def get(self, key: str, default=None):
        """일반 설정 값 조회"""
        return self.common.get(key, default)
```

---

## 6. 구현 예시

### 6.1 Oracle Source Plugin (관리자 접속)

```python
# oma/sources/oracle.py
import cx_Oracle
from .base import SourceDB

class OracleSource(SourceDB):
    """Oracle 소스 - 관리자 계정으로 접속"""
    
    def connect(self):
        """관리자 계정으로 접속"""
        dsn = cx_Oracle.makedsn(
            self.config['host'],
            self.config['port'],
            service_name=self.config['service_name']
        )
        self.connection = cx_Oracle.connect(
            user=self.admin_user,  # 관리자 계정 (예: SYSTEM)
            password=self.config['admin_password'],
            dsn=dsn
        )
    
    def disconnect(self):
        if self.connection:
            self.connection.close()
    
    def extract_schema(self, schema_name: str = None) -> Dict:
        """대상 스키마의 메타데이터 추출
        
        Args:
            schema_name: 생략 시 self.target_schema 사용
        """
        if schema_name is None:
            schema_name = self.target_schema
        
        cursor = self.connection.cursor()
        
        # 대상 스키마의 테이블 목록 (관리자 권한으로 조회)
        cursor.execute("""
            SELECT table_name 
            FROM all_tables 
            WHERE owner = :schema
        """, schema=schema_name.upper())
        
        tables = {}
        for (table_name,) in cursor:
            # 컬럼 정보
            cursor.execute("""
                SELECT column_name, data_type, data_length, 
                       data_precision, data_scale, nullable
                FROM all_tab_columns
                WHERE owner = :schema AND table_name = :table
                ORDER BY column_id
            """, schema=schema_name.upper(), table=table_name)
            
            columns = {}
            for col in cursor:
                columns[col[0].lower()] = {
                    'data_type': col[1],
                    'data_length': col[2],
                    'data_precision': col[3],
                    'data_scale': col[4],
                    'nullable': col[5] == 'Y'
                }
            
            tables[table_name.lower()] = {'columns': columns}
        
        return {'tables': tables}
    
    def get_sample_data(self, table: str, limit: int = 1) -> List[Dict]:
        """대상 스키마의 테이블에서 샘플 데이터 조회"""
        cursor = self.connection.cursor()
        # 스키마 명시
        full_table = f"{self.target_schema}.{table}"
        cursor.execute(f"SELECT * FROM {full_table} WHERE ROWNUM <= :limit", limit=limit)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor]
    
    def get_sql_dialect(self) -> str:
        return "oracle"
```

### 6.2 PostgreSQL Target Plugin (유저 직접 접속)

```python
# oma/targets/postgres.py
import psycopg2
from .base import TargetDB

class PostgreSQLTarget(TargetDB):
    """PostgreSQL 타겟 - 대상 유저로 직접 접속"""
    
    def connect(self):
        """대상 유저 계정으로 접속"""
        self.connection = psycopg2.connect(
            host=self.config['host'],
            port=self.config['port'],
            database=self.config['database'],
            user=self.user,  # 대상 유저 (예: appdb)
            password=self.config['password']
        )
    
    def disconnect(self):
        if self.connection:
            self.connection.close()
    
    def get_schema_info(self, schema_name: str = None) -> Dict:
        """대상 스키마의 딕셔너리 생성
        
        Args:
            schema_name: 생략 시 self.schema 사용
        """
        if schema_name is None:
            schema_name = self.schema
        
        cursor = self.connection.cursor()
        
        # 대상 스키마 정보 조회 (유저 권한으로 조회)
        cursor.execute("""
            SELECT 
                table_name,
                column_name,
                data_type,
                character_maximum_length,
                numeric_precision,
                numeric_scale,
                is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s
            ORDER BY table_name, ordinal_position
        """, (schema_name,))
        
        schema_dict = {}
        for row in cursor:
            table, column, dtype, char_len, num_prec, num_scale, nullable = row
            key = f"{table}.{column}"
            
            # 샘플 값 조회
            sample_cursor = self.connection.cursor()
            sample_cursor.execute(f"SELECT {column} FROM {schema_name}.{table} LIMIT 1")
            sample_row = sample_cursor.fetchone()
            sample_value = sample_row[0] if sample_row else None
            
            schema_dict[key] = {
                'table': table,
                'column': column,
                'data_type': dtype,
                'character_maximum_length': char_len,
                'numeric_precision': num_prec,
                'numeric_scale': num_scale,
                'is_nullable': nullable == 'YES',
                'sample_value': sample_value,
                'cast_hint': self._get_cast_hint(dtype)
            }
        
        return schema_dict
    
    def _get_cast_hint(self, data_type: str) -> Dict:
        """형변환 힌트 생성"""
        if data_type in ['integer', 'bigint', 'smallint']:
            return {
                'needs_cast_from_string': True,
                'cast_syntax': f'::{data_type.upper()}'
            }
        elif data_type in ['numeric', 'decimal']:
            return {
                'needs_cast_from_string': True,
                'cast_syntax': '::NUMERIC'
            }
        elif 'timestamp' in data_type or data_type == 'date':
            return {
                'needs_cast_from_string': True,
                'cast_syntax': '::TIMESTAMP'
            }
        else:
            return {'needs_cast_from_string': False}
    
    def validate_sql(self, sql: str) -> bool:
        """PREPARE로 구문 검증"""
        cursor = self.connection.cursor()
        try:
            # 바인드 변수를 $1, $2로 변환 필요
            cursor.execute(f"PREPARE test_stmt AS {sql}")
            cursor.execute("DEALLOCATE test_stmt")
            return True
        except Exception as e:
            return False
    
    def execute_test_case(self, sql: str, params: Dict) -> List[Dict]:
        cursor = self.connection.cursor()
        cursor.execute(sql, params)
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    def get_sql_dialect(self) -> str:
        return "postgres"
    
    def get_type_cast_syntax(self, target_type: str) -> str:
        return f"::{target_type}"
```

### 5.3 MySQL Target Plugin

```python
# oma/targets/mysql.py
import mysql.connector
from .base import TargetDB

class MySQLTarget(TargetDB):
    
    def connect(self):
        self.connection = mysql.connector.connect(
            host=self.config['host'],
            port=self.config['port'],
            database=self.config['database'],
            user=self.config['user'],
            password=self.config['password']
        )
    
    def get_sql_dialect(self) -> str:
        return "mysql"
    
    def get_type_cast_syntax(self, target_type: str) -> str:
        """MySQL은 CAST 함수 사용"""
        return f"CAST(? AS {target_type})"
    
    # ... 나머지 구현
```

---

## 6. 변환 규칙 외부화

### 6.1 함수 매핑 (YAML)

```yaml
# rules/oracle_to_postgres/functions.yaml
NVL:
  postgres: "COALESCE"
  example: "NVL(col, 'default') → COALESCE(col, 'default')"

DECODE:
  postgres: "CASE"
  pattern: "DECODE(col, v1, r1, v2, r2, default)"
  replacement: "CASE WHEN col = v1 THEN r1 WHEN col = v2 THEN r2 ELSE default END"

TO_CHAR:
  postgres: "to_char"  # 동일하지만 형식 차이
  note: "날짜 형식 변환 필요"

SYSDATE:
  postgres: "CURRENT_TIMESTAMP"

ROWNUM:
  postgres: "ROW_NUMBER() OVER()"
  note: "컨텍스트에 따라 LIMIT으로 대체 가능"
```

```yaml
# rules/oracle_to_mysql/functions.yaml
NVL:
  mysql: "IFNULL"
  example: "NVL(col, 'default') → IFNULL(col, 'default')"

DECODE:
  mysql: "CASE"
  # 동일

SYSDATE:
  mysql: "NOW()"
```

### 6.2 타입 매핑 (YAML)

```yaml
# rules/oracle_to_postgres/types.yaml
NUMBER:
  postgres: "NUMERIC"
  cast_required: true

VARCHAR2:
  postgres: "VARCHAR"
  cast_required: false

DATE:
  postgres: "TIMESTAMP"
  cast_required: true

CLOB:
  postgres: "TEXT"
```

---

## 7. Factory 패턴으로 플러그인 로드

```python
# oma/core/plugin_factory.py
from typing import Dict
from ..sources.base import SourceDB
from ..targets.base import TargetDB

class PluginFactory:
    """플러그인 팩토리"""
    
    _source_plugins = {
        'oracle': 'oma.sources.oracle.OracleSource',
        'edb': 'oma.sources.edb.EDBSource',
        'tibero': 'oma.sources.tibero.TiberoSource',
    }
    
    _target_plugins = {
        'postgres': 'oma.targets.postgres.PostgreSQLTarget',
        'mysql': 'oma.targets.mysql.MySQLTarget',
    }
    
    @classmethod
    def create_source(cls, db_type: str, config: Dict) -> SourceDB:
        """소스 DB 플러그인 생성"""
        if db_type not in cls._source_plugins:
            raise ValueError(f"Unsupported source DB: {db_type}")
        
        module_path, class_name = cls._source_plugins[db_type].rsplit('.', 1)
        module = __import__(module_path, fromlist=[class_name])
        plugin_class = getattr(module, class_name)
        
        return plugin_class(config)
    
    @classmethod
    def create_target(cls, db_type: str, config: Dict) -> TargetDB:
        """타겟 DB 플러그인 생성"""
        if db_type not in cls._target_plugins:
            raise ValueError(f"Unsupported target DB: {db_type}")
        
        module_path, class_name = cls._target_plugins[db_type].rsplit('.', 1)
        module = __import__(module_path, fromlist=[class_name])
        plugin_class = getattr(module, class_name)
        
        return plugin_class(config)
```

---

## 8. 메인 워크플로우 (Secrets Manager 통합)

```python
# scripts/run_conversion.py
from oma.core.plugin_factory import PluginFactory
from oma.core.workflow import ConversionWorkflow
from oma.utils.config import Config

def main():
    # 설정 로드 (properties + Secrets Manager)
    config = Config(
        config_path='config/oma.properties',
        aws_region='ap-northeast-2'
    )
    
    # 소스 DB 설정 (Secrets Manager에서 크리덴셜 조회)
    source_config = config.get_source_config()
    # {
    #   'db_type': 'oracle',
    #   'admin_user': 'SYSTEM',
    #   'admin_password': '***',
    #   'target_schema': 'APPDB',
    #   'host': '10.0.139.149',
    #   'port': 1521,
    #   'service_name': 'ORCLPDB1'
    # }
    
    # 타겟 DB 설정 (Secrets Manager에서 크리덴셜 조회)
    target_config = config.get_target_config()
    # {
    #   'db_type': 'postgres',
    #   'user': 'appdb',
    #   'password': '***',
    #   'schema': 'appdb',
    #   'host': 'omabox-stack-aurora-cluster.cluster-xxx.rds.amazonaws.com',
    #   'port': 5432,
    #   'database': 'appdb'
    # }
    
    # 플러그인 생성
    source_db = PluginFactory.create_source(
        source_config['db_type'],
        source_config
    )
    
    target_db = PluginFactory.create_target(
        target_config['db_type'],
        target_config
    )
    
    # 연결 테스트
    print("Testing source DB connection...")
    if not source_db.test_connection():
        raise RuntimeError("Source DB connection failed")
    print("✓ Source DB connected")
    
    print("Testing target DB connection...")
    if not target_db.test_connection():
        raise RuntimeError("Target DB connection failed")
    print("✓ Target DB connected")
    
    # 워크플로우 실행
    workflow = ConversionWorkflow(
        source_db=source_db,
        target_db=target_db,
        source_workspace=config.get('SOURCE_WORKSPACE'),
        target_workspace=config.get('TARGET_WORKSPACE'),
        work_dir=config.get('MAPPER_WORK_DIR'),
        llm_config={
            'region': config.get('BEDROCK_REGION'),
            'model_id': config.get('BEDROCK_MODEL_ID')
        }
    )
    
    workflow.run()

if __name__ == '__main__':
    main()
```

---

## 9. 확장 시나리오

### 새 소스 DB 추가 (예: Altibase)

1. **플러그인 구현**:
```python
# oma/sources/altibase.py
from .base import SourceDB

class AltibaseSource(SourceDB):
    # SourceDB 인터페이스 구현
    pass
```

2. **Factory 등록**:
```python
# oma/core/plugin_factory.py
_source_plugins = {
    'oracle': '...',
    'altibase': 'oma.sources.altibase.AltibaseSource',  # 추가
}
```

3. **변환 규칙 추가**:
```
rules/altibase_to_postgres/
  ├── functions.yaml
  ├── types.yaml
  └── syntax.yaml
```

### 새 타겟 DB 추가 (예: MariaDB)

동일한 방식으로 플러그인 + 규칙 추가

---

## 10. 기술 스택 요약

### 필수 Python 패키지

```txt
# requirements.txt

# DB 드라이버
cx-Oracle>=8.3.0           # Oracle
psycopg2-binary>=2.9.0     # PostgreSQL
mysql-connector-python>=8.0.0  # MySQL

# AWS
boto3>=1.26.0              # Bedrock + Secrets Manager
botocore>=1.29.0

# XML/YAML 파싱
lxml>=4.9.0
PyYAML>=6.0

# 데이터 처리
pandas>=2.0.0

# 멀티프로세싱
multiprocess>=0.70.0

# 설정
python-dotenv>=1.0.0

# 로깅
loguru>=0.7.0

# 타입 체킹 (개발용)
mypy>=1.0.0

# 테스트
pytest>=7.0.0
```

### Docker 이미지

```dockerfile
# Dockerfile
FROM python:3.10-slim

# Oracle Instant Client (필요 시)
RUN apt-get update && apt-get install -y \
    wget \
    unzip \
    libaio1

RUN wget https://download.oracle.com/otn_software/linux/instantclient/instantclient-basic-linux.zip \
    && unzip instantclient-basic-linux.zip -d /opt/oracle \
    && rm instantclient-basic-linux.zip

ENV LD_LIBRARY_PATH=/opt/oracle/instantclient_21_1:$LD_LIBRARY_PATH

# Python 패키지
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션
COPY . /app
WORKDIR /app

CMD ["python", "scripts/run_conversion.py"]
```

---

## 11. 장점 정리

### Plugin 아키텍처
- ✅ 새 DB 추가 용이 (플러그인만 구현)
- ✅ 기존 코드 수정 최소화
- ✅ 각 DB별 독립 테스트 가능

### Python + DB 드라이버
- ✅ 설치 간단 (pip)
- ✅ 크로스 플랫폼 (Linux/Mac/Windows)
- ✅ 에러 처리 표준화
- ✅ 코드 통합 용이

### 변환 규칙 외부화
- ✅ 코드 수정 없이 규칙 추가/변경
- ✅ DB 조합별 규칙 관리
- ✅ 버전 관리 용이

### Secrets Manager 통합
- ✅ 크리덴셜 중앙 관리 (코드에 하드코딩 없음)
- ✅ 소스는 관리자 계정, 타겟은 유저 계정 분리
- ✅ IAM 권한 기반 접근 제어
- ✅ 크리덴셜 로테이션 지원

### 확장성
- ✅ 소스: Oracle/EDB/Tibero/... 무한 확장
- ✅ 타겟: PostgreSQL/MySQL/... 무한 확장
- ✅ 변환 규칙: YAML로 관리
- ✅ DB 접속 전략: 소스(관리자)/타겟(유저) 명확히 분리

---

## 12. Secrets Manager 설정 가이드

### 시크릿 생성

**AWS CLI로 생성**:

```bash
# 소스 DB 시크릿 (관리자 계정 - 스키마 추출용)
aws secretsmanager create-secret \
  --name oma-source-admin \
  --description "OMA Source DB Admin Credentials (for schema extraction)" \
  --secret-string '{
    "admin_user": "SYSTEM",
    "admin_password": "admin_password_here",
    "target_schema": "APPDB",
    "host": "10.0.139.149",
    "port": 1521,
    "service_name": "ORCLPDB1",
    "db_type": "oracle"
  }' \
  --region ap-northeast-2

# 타겟 DB 시크릿 (서비스 계정 - 스키마 작업용)
aws secretsmanager create-secret \
  --name oma-target-service \
  --description "OMA Target DB Service Credentials (for schema operations)" \
  --secret-string '{
    "user": "appdb",
    "password": "user_password_here",
    "schema": "appdb",
    "host": "omabox-stack-aurora-cluster.cluster-xxx.rds.amazonaws.com",
    "port": 5432,
    "database": "appdb",
    "db_type": "postgres"
  }' \
  --region ap-northeast-2

# 선택적: 소스 서비스 계정 (일반적으로 마이그레이션에서는 미사용)
aws secretsmanager create-secret \
  --name oma-source-service \
  --description "OMA Source DB Service Credentials (optional)" \
  --secret-string '{
    "user": "app_user",
    "password": "service_password_here",
    "schema": "APPDB",
    "host": "10.0.139.149",
    "port": 1521,
    "service_name": "ORCLPDB1",
    "db_type": "oracle"
  }' \
  --region ap-northeast-2

# 선택적: 타겟 관리자 계정 (일반적으로 마이그레이션에서는 미사용)
aws secretsmanager create-secret \
  --name oma-target-admin \
  --description "OMA Target DB Admin Credentials (optional)" \
  --secret-string '{
    "admin_user": "postgres",
    "admin_password": "admin_password_here",
    "schema": "public",
    "host": "omabox-stack-aurora-cluster.cluster-xxx.rds.amazonaws.com",
    "port": 5432,
    "database": "appdb",
    "db_type": "postgres"
  }' \
  --region ap-northeast-2
```

### IAM 권한

**OMA 실행 역할에 필요한 권한**:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ],
      "Resource": [
        "arn:aws:secretsmanager:ap-northeast-2:*:secret:oma-source-*",
        "arn:aws:secretsmanager:ap-northeast-2:*:secret:oma-target-*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel"
      ],
      "Resource": [
        "arn:aws:bedrock:ap-northeast-2::foundation-model/global.anthropic.claude-opus-*"
      ]
    }
  ]
}
```

### 시크릿 업데이트

```bash
# 크리덴셜 변경 시
aws secretsmanager update-secret \
  --secret-id oma-source-admin \
  --secret-string '{
    "admin_user": "SYSTEM",
    "admin_password": "new_password",
    "target_schema": "APPDB",
    "host": "10.0.139.149",
    "port": 1521,
    "service_name": "ORCLPDB1",
    "db_type": "oracle"
  }'
```

### 시크릿 이름 규칙

**확정**:
```
기본:
- oma-source-admin    (소스 관리자 - 마이그레이션용)
- oma-source-service  (소스 서비스 - 선택적)
- oma-target-admin    (타겟 관리자 - 선택적)
- oma-target-service  (타겟 서비스 - 마이그레이션용)

환경별 확장 가능 (필요 시):
- oma-{env}-source-admin     (예: oma-prod-source-admin)
- oma-{env}-target-service   (예: oma-dev-target-service)
```

### 로컬 개발 시 (Secrets Manager 없이)

```python
# config/oma.properties에 추가
USE_SECRETS_MANAGER=false

# 로컬 개발 시 직접 지정
SOURCE_ADMIN_USER=SYSTEM
SOURCE_ADMIN_PASSWORD=password
SOURCE_TARGET_SCHEMA=APPDB
# ...
```

```python
# oma/utils/config.py 수정
def get_source_config(self) -> Dict:
    if self.common.get('USE_SECRETS_MANAGER', 'true').lower() == 'false':
        # properties 파일에서 직접 읽기
        return {
            'admin_user': self.common['SOURCE_ADMIN_USER'],
            'admin_password': self.common['SOURCE_ADMIN_PASSWORD'],
            # ...
        }
    else:
        # Secrets Manager 사용
        return self.secrets.get_source_credentials(source_type)
```

---

## 문서 버전
- 버전: 1.1
- 작성일: 2026-07-26
- 수정일: 2026-07-26
- 목적: OMA 아키텍처 설계 (Secrets Manager 통합)
