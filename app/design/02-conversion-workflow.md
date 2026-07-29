# Oracle → PostgreSQL 매퍼 변환 전체 플로우

## 환경 구성 (oma.properties 기준)

```
SOURCE_WORKSPACE: /home/ec2-user/workspace/source
  └─ 원본 자바 애플리케이션 (MyBatis 매퍼 포함)

TARGET_WORKSPACE: /home/ec2-user/workspace/target
  └─ 변환된 애플리케이션 복사 목적지

OMA_BASE_DIR: /home/ec2-user/workspace/oma/app/app
  └─ projects/<APPLICATION_NAME>/ (PROJECT_WORK_DIR - 프로젝트별 격리)
      ├─ output/
      │   └─ schema_dictionary.json (스키마 딕셔너리)
      ├─ mappers/ (MAPPER_WORK_DIR - 작업 디렉토리)
      │   ├─ original/        (Step 2: 원본 매퍼 복사본)
      │   ├─ fragmented/      (Step 3: SQL ID별 분할)
      │   ├─ converted/       (Step 4: 변환된 SQL 조각)
      │   └─ merged/          (Step 5: 병합된 매퍼)
      ├─ testcases/           (Step 4: 동적 SQL TC)
      ├─ reports/             (Step 6: 검증 리포트)
      └─ .checkpoint.json     (재시작 지점)
```

---

## 전체 워크플로우

### Phase 1: 사전 준비

#### Step 1-1: 스키마 딕셔너리 생성
**입력**:
- PostgreSQL 연결 정보 (PGHOST, PGDATABASE, PGSCHEMA)

**작업**:
1. PostgreSQL 스키마 메타데이터 추출
   ```sql
   SELECT 
     table_name,
     column_name,
     data_type,
     character_maximum_length,
     numeric_precision,
     numeric_scale,
     is_nullable
   FROM information_schema.columns
   WHERE table_schema = '${PGSCHEMA}'
   ```

2. 각 테이블에서 샘플 데이터 1건 조회
   ```sql
   SELECT * FROM ${PGSCHEMA}.${table_name} LIMIT 1;
   ```

3. 형변환 힌트 생성
   - integer/bigint → needs_cast_from_string: true
   - character(n) → needs_trim: true
   - timestamp/date → 날짜 캐스팅 문법

**출력**:
- `${PROJECT_WORK_DIR}/output/oracle_dictionary.json`

**딕셔너리 구조**:
```json
{
  "users.user_id": {
    "table": "users",
    "column": "user_id",
    "data_type": "integer",
    "is_nullable": false,
    "numeric_precision": 32,
    "sample_value": 12345,
    "cast_hint": {
      "needs_cast_from_string": true,
      "cast_syntax": "::INTEGER",
      "performance_note": "리터럴은 숫자로 변환 권장"
    }
  }
}
```

#### Step 1-2: 조회 함수 준비
**구현 옵션**:

**옵션 A**: 스탠드얼론 스크립트
```javascript
// ${PROJECT_WORK_DIR}/scripts/schema-lookup.js
const dict = require('../output/oracle_dictionary.json');

function lookup(tableColumn) {
  const key = tableColumn.toLowerCase();
  return dict[key] || { found: false };
}

// CLI: node schema-lookup.js "users.user_id"
```

**옵션 B**: LLM이 직접 JSON 읽기
- LLM이 Read tool로 dictionary.json 읽어서 직접 파싱
- 별도 스크립트 불필요

**권장**: 옵션 B (간단하고 LLM이 충분히 처리 가능)

---

### Phase 2: 매퍼 수집 및 원본 복사

#### Step 2-1: 매퍼 파일 찾기
**작업**:
```bash
find ${SOURCE_WORKSPACE} -name "*Mapper.xml" -o -name "*mapper.xml"
```

**출력**:
- 매퍼 파일 경로 리스트
- 매퍼 파일 개수
- 복잡도 분석 (선택사항)

#### Step 2-2: 원본 복사
**작업**:
- SOURCE_WORKSPACE의 매퍼를 MAPPER_WORK_DIR/original/로 복사
- 디렉토리 구조 유지 (프로젝트 구조 보존)

**예시**:
```
${SOURCE_WORKSPACE}/src/main/resources/mapper/UserMapper.xml
  → ${MAPPER_WORK_DIR}/original/mapper/UserMapper.xml
```

**목적**:
- 원본 보존 (롤백/비교용)
- 작업 격리 (소스 워크스페이스 보호)

---

### Phase 3: 매퍼 분할 (핵심)

#### Step 3-1: SQL ID 추출
**입력**: `${MAPPER_WORK_DIR}/original/**/*.xml`

**작업**:
MyBatis 매퍼 XML 파싱하여 각 SQL 구문 추출

**매퍼 구조 예시**:
```xml
<mapper namespace="com.example.UserMapper">
  <select id="getUser" resultType="User">
    SELECT * FROM users WHERE user_id = #{userId}
  </select>
  
  <insert id="insertUser">
    INSERT INTO users (username, status) VALUES (#{username}, #{status})
  </insert>
  
  <update id="updateUser">
    UPDATE users SET status = #{status} WHERE user_id = #{userId}
  </update>
</mapper>
```

#### Step 3-2: 조각 파일 생성
**출력**: `${MAPPER_WORK_DIR}/fragmented/`

**파일명 규칙**: `{매퍼명}_{sqlId}.xml` 또는 `.sql`

**예시**:
```
fragmented/
  ├─ UserMapper_getUser.xml
  ├─ UserMapper_insertUser.xml
  ├─ UserMapper_updateUser.xml
  ├─ OrderMapper_getOrder.xml
  └─ OrderMapper_listOrders.xml
```

**조각 파일 내용**:
```xml
<!-- UserMapper_getUser.xml -->
<sql-fragment>
  <metadata>
    <original-mapper>com.example.UserMapper</original-mapper>
    <sql-id>getUser</sql-id>
    <sql-type>select</sql-type>
    <result-type>User</result-type>
  </metadata>
  <sql>
    SELECT * FROM users WHERE user_id = #{userId}
  </sql>
</sql-fragment>
```

**또는 순수 SQL만 저장** (더 간단):
```sql
-- Metadata: UserMapper.getUser (select)
SELECT * FROM users WHERE user_id = #{userId}
```

#### Step 3-3: 메타데이터 매핑 파일 생성
**출력**: `${MAPPER_WORK_DIR}/fragmented/mapping.json`

**구조**:
```json
{
  "UserMapper.xml": {
    "namespace": "com.example.UserMapper",
    "fragments": [
      {
        "sql_id": "getUser",
        "sql_type": "select",
        "result_type": "User",
        "fragment_file": "UserMapper_getUser.xml"
      },
      {
        "sql_id": "insertUser",
        "sql_type": "insert",
        "fragment_file": "UserMapper_insertUser.xml"
      }
    ]
  }
}
```

**목적**:
- 조각과 원본 매퍼 연결 정보 보존
- Phase 5 병합 시 사용

---

### Phase 4: SQL 변환 (LLM 핵심 작업)

#### Step 4-1: 변환 준비
**입력**:
- 조각 파일들: `${MAPPER_WORK_DIR}/fragmented/*.xml`
- 스키마 딕셔너리: `${PROJECT_WORK_DIR}/output/oracle_dictionary.json`
- 변환 프롬프트: `01-migration-principles.md`

#### Step 4-2: 병렬 변환
**프로세스**:
```
각 조각 파일에 대해 독립적으로:
1. 조각 파일 읽기
2. LLM 변환 실행
   - 딕셔너리 조회
   - 구문 변환
   - 형변환 추가
3. 변환 결과 저장
4. 변환 리포트 생성
```

**병렬 처리**:
- Workflow pipeline 사용
- MAX_WORKERS=7 (설정 파일 기준)
- 파일별 독립 변환 (격리: worktree 또는 파일 단위)

**LLM 프롬프트 구조**:
```
# 입력
- SQL 조각: UserMapper_getUser.xml
- 딕셔너리: oracle_dictionary.json
- 변환 규칙: 01-migration-principles.md

# 작업
1. SQL 파싱 및 컬럼 추출
2. 각 컬럼 딕셔너리 조회
3. Oracle 구문 → PostgreSQL 변환
4. 형변환 명시적 추가
5. 구조화된 출력

# 출력
- 변환된 SQL
- 변경 사항 로그
- Warning 리스트
```

#### Step 4-3: 변환 결과 저장
**출력**: `${MAPPER_WORK_DIR}/converted/`

**파일 구조**:
```
converted/
  ├─ UserMapper_getUser.xml          (변환된 SQL)
  ├─ UserMapper_getUser.report.json  (변환 리포트)
  ├─ UserMapper_insertUser.xml
  ├─ UserMapper_insertUser.report.json
  └─ ...
```

**변환된 SQL 예시**:
```xml
<sql-fragment>
  <metadata>
    <original-mapper>com.example.UserMapper</original-mapper>
    <sql-id>getUser</sql-id>
    <sql-type>select</sql-type>
    <result-type>User</result-type>
    <conversion-status>success</conversion-status>
  </metadata>
  <sql>
    SELECT * FROM users WHERE user_id = #{userId}::INTEGER
  </sql>
</sql-fragment>
```

**변환 리포트 예시**:
```json
{
  "fragment": "UserMapper_getUser.xml",
  "status": "success",
  "lookups_performed": [
    {
      "column": "users.user_id",
      "type_found": "integer",
      "actions_taken": ["cast #{userId} to INTEGER"]
    }
  ],
  "changes": [
    {
      "original": "user_id = #{userId}",
      "converted": "user_id = #{userId}::INTEGER",
      "reason": "users.user_id is INTEGER, explicit cast for type safety"
    }
  ],
  "warnings": []
}
```

#### Step 4-4: 에러 처리
**실패 케이스**:
- 딕셔너리에 없는 컬럼
- 복잡한 구문 (CONNECT BY, MERGE)
- ${} 동적 SQL
- LLM 변환 실패

**처리 방식**:
```json
{
  "fragment": "OrderMapper_complexQuery.xml",
  "status": "partial",
  "warnings": [
    {
      "column": "unknown_table.col",
      "issue": "Column not found in dictionary",
      "action": "Kept original, flagged for manual review"
    }
  ],
  "manual_review_required": true
}
```

**결과**:
- 변환 가능한 부분은 변환
- 불가능한 부분은 원본 유지 + 플래그
- 프로세스 중단하지 않음

---

### Phase 5: 매퍼 병합

#### Step 5-1: 조각 재조립
**입력**:
- 변환된 조각들: `${MAPPER_WORK_DIR}/converted/*.xml`
- 매핑 정보: `${MAPPER_WORK_DIR}/fragmented/mapping.json`

**작업**:
```
각 원본 매퍼별로:
1. mapping.json에서 해당 매퍼의 조각 리스트 조회
2. 각 조각의 변환 결과 읽기
3. 원본 매퍼 구조로 재조립
4. XML 포맷팅
```

**출력**: `${MAPPER_WORK_DIR}/merged/`

**병합 결과 예시**:
```xml
<mapper namespace="com.example.UserMapper">
  <select id="getUser" resultType="User">
    SELECT * FROM users WHERE user_id = #{userId}::INTEGER
  </select>
  
  <insert id="insertUser">
    INSERT INTO users (username, status) VALUES (#{username}, #{status})
  </insert>
  
  <update id="updateUser">
    UPDATE users SET status = #{status} WHERE user_id = #{userId}::INTEGER
  </update>
</mapper>
```

#### Step 5-2: 병합 검증
**체크 항목**:
- 모든 SQL ID 포함 확인
- XML 문법 검증
- 누락된 조각 확인
- 변환 실패 조각 표시

---

### Phase 6: 검증

#### Step 6-1: 구문 검증
**작업**:
```sql
-- PostgreSQL에서 각 SQL PREPARE 테스트
PREPARE stmt AS 
  SELECT * FROM users WHERE user_id = $1::INTEGER;

DEALLOCATE stmt;
```

**결과**:
- 구문 에러 있는 매퍼 리스트
- 에러 메시지

#### Step 6-2: 의미적 검증 (선택적)
**LLM 독립 검증**:
```
원본 SQL과 변환 SQL 비교:
- 의미적 동등성
- NULL 처리 동일성
- 성능 영향 분석
```

#### Step 6-3: 커버리지 리포트
**생성**:
```json
{
  "total_mappers": 50,
  "total_sql_fragments": 327,
  "conversion_success": 310,
  "conversion_partial": 12,
  "conversion_failed": 5,
  "dictionary_coverage": "95.4%",
  "manual_review_required": [
    {
      "mapper": "ComplexMapper.xml",
      "sql_id": "hierarchyQuery",
      "reason": "CONNECT BY not auto-converted"
    }
  ]
}
```

---

### Phase 7: 타겟 복사

#### Step 7-1: 디렉토리 구조 복사
**작업**:
```bash
# SOURCE_WORKSPACE 전체 복사
cp -r ${SOURCE_WORKSPACE} ${TARGET_WORKSPACE}

# 매퍼만 교체
# TARGET_WORKSPACE의 매퍼를 merged/ 결과로 덮어쓰기
```

#### Step 7-2: 선택적 복사
**전략 A**: 전체 복사 후 매퍼 교체
```
1. SOURCE → TARGET 전체 복사
2. merged/*.xml → TARGET의 해당 경로로 복사
```

**전략 B**: 매퍼만 복사 (권장)
```
1. TARGET은 이미 존재한다고 가정
2. merged/*.xml만 TARGET의 매퍼 디렉토리로 복사
3. 타임스탬프/백업 관리
```

#### Step 7-3: 변환 리포트 복사
**출력**:
```
${TARGET_WORKSPACE}/
  ├─ [원본 앱 구조]
  └─ .oma/
      ├─ conversion-report.json  (전체 리포트)
      ├─ manual-review.json      (수동 검토 리스트)
      └─ coverage.json           (커버리지)
```

---

## 디렉토리 구조 상세

### PROJECT_WORK_DIR 최종 구조
```
${PROJECT_WORK_DIR}/            # projects/<APPLICATION_NAME>/ (프로젝트별 격리)
├─ mappers/                     # MAPPER_WORK_DIR
│   ├─ original/                # Step 2: 원본 복사
│   │   └─ [SOURCE_WORKSPACE 매퍼 구조]
│   │
│   ├─ fragmented/              # Step 3: SQL ID별 분할
│   │   ├─ mapping.json         # 조각-원본 매핑 정보
│   │   ├─ UserMapper_getUser.xml
│   │   ├─ UserMapper_insertUser.xml
│   │   └─ ...
│   │
│   ├─ converted/               # Step 4: 변환 결과
│   │   ├─ UserMapper_getUser.xml
│   │   ├─ UserMapper_getUser.report.json
│   │   ├─ UserMapper_insertUser.xml
│   │   ├─ UserMapper_insertUser.report.json
│   │   └─ ...
│   │
│   └─ merged/                  # Step 5: 병합 결과
│       ├─ UserMapper.xml
│       ├─ OrderMapper.xml
│       └─ ...
│
├─ output/                      # schema_dictionary.json (SCHEMA_DICT_PATH)
├─ testcases/                   # Step 4: TC 파일 (TESTCASE_DIR)
├─ reports/                     # Step 6: 검증 리포트 (REPORT_DIR)
│   ├─ conversion-summary.json
│   ├─ validation-errors.json
│   └─ manual-review-list.json
└─ .checkpoint.json             # 재시작 지점 (CHECKPOINT_PATH)
```

---

## 보완 및 최적화 제안

### 1. 체크포인트 시스템
**목적**: 중단 시 재개 가능

**구현**:
```json
// ${CHECKPOINT_PATH}
{
  "last_completed_phase": "conversion",
  "processed_fragments": ["UserMapper_getUser", "UserMapper_insertUser"],
  "failed_fragments": ["OrderMapper_complex"],
  "timestamp": "2026-07-26T10:30:00Z"
}
```

**효과**:
- 실패 시 마지막 단계부터 재개
- 처리된 조각 스킵 가능

### 2. 증분 변환 (Incremental Conversion)
**시나리오**: 소스가 계속 변경되는 경우

**구현**:
- 원본 매퍼 해시값 저장
- 변경된 매퍼만 재변환
- 나머지는 캐시 사용

### 3. 변환 품질 레벨
**레벨 1**: 빠른 변환
- low effort
- 단순 구문만 변환
- 형변환 최소

**레벨 2**: 표준 변환 (기본)
- medium effort
- 구문 + 형변환
- 딕셔너리 조회

**레벨 3**: 철저한 변환
- high effort
- 의미적 검증 포함
- 성능 최적화 제안

### 4. 롤백 메커니즘
**구현**:
```bash
# 각 단계별 스냅샷
${MAPPER_WORK_DIR}/.snapshots/
  ├─ phase2_original.tar.gz
  ├─ phase3_fragmented.tar.gz
  ├─ phase4_converted.tar.gz
  └─ phase5_merged.tar.gz
```

**효과**:
- 특정 단계로 롤백 가능
- 디버깅 용이

### 5. 병렬 처리 최적화
**전략**:
- 큰 매퍼 (SQL > 10개) → 분할 후 병렬
- 작은 매퍼 → 통째로 변환 (분할 오버헤드 제거)

**동적 조절**:
```
if (sql_count <= 5):
  → 분할 없이 매퍼 전체 변환
else:
  → 분할 후 병렬 변환
```

### 6. 수동 검토 워크플로우
**구현**:
```
${MAPPER_WORK_DIR}/manual-review/
  ├─ pending/        # 검토 대기
  ├─ reviewed/       # 검토 완료
  └─ approved/       # 승인 (병합 대상)
```

**프로세스**:
1. 자동 변환 실패 → pending/
2. 사람이 수동 수정 → reviewed/
3. 검증 후 승인 → approved/
4. approved/만 병합

### 7. 변환 규칙 학습
**목적**: 반복되는 패턴 자동화

**구현**:
```json
// custom-rules.json
{
  "patterns": [
    {
      "oracle": "TO_CHAR(amount, 'FM999999.00')",
      "postgres": "TO_CHAR(amount, 'FM999999.00')",
      "note": "이 프로젝트는 포맷 동일"
    }
  ]
}
```

**효과**:
- 프로젝트별 특수 규칙 반영
- LLM 프롬프트에 추가

---

## 에러 복구 전략

### 분할 실패 (Phase 3)
**원인**: XML 파싱 에러, 잘못된 매퍼 구조

**처리**:
- 해당 매퍼 스킵
- 에러 로그 기록
- 수동 검토 리스트 추가
- 계속 진행

### 변환 실패 (Phase 4)
**원인**: 딕셔너리 누락, 복잡한 SQL, LLM 에러

**처리**:
- 원본 유지
- warning 플래그
- partial 상태로 저장
- 계속 진행

### 병합 실패 (Phase 5)
**원인**: 조각 누락, XML 문법 에러

**처리**:
- 해당 매퍼 스킵
- 원본 매퍼 사용
- 에러 리포트 생성
- 계속 진행

---

## 성능 고려사항

### Phase별 예상 소요 시간

| Phase | 작업 | 소규모 (100 매퍼) | 중규모 (500 매퍼) | 대규모 (1000 매퍼) |
|-------|------|------------------|------------------|-------------------|
| **Phase 1** | Dictionary 생성 | 5-10분 | 10-15분 | 15-25분 |
| **Phase 2** | 매퍼 복사 | 1분 | 2분 | 3-5분 |
| **Phase 3** | 분할 (Fragment) | 2-3분 | 5-10분 | 10-20분 |
| **Phase 4** | LLM 변환 | 30-60분 | 3-6시간 | 6-12시간 |
| **Phase 5** | 병합 (Merge) | 2-3분 | 5-10분 | 10-20분 |
| **Phase 6** | 검증 | 10-20분 | 30분-1시간 | 1-2시간 |
| **Phase 7** | 타겟 복사 | 1분 | 2분 | 3-5분 |
| **합계** | | **1-2시간** | **4-8시간** | **8-16시간** |

**변수**:
- LLM API 속도 (RPM 제한)
- SQL 복잡도 (동적 SQL 비율)
- DB 응답 속도 (검증 시)
- 네트워크 속도

**Phase 4 상세** (가장 시간 소요):
```
100 매퍼 = 약 1,000 SQL 조각 (매퍼당 평균 10개 SQL)
LLM API: RPM 50 제한
병렬 워커: 7개

이론적 최소 시간:
- 1,000 조각 ÷ 50 RPM = 20분

실제 소요 시간:
- API 지연, 재시도, 네트워크 등 고려
- 약 30-60분 (2-3배 여유)

500 매퍼 = 5,000 조각:
- 이론: 100분
- 실제: 180-360분 (3-6시간)

1000 매퍼 = 10,000 조각:
- 이론: 200분
- 실제: 360-720분 (6-12시간)
```

### 처리 속도 예측
```
매퍼 100개, 평균 SQL 10개 = 1000 조각

병렬 처리 (MAX_WORKERS=7):
- 조각당 평균 10초 (LLM 호출)
- 1000 / 7 * 10초 = 약 24분

직렬 처리:
- 1000 * 10초 = 약 2시간 47분
```

### 병목 지점
1. **LLM 호출**: 가장 느림
   - 해결: 병렬 처리, Rate Limit 준수
2. **딕셔너리 조회**: 빠름 (JSON 읽기)
3. **파일 I/O**: 보통
   - 해결: 메모리 캐싱

### 비용 고려
```
Opus 4.8 기준 (2026-07 가격):
- 입력: $15 per 1M tokens
- 출력: $75 per 1M tokens

100 매퍼 (1,000 조각):
- 입력: 2M tokens = $30
- 출력: 3M tokens = $225
- 총: ~$255

500 매퍼 (5,000 조각):
- 입력: 10M tokens = $150
- 출력: 15M tokens = $1,125
- 총: ~$1,275

1000 매퍼 (10,000 조각):
- 입력: 20M tokens = $300
- 출력: 30M tokens = $2,250
- 총: ~$2,550

※ 실제 비용은 SQL 복잡도에 따라 ±50% 변동 가능
```

---

## 문서 버전
- 버전: 1.0
- 작성일: 2026-07-26
- 목적: 매퍼 변환 전체 워크플로우 정의
