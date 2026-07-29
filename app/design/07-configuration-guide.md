# OMA Configuration Guide

## oma.properties 파일 구조

### 주요 변경 사항 (기존 대비)

| 항목 | 기존 | 변경 후 |
|------|------|---------|
| **DB 지정** | ORACLE_*, PGHOST, MYSQL_* | SOURCE_DB_TYPE, TARGET_DB_TYPE |
| **네이밍** | DB별 개별 이름 | SOURCE_*, TARGET_* 통일 |
| **크리덴셜** | properties 파일 직접 | Secrets Manager (기본) |
| **관리자/유저** | 구분 없음 | SOURCE_ADMIN_USER, TARGET_USER 분리 |
| **Python 전용** | ORACLE_HOME 있음 | ORACLE_HOME 제거 (Python 드라이버) |
| **딕셔너리** | ORACLE_DICT_PATH | SCHEMA_DICT_PATH (범용) |

---

## 설정 항목 상세

### 1. 기본 설정

```properties
[COMMON]
OMA_BASE_DIR=/home/ec2-user/workspace/oma/app/app
LANGUAGE=en
AWS_REGION=ap-northeast-2
```

**OMA_BASE_DIR**: OMA 설치 디렉토리
- 출력 파일, 작업 디렉토리 기준 경로
- 절대 경로 사용

**LANGUAGE**: 로그/메시지 언어
- `en`: English
- `ko`: 한국어

**AWS_REGION**: AWS 리소스 리전
- Secrets Manager, Bedrock 리전과 일치

---

### 2. LLM 설정

```properties
BEDROCK_REGION=ap-northeast-2
BEDROCK_MODEL_ID=global.anthropic.claude-opus-4-8
```

**BEDROCK_REGION**: Bedrock 서비스 리전
- AWS_REGION과 동일하게 설정 권장

**BEDROCK_MODEL_ID**: 사용할 Claude 모델
- `global.anthropic.claude-opus-4-8`: Opus 4.8 (권장)
- `global.anthropic.claude-sonnet-4-5`: Sonnet 4.5
- `global.anthropic.claude-haiku-4-5`: Haiku 4.5

**선택 기준**:
- 복잡한 SQL: Opus 4.8
- 일반 변환: Sonnet 4.5
- 빠른 처리: Haiku 4.5

---

### 3. DB 타입 지정 (핵심!)

```properties
SOURCE_DB_TYPE=oracle
TARGET_DB_TYPE=postgres
```

**SOURCE_DB_TYPE**: 소스 DB 종류
- `oracle`: Oracle Database
- `edb`: EDB Postgres Advanced Server (Oracle 호환)
- `tibero`: Tibero

**TARGET_DB_TYPE**: 타겟 DB 종류
- `postgres`: PostgreSQL
- `mysql`: MySQL

**지원 조합**:
| 소스 | 타겟 | 상태 |
|------|------|------|
| oracle | postgres | ✅ 지원 |
| oracle | mysql | ✅ 지원 |
| edb | postgres | ✅ 지원 |
| tibero | postgres | ✅ 지원 |
| tibero | mysql | ✅ 지원 |

---

### 4. 변환 설정

```properties
MAX_WORKERS=7
SOURCE_WORKSPACE=/home/ec2-user/workspace/source
TARGET_WORKSPACE=/home/ec2-user/workspace/target

# 프로젝트별 작업 디렉토리 (멀티 프로젝트 격리)
PROJECT_WORK_DIR=${OMA_BASE_DIR}/projects/${APPLICATION_NAME}
MAPPER_WORK_DIR=${PROJECT_WORK_DIR}/mappers
SCHEMA_DICT_PATH=${PROJECT_WORK_DIR}/output/schema_dictionary.json
TESTCASE_DIR=${PROJECT_WORK_DIR}/testcases
REPORT_DIR=${PROJECT_WORK_DIR}/reports
CHECKPOINT_PATH=${PROJECT_WORK_DIR}/.checkpoint.json
```

**MAX_WORKERS**: 병렬 처리 워커 수
- CPU 코어 수 - 2 권장
- 예: 8코어 → 6-7
- LLM 호출 수와 비례

**SOURCE_WORKSPACE**: 소스 애플리케이션 경로
- MyBatis 매퍼 XML 파일이 있는 프로젝트 루트

**TARGET_WORKSPACE**: 변환 결과 복사 경로
- 변환된 매퍼가 저장될 위치

**PROJECT_WORK_DIR**: 프로젝트별 작업 루트
- `${OMA_BASE_DIR}/projects/${APPLICATION_NAME}` 로 해석됨
- 아래 모든 작업/산출물 경로의 기준. 프로젝트마다 격리되어 동시 처리 가능
- 코드 모듈(converter/utils/...)은 프로젝트 공통이며 여기 포함되지 않음

**MAPPER_WORK_DIR**: 매퍼 작업 디렉토리
- 분할/변환/병합 중간 결과 저장
- 구조:
  ```
  projects/<APPLICATION_NAME>/
    ├─ mappers/
    │   ├─ original/      (원본 복사)
    │   ├─ fragmented/    (SQL ID별 분할)
    │   ├─ converted/     (변환 결과)
    │   └─ merged/        (병합 결과)
    ├─ output/            (schema_dictionary.json)
    ├─ testcases/         (TC 파일)
    ├─ reports/           (리포트)
    └─ .checkpoint.json   (재시작 지점)
  ```

**SCHEMA_DICT_PATH**: 스키마 딕셔너리 파일 경로
- 타겟 DB 메타데이터 JSON
- 형변환 판단에 사용

**TESTCASE_DIR / REPORT_DIR / CHECKPOINT_PATH**: TC / 리포트 / 체크포인트 경로
- 모두 `PROJECT_WORK_DIR` 아래에 위치 (mappers와 형제 레벨)

---

### 5. Secrets Manager 사용

```properties
USE_SECRETS_MANAGER=true
```

**USE_SECRETS_MANAGER**: Secrets Manager 사용 여부
- `true` (기본): AWS Secrets Manager에서 크리덴셜 조회
- `false`: properties 파일의 직접 설정값 사용 (로컬 개발용)

**시크릿 이름** (확정):
```
# 마이그레이션에서 사용
oma-source-admin     # 소스 관리자 계정 (스키마 추출용)
oma-target-service   # 타겟 서비스 계정 (스키마 작업용)

# 선택적 (일반적으로 미사용)
oma-source-service   # 소스 서비스 계정
oma-target-admin     # 타겟 관리자 계정
```

**설정 파일에서 지정**:
```properties
SOURCE_SECRET_NAME=oma-source-admin
TARGET_SECRET_NAME=oma-target-service
```

**시크릿 JSON 구조**:

소스 관리자 (oma-source-admin):
```json
{
  "admin_user": "SYSTEM",
  "admin_password": "***",
  "target_schema": "APPDB",
  "host": "10.0.139.149",
  "port": 1521,
  "service_name": "ORCLPDB1",
  "db_type": "oracle"
}
```

타겟 서비스 (oma-target-service):
```json
{
  "user": "appdb",
  "password": "***",
  "schema": "appdb",
  "host": "omabox-cluster.xxx.rds.amazonaws.com",
  "port": 5432,
  "database": "appdb",
  "db_type": "postgres"
}
```

---

### 6. 로컬 개발 설정 (USE_SECRETS_MANAGER=false)

```properties
# Source DB (Admin credentials)
SOURCE_HOST=10.0.139.149
SOURCE_PORT=1521
SOURCE_DATABASE=ORCLPDB1
SOURCE_CONN_TYPE=service
SOURCE_ADMIN_USER=SYSTEM
SOURCE_ADMIN_PASSWORD=admin_password
SOURCE_TARGET_SCHEMA=APPDB

# Target DB (User credentials)
TARGET_HOST=localhost
TARGET_PORT=5432
TARGET_DATABASE=appdb
TARGET_SCHEMA=appdb
TARGET_USER=appdb
TARGET_PASSWORD=user_password
```

**소스 DB**:
- `SOURCE_ADMIN_USER`: 관리자 계정 (예: SYSTEM, postgres)
- `SOURCE_ADMIN_PASSWORD`: 관리자 비밀번호
- `SOURCE_TARGET_SCHEMA`: 추출할 대상 스키마/유저

**타겟 DB**:
- `TARGET_USER`: 대상 유저 계정
- `TARGET_PASSWORD`: 유저 비밀번호
- `TARGET_SCHEMA`: 작업할 스키마

**주의**: 
- 로컬 개발/테스트 용도로만 사용
- 프로덕션에서는 반드시 Secrets Manager 사용
- Git에 커밋하지 말 것 (.gitignore 추가)

---

## 사용 예시

### 예시 1: Oracle → PostgreSQL (Secrets Manager)

```properties
[COMMON]
SOURCE_DB_TYPE=oracle
TARGET_DB_TYPE=postgres
USE_SECRETS_MANAGER=true
AWS_REGION=ap-northeast-2
BEDROCK_MODEL_ID=global.anthropic.claude-opus-4-8
```

**필요한 시크릿**:
- `oma-source-admin`: Oracle 관리자 크리덴셜
- `oma-target-service`: PostgreSQL 서비스 크리덴셜

---

### 예시 2: Tibero → MySQL (Secrets Manager)

```properties
[COMMON]
SOURCE_DB_TYPE=tibero
TARGET_DB_TYPE=mysql
USE_SECRETS_MANAGER=true
```

**필요한 시크릿**:
- `oma-source-admin`: Tibero 관리자 크리덴셜
- `oma-target-service`: MySQL 서비스 크리덴셜

---

### 예시 3: 로컬 개발 (Secrets Manager 없이)

```properties
[COMMON]
SOURCE_DB_TYPE=oracle
TARGET_DB_TYPE=postgres
USE_SECRETS_MANAGER=false

SOURCE_HOST=localhost
SOURCE_PORT=1521
SOURCE_ADMIN_USER=SYSTEM
SOURCE_ADMIN_PASSWORD=oracle
SOURCE_TARGET_SCHEMA=TESTUSER
SOURCE_DATABASE=ORCLPDB1
SOURCE_CONN_TYPE=service

TARGET_HOST=localhost
TARGET_PORT=5432
TARGET_DATABASE=testdb
TARGET_SCHEMA=public
TARGET_USER=testuser
TARGET_PASSWORD=postgres
```

---

## DB별 특수 설정

### Oracle

```properties
SOURCE_DB_TYPE=oracle
SOURCE_CONN_TYPE=service
SOURCE_DATABASE=ORCLPDB1  # service_name

# 또는 SID 사용
SOURCE_CONN_TYPE=sid
SOURCE_DATABASE=ORCL
```

**SOURCE_CONN_TYPE**:
- `service`: service_name 사용 (PDB, 클라우드)
- `sid`: SID 사용 (전통적)

### EDB Postgres

```properties
SOURCE_DB_TYPE=edb
SOURCE_DATABASE=edb  # database name
```

EDB는 PostgreSQL 호환이므로 PostgreSQL과 동일한 연결 방식

### Tibero

```properties
SOURCE_DB_TYPE=tibero
SOURCE_DATABASE=tibero  # SID
SOURCE_PORT=8629  # 기본 포트
```

### MySQL

```properties
TARGET_DB_TYPE=mysql
TARGET_PORT=3306
TARGET_DATABASE=appdb
TARGET_SCHEMA=appdb  # MySQL은 database=schema
```

MySQL에서는 database와 schema가 동일 개념

---

## 환경별 설정 파일

### 개발 환경

```bash
cp oma.properties oma.properties.dev

# oma.properties.dev
USE_SECRETS_MANAGER=false
SOURCE_HOST=localhost
TARGET_HOST=localhost
BEDROCK_MODEL_ID=global.anthropic.claude-haiku-4-5  # 빠른 테스트
MAX_WORKERS=3
```

### 프로덕션 환경

```bash
cp oma.properties oma.properties.prod

# oma.properties.prod
USE_SECRETS_MANAGER=true
AWS_REGION=ap-northeast-2
BEDROCK_MODEL_ID=global.anthropic.claude-opus-4-8
MAX_WORKERS=7
```

### 실행 시 지정

```bash
# 개발 환경
python scripts/run_conversion.py --config config/oma.properties.dev

# 프로덕션 환경
python scripts/run_conversion.py --config config/oma.properties.prod
```

---

## 설정 검증

### 설정 파일 검증 스크립트

```python
# scripts/validate_config.py
from oma.utils.config import Config

def main():
    config = Config('config/oma.properties', 'ap-northeast-2')
    
    # 소스 DB 연결 테스트
    print("Testing source DB connection...")
    source_config = config.get_source_config()
    print(f"  Type: {source_config['db_type']}")
    print(f"  Host: {source_config['host']}")
    print(f"  Schema: {source_config['target_schema']}")
    
    # 타겟 DB 연결 테스트
    print("\nTesting target DB connection...")
    target_config = config.get_target_config()
    print(f"  Type: {target_config['db_type']}")
    print(f"  Host: {target_config['host']}")
    print(f"  Schema: {target_config['schema']}")
    
    # Bedrock 설정
    print("\nBedrock configuration:")
    print(f"  Region: {config.get('BEDROCK_REGION')}")
    print(f"  Model: {config.get('BEDROCK_MODEL_ID')}")
    
    print("\n✓ Configuration validated successfully")

if __name__ == '__main__':
    main()
```

**실행**:
```bash
python scripts/validate_config.py
```

---

## 마이그레이션 가이드 (기존 → 신규)

### 기존 oma.properties에서 변경

```bash
# 백업
cp oma.properties oma.properties.old

# 신규 파일 생성
cat > oma.properties << EOF
[COMMON]
# DB 타입 추가
SOURCE_DB_TYPE=oracle
TARGET_DB_TYPE=postgres

# Secrets Manager 사용
USE_SECRETS_MANAGER=true

# 기존 설정 유지
OMA_BASE_DIR=/home/ec2-user/workspace/oma/app/app
AWS_REGION=ap-northeast-2
BEDROCK_REGION=ap-northeast-2
BEDROCK_MODEL_ID=global.anthropic.claude-opus-4-8
MAX_WORKERS=7
SOURCE_WORKSPACE=/home/ec2-user/workspace/source
TARGET_WORKSPACE=/home/ec2-user/workspace/target
PROJECT_WORK_DIR=\${OMA_BASE_DIR}/projects/\${APPLICATION_NAME}
MAPPER_WORK_DIR=\${PROJECT_WORK_DIR}/mappers
SCHEMA_DICT_PATH=\${PROJECT_WORK_DIR}/output/schema_dictionary.json

[oma]
APPLICATION_NAME=oma
EOF
```

### 매핑 테이블

| 기존 항목 | 신규 항목 | 비고 |
|----------|----------|------|
| ORACLE_HOST | SOURCE_HOST | 로컬 개발용 |
| ORACLE_USER | SOURCE_ADMIN_USER | 관리자 계정 |
| ORACLE_SCHEMA | SOURCE_TARGET_SCHEMA | 대상 스키마 |
| PGHOST | TARGET_HOST | 로컬 개발용 |
| PGUSER | TARGET_USER | 유저 계정 |
| PGSCHEMA | TARGET_SCHEMA | 대상 스키마 |
| ORACLE_HOME | (삭제) | Python 드라이버 사용 |
| ORACLE_DICT_PATH | SCHEMA_DICT_PATH | 범용 이름 |
| TARGET_DB_TYPE | TARGET_DB_TYPE | 그대로 유지 |

---

## 보안 고려사항

### DO ✅
- Secrets Manager 사용 (프로덕션)
- IAM 역할 기반 접근
- 최소 권한 원칙
- 시크릿 로테이션 설정

### DON'T ❌
- properties 파일에 비밀번호 직접 입력 (프로덕션)
- Git에 크리덴셜 커밋
- 관리자 비밀번호 공유
- Secrets Manager 없이 프로덕션 운영

### .gitignore 추가

```gitignore
# OMA Configuration
oma.properties.local
oma.properties.dev
*.properties.backup
*.properties.old

# Secrets
*.key
*.pem
credentials.json
```

---

## 트러블슈팅

### 문제: Secrets Manager 접근 실패

**증상**:
```
ClientError: An error occurred (AccessDeniedException) 
when calling the GetSecretValue operation
```

**해결**:
1. IAM 역할에 `secretsmanager:GetSecretValue` 권한 확인
2. 시크릿 이름 확인 (`oma-source-admin`, `oma-target-service`)
3. AWS_REGION 일치 확인
4. properties 파일의 SOURCE_SECRET_NAME, TARGET_SECRET_NAME 확인

### 문제: 소스 DB 연결 실패

**증상**:
```
ORA-01017: invalid username/password
```

**해결**:
1. SOURCE_ADMIN_USER가 관리자 권한인지 확인
2. 시크릿의 admin_user, admin_password 확인
3. 방화벽/보안그룹 확인

### 문제: 타겟 스키마 조회 실패

**증상**:
```
permission denied for schema appdb
```

**해결**:
1. TARGET_USER가 TARGET_SCHEMA에 접근 권한 있는지 확인
2. 시크릿의 user, password 확인
3. PostgreSQL: `GRANT USAGE ON SCHEMA appdb TO appdb`

---

## 문서 버전
- 버전: 1.0
- 작성일: 2026-07-26
- 목적: oma.properties 설정 가이드
