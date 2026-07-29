# OMA 파일 저장 위치 가이드

## 디렉토리 구조 전체 개요

```
${OMA_BASE_DIR}/                            # /home/ec2-user/workspace/oma/app
├─ projects/
│   └─ <APPLICATION_NAME>/                  # 예: wms — PROJECT_WORK_DIR (프로젝트별 격리)
│       ├─ output/
│       │   └─ schema_dictionary.json       # 스키마 딕셔너리 (타겟 DB)
│       │
│       ├─ mappers/                         # MAPPER_WORK_DIR
│       │   ├─ original/                     # Step 2: 원본 매퍼 복사
│       │   │   └─ [SOURCE_WORKSPACE 구조]
│       │   │
│       │   ├─ fragmented/                   # Step 3: SQL ID별 분할
│       │   │   ├─ mapping.json              # 조각-원본 매핑 정보
│       │   │   ├─ UserMapper_getUser.xml
│       │   │   ├─ UserMapper_insertUser.xml
│       │   │   └─ ...
│       │   │
│       │   ├─ converted/                    # Step 4: 변환 결과
│       │   │   ├─ UserMapper_getUser.xml
│       │   │   ├─ UserMapper_getUser.report.json
│       │   │   └─ ...
│       │   │
│       │   └─ merged/                       # Step 5: 병합 결과
│       │       ├─ UserMapper.xml
│       │       ├─ OrderMapper.xml
│       │       └─ ...
│       │
│       ├─ testcases/                       # Step 4: TC 파일 (TESTCASE_DIR)
│       │   ├─ UserMapper_searchUsers_tc001.json
│       │   ├─ UserMapper_searchUsers_tc002.json
│       │   ├─ OrderMapper_getOrders_tc001.json
│       │   └─ ...
│       │
│       ├─ reports/                         # Step 6: 리포트 (REPORT_DIR)
│       │   ├─ conversion-summary.json      # 전체 변환 요약
│       │   ├─ binding_failures.csv         # 바인딩 실패 (CSV)
│       │   ├─ binding_failures.json        # 바인딩 실패 (JSON)
│       │   ├─ binding_corrections.csv      # 수동 보정 (사용자 작성)
│       │   ├─ validation-errors.json       # 검증 에러
│       │   └─ manual-review-list.json      # 수동 검토 리스트
│       │
│       └─ .checkpoint.json                 # 재시작 지점 (CHECKPOINT_PATH)
│
└─ rules/                                    # 변환 규칙 (YAML)
    ├─ oracle_to_postgres/
    ├─ oracle_to_mysql/
    └─ ...
```

---

## 1. 스키마 딕셔너리

### 위치
```
${PROJECT_WORK_DIR}/output/schema_dictionary.json
```

### 설정
```properties
# oma.properties
SCHEMA_DICT_PATH=${PROJECT_WORK_DIR}/output/schema_dictionary.json
```

### 실제 경로 예시
```
/home/ec2-user/workspace/oma/app/projects/oma/output/schema_dictionary.json
```

### 용도
- 타겟 DB 스키마 메타데이터
- 테이블.컬럼 타입 정보
- 샘플 값
- 형변환 힌트

### 생성 시점
- **Phase 1**: 사전 준비 단계
- 타겟 DB 접속하여 스키마 정보 추출

### 크기
- 일반적으로 수백 KB ~ 수 MB
- 테이블/컬럼 수에 비례

---

## 2. 테스트 케이스 (TC) 파일

### 위치
```
${TESTCASE_DIR}/
```

### 설정
```properties
# oma.properties
MAPPER_WORK_DIR=${PROJECT_WORK_DIR}/mappers
```

### 실제 경로 예시
```
/home/ec2-user/workspace/oma/app/projects/oma/testcases/
```

### 파일명 규칙
```
{매퍼명}_{sqlId}_tc{번호}.json

예시:
- UserMapper_searchUsers_tc001.json
- UserMapper_searchUsers_tc002.json
- UserMapper_searchUsers_tc003.json
- OrderMapper_getOrders_tc001.json
- OrderMapper_complexQuery_tc001.json
```

### 파일 내용 예시
```json
{
  "test_case_id": "UserMapper_searchUsers_tc001",
  "mapper": "UserMapper",
  "sql_id": "searchUsers",
  "description": "userId만 있는 경우",
  "parameters": {
    "userId": 12345,
    "username": null,
    "status": null
  },
  "parameter_types": {
    "userId": "INTEGER",
    "username": "VARCHAR",
    "status": "CHAR(1)"
  },
  "expected_branches": ["userId != null"]
}
```

### 생성 시점
- **Phase 4**: SQL 변환 단계
- 동적 SQL이 있는 매퍼만 생성

### 개수
- 매퍼별, SQL ID별로 여러 개
- 동적 SQL 분기 수에 비례 (일반적으로 4-10개/쿼리)

### 크기
- 파일당 수백 바이트 ~ 수 KB
- 전체: 수십 ~ 수백 KB

---

## 3. 바인딩 실패 파일

### 위치
```
${REPORT_DIR}/
```

### 실제 경로 예시
```
/home/ec2-user/workspace/oma/app/projects/oma/reports/
```

### 파일 종류

#### 3.1 CSV 파일 (Excel용)
```
binding_failures.csv
```

**경로**:
```
/home/ec2-user/workspace/oma/app/projects/oma/reports/binding_failures.csv
```

**내용**:
```csv
mapper_file,sql_id,bind_variable,inferred_table,inferred_column,failure_reason,confidence,line_number,sql_fragment,suggestion
UserMapper.xml,searchUsers,userId,users,user_id,column_not_in_dictionary,high,15,"WHERE user_id = #{userId}",Add users.user_id to dictionary
OrderMapper.xml,complexQuery,statusCode,NULL,NULL,table_inference_failed,none,42,"WHERE status = #{statusCode}",Manually identify table
```

#### 3.2 JSON 파일 (상세)
```
binding_failures.json
```

**경로**:
```
/home/ec2-user/workspace/oma/app/projects/oma/reports/binding_failures.json
```

**내용**:
```json
{
  "binding_failures": [
    {
      "mapper_file": "UserMapper.xml",
      "sql_id": "searchUsers",
      "bind_variable": "userId",
      "inferred_mapping": {
        "table": "users",
        "column": "user_id",
        "confidence": "high"
      },
      "lookup_attempted": "users.user_id",
      "failure_reason": "column_not_in_dictionary",
      "line_number": 15,
      "sql_fragment": "WHERE user_id = #{userId}",
      "suggestion": "Verify users.user_id exists in target schema"
    }
  ],
  "summary": {
    "total_failures": 152,
    "by_reason": {
      "column_not_in_dictionary": 89,
      "table_inference_failed": 35,
      "ambiguous_mapping": 18,
      "view_column": 10
    },
    "by_severity": {
      "critical": 35,
      "high": 89,
      "medium": 28
    }
  }
}
```

#### 3.3 수동 보정 파일 (사용자 작성)
```
binding_corrections.csv
```

**경로**:
```
/home/ec2-user/workspace/oma/app/projects/oma/reports/binding_corrections.csv
```

**내용** (사용자가 작성):
```csv
mapper_file,sql_id,bind_variable,corrected_table,corrected_column,notes
OrderMapper.xml,complexQuery,statusCode,orders,status,확인 완료
ProductMapper.xml,searchProducts,categoryId,products,category_id,products 테이블 사용
```

### 생성 시점
- **Phase 4 완료 후**: 모든 변환 결과 집계
- 바인딩 실패가 발생한 경우만 생성

### 크기
- 실패 건수에 비례
- 일반적으로 수십 KB ~ 수백 KB

---

## 4. 기타 리포트 파일

### 4.1 전체 변환 요약
```
${REPORT_DIR}/conversion-summary.json
```

**경로**:
```
/home/ec2-user/workspace/oma/app/projects/oma/reports/conversion-summary.json
```

**내용**:
```json
{
  "total_mappers": 50,
  "total_sql_fragments": 327,
  "total_bind_variables": 1854,
  "conversion_success": 310,
  "conversion_partial": 12,
  "conversion_failed": 5,
  "binding_statistics": {
    "successful_mappings": 1702,
    "failed_mappings": 152,
    "success_rate": 91.8
  },
  "test_cases_generated": 1247
}
```

### 4.2 검증 에러
```
${REPORT_DIR}/validation-errors.json
```

### 4.3 수동 검토 리스트
```
${REPORT_DIR}/manual-review-list.json
```

---

## 5. 파일 접근 방법

### Python 코드에서

```python
from oma.utils.config import Config

config = Config('config/oma.properties', 'ap-northeast-2')

# 딕셔너리 경로
dict_path = config.get('SCHEMA_DICT_PATH')
# /home/ec2-user/workspace/oma/app/projects/oma/output/schema_dictionary.json

# 작업 디렉토리
work_dir = config.get('MAPPER_WORK_DIR')
# /home/ec2-user/workspace/oma/app/projects/oma/mappers

# TC 디렉토리
tc_dir = f"{work_dir}/testcases"
# /home/ec2-user/workspace/oma/app/projects/oma/testcases

# 바인딩 실패 CSV
binding_csv = f"{work_dir}/reports/binding_failures.csv"
# /home/ec2-user/workspace/oma/app/projects/oma/reports/binding_failures.csv

# 바인딩 실패 JSON
binding_json = f"{work_dir}/reports/binding_failures.json"
# /home/ec2-user/workspace/oma/app/projects/oma/reports/binding_failures.json
```

### 커맨드라인에서

```bash
# 딕셔너리 확인
cat /home/ec2-user/workspace/oma/app/projects/oma/output/schema_dictionary.json | jq '."users.user_id"'

# TC 파일 목록
ls -l /home/ec2-user/workspace/oma/app/projects/oma/testcases/

# TC 개수 확인
ls /home/ec2-user/workspace/oma/app/projects/oma/testcases/*.json | wc -l

# 바인딩 실패 확인 (CSV)
cat /home/ec2-user/workspace/oma/app/projects/oma/reports/binding_failures.csv

# 바인딩 실패 통계 (JSON)
cat /home/ec2-user/workspace/oma/app/projects/oma/reports/binding_failures.json | jq '.summary'

# Excel에서 열기 (로컬에서)
open /home/ec2-user/workspace/oma/app/projects/oma/reports/binding_failures.csv
```

---

## 6. 파일 생명주기

### 딕셔너리
```
생성: Phase 1 (사전 준비)
사용: Phase 4 (변환 시 조회)
유지: 영구 (스키마 변경 시 재생성)
크기: 수백 KB ~ 수 MB
```

### TC 파일
```
생성: Phase 4 (변환과 동시)
사용: Phase 6 (검증)
유지: 영구 (회귀 테스트용)
크기: 수십 ~ 수백 KB
개수: 동적 SQL 수 × 분기 조합
```

### 바인딩 실패
```
생성: Phase 4 완료 후 (집계)
사용: 수동 검토, 재변환
유지: 임시 (재변환 후 갱신)
크기: 수십 ~ 수백 KB
```

---

## 7. 디스크 공간 예측

### 일반적인 프로젝트 (50 매퍼, 300 SQL)

| 항목 | 크기 |
|------|------|
| 딕셔너리 | 1-2 MB |
| TC 파일 | 500 KB - 1 MB |
| 바인딩 실패 | 100-500 KB |
| 변환 리포트 | 500 KB |
| **합계** | **~3-5 MB** |

### 대규모 프로젝트 (500 매퍼, 3000 SQL)

| 항목 | 크기 |
|------|------|
| 딕셔너리 | 5-10 MB |
| TC 파일 | 5-10 MB |
| 바인딩 실패 | 1-5 MB |
| 변환 리포트 | 5 MB |
| **합계** | **~20-30 MB** |

---

## 8. 백업 권장 사항

### 중요 파일 (백업 필수)
- ✅ `schema_dictionary.json`: 재생성 가능하지만 시간 소요
- ✅ `testcases/*.json`: 재생성 가능하지만 동일 보장 어려움
- ✅ `binding_corrections.csv`: 수동 작성, 재현 불가

### 임시 파일 (백업 불필요)
- ❌ `binding_failures.csv/json`: 재변환 시 갱신
- ❌ `conversion-summary.json`: 재변환 시 재생성
- ❌ `fragmented/*`: 중간 결과

### 백업 스크립트
```bash
#!/bin/bash
BACKUP_DIR=/home/ec2-user/workspace/oma-backup/$(date +%Y%m%d_%H%M%S)
mkdir -p $BACKUP_DIR

# 딕셔너리
cp /home/ec2-user/workspace/oma/app/projects/oma/output/schema_dictionary.json $BACKUP_DIR/

# TC 파일
cp -r /home/ec2-user/workspace/oma/app/projects/oma/testcases $BACKUP_DIR/

# 수동 보정 파일 (있으면)
if [ -f /home/ec2-user/workspace/oma/app/projects/oma/reports/binding_corrections.csv ]; then
  cp /home/ec2-user/workspace/oma/app/projects/oma/reports/binding_corrections.csv $BACKUP_DIR/
fi

echo "Backup completed: $BACKUP_DIR"
```

---

## 9. 파일 위치 요약표

| 파일 | 경로 | 생성 시점 | 용도 |
|------|------|----------|------|
| **스키마 딕셔너리** | `${PROJECT_WORK_DIR}/output/schema_dictionary.json` | Phase 1 | 타겟 DB 메타데이터 |
| **TC 파일** | `${TESTCASE_DIR}/*.json` | Phase 4 | 동적 SQL 테스트 |
| **바인딩 실패 CSV** | `${REPORT_DIR}/binding_failures.csv` | Phase 4 후 | Excel 검토용 |
| **바인딩 실패 JSON** | `${REPORT_DIR}/binding_failures.json` | Phase 4 후 | 프로그래밍 처리용 |
| **수동 보정** | `${REPORT_DIR}/binding_corrections.csv` | 사용자 작성 | 재변환 입력 |
| **변환 요약** | `${REPORT_DIR}/conversion-summary.json` | Phase 6 | 전체 통계 |

---

## 문서 버전
- 버전: 1.0
- 작성일: 2026-07-26
- 목적: OMA 파일 저장 위치 가이드
