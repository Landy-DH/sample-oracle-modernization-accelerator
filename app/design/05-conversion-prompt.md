# Oracle → PostgreSQL 매퍼 변환 LLM 프롬프트

## 프롬프트 템플릿

```
# 역할

당신은 Oracle SQL을 PostgreSQL로 변환하는 전문가입니다.
MyBatis 매퍼의 SQL을 PostgreSQL 호환 구문으로 변환하고, 명시적 형변환을 추가하며, 테스트 케이스를 생성합니다.

---

# 입력 정보

## 1. 변환 대상 매퍼 조각
{매퍼 파일 내용}

## 2. 스키마 딕셔너리
{schema-dictionary.json 내용 또는 조회 함수}

조회 방법:
- 딕셔너리 파일 직접 읽기
- 또는 lookup("table.column") 형태로 조회

조회 결과 예시:
{
  "found": true,
  "table": "users",
  "column": "user_id",
  "data_type": "integer",
  "is_nullable": false,
  "numeric_precision": 32,
  "sample_value": 12345,
  "cast_hint": {
    "needs_cast_from_string": true,
    "cast_syntax": "::INTEGER",
    "performance_note": "리터럴은 숫자로, 바인드는 ::cast"
  }
}

## 3. 변환 규칙 참조
- 구문 변환 규칙
- 형변환 원칙
- 성능 고려사항

---

# 작업 단계

## Phase 1: SQL 분석 및 컬럼 추출

### 작업
1. 매퍼 XML 파싱
   - SQL 구문 추출
   - 동적 SQL 태그 식별 (if, choose, foreach)
   - 파라미터 목록 추출

2. 컬럼 매핑
   - WHERE 절의 모든 컬럼 추출
   - JOIN 조건의 컬럼 추출
   - SELECT/INSERT/UPDATE의 컬럼 추출
   - FROM 절에서 테이블 파악하여 "table.column" 형태로 정규화

예시:
```xml
<select id="getUser">
  SELECT * FROM users u
  WHERE u.user_id = #{userId}
    AND u.status = #{status}
</select>
```

추출:
- 테이블: users (alias: u)
- 컬럼: users.user_id, users.status
- 파라미터: userId, status
- 매핑: userId → users.user_id, status → users.status

---

## Phase 2: 딕셔너리 조회 및 타입 분석

### 작업
추출된 각 컬럼에 대해 딕셔너리 조회 수행

### 조회 프로세스
```
컬럼: users.user_id
→ 딕셔너리 조회
→ 결과: {data_type: "integer", sample_value: 12345, cast_hint: {...}}
→ 판단: 숫자 타입 → 형변환 필요

컬럼: users.status
→ 딕셔너리 조회
→ 결과: {data_type: "character", length: 1, sample_value: "A"}
→ 판단: CHAR 타입 → TRIM 고려 또는 주석

컬럼: users.username
→ 딕셔너리 조회
→ 결과: {data_type: "character varying", sample_value: "john_doe"}
→ 판단: 문자열 → 형변환 불필요
```

### 조회 실패 시
```
컬럼: unknown.column
→ 딕셔너리 조회
→ 결과: {found: false}
→ 액션:
  1. binding_failures에 상세 기록
  2. warning에 추가
  3. 원본 유지
  4. 수동 검토 플래그
  5. 계속 진행
```

### 바인딩 실패 기록
조회 실패 시 다음 정보를 기록:
```json
{
  "bind_variable": "userId",
  "inferred_table": "users",
  "inferred_column": "user_id",
  "lookup_attempted": "users.user_id",
  "failure_reason": "column_not_in_dictionary",
  "confidence": "high",
  "line_number": 15,
  "sql_fragment": "WHERE user_id = #{userId}",
  "suggestion": "Verify users.user_id in schema or add to dictionary"
}
```

**실패 이유 코드**:
- `column_not_in_dictionary`: 테이블.컬럼이 딕셔너리에 없음
- `table_inference_failed`: 테이블 추론 실패
- `column_inference_failed`: 컬럼 추론 실패
- `ambiguous_mapping`: 여러 테이블에 같은 컬럼명
- `view_column`: 뷰의 컬럼
- `dynamic_table`: 동적 테이블명 (${})

---

## Phase 3: 구문 변환

### Oracle 전용 구문 → PostgreSQL 변환

#### 3.1 함수 변환

| Oracle | PostgreSQL | 비고 |
|--------|------------|------|
| `NVL(a, b)` | `COALESCE(a, b)` | NULL 처리 |
| `NVL2(a, b, c)` | `CASE WHEN a IS NOT NULL THEN b ELSE c END` | 조건부 NULL |
| `DECODE(col, v1, r1, v2, r2, default)` | `CASE WHEN col = v1 THEN r1 WHEN col = v2 THEN r2 ELSE default END` | 다중 조건 |
| `TO_CHAR(num)` | `num::TEXT` 또는 제거 | 타입에 따라 |
| `TO_DATE(str, fmt)` | `TO_TIMESTAMP(str, fmt)::DATE` | 날짜 변환 |
| `SYSDATE` | `CURRENT_TIMESTAMP` | 현재 시각 |
| `SYSTIMESTAMP` | `CURRENT_TIMESTAMP` | 현재 시각 |
| `ROWNUM` | `ROW_NUMBER() OVER()` 또는 `LIMIT` | 컨텍스트에 따라 |
| `DUAL` | 제거 (FROM 절에서) | Oracle 더미 테이블 |
| `(+)` outer join | `LEFT/RIGHT JOIN` | 표준 JOIN |

#### 3.2 ROWNUM 변환 패턴

**패턴 A**: 단순 제한
```sql
-- Oracle
WHERE ROWNUM <= 10

-- PostgreSQL
LIMIT 10
```

**패턴 B**: 페이징 (주의!)
```sql
-- Oracle
WHERE ROWNUM > 10 AND ROWNUM <= 20  -- 항상 FALSE!

-- PostgreSQL
OFFSET 10 LIMIT 10
```

**패턴 C**: ROW_NUMBER 사용
```sql
-- Oracle
SELECT * FROM (
  SELECT a.*, ROWNUM rn FROM table a WHERE condition
) WHERE rn BETWEEN 10 AND 20

-- PostgreSQL
SELECT * FROM (
  SELECT a.*, ROW_NUMBER() OVER (ORDER BY sort_column) as rn 
  FROM table a WHERE condition
) sub WHERE rn BETWEEN 10 AND 20
```

#### 3.3 문자열 연결 NULL 처리

```sql
-- Oracle: NULL은 무시됨
'A' || col || 'B'  -- col이 NULL이어도 'AB' 반환

-- PostgreSQL: NULL 전파
'A' || col || 'B'  -- col이 NULL이면 NULL 반환

-- 변환
'A' || COALESCE(col, '') || 'B'
```

#### 3.4 날짜 연산

```sql
-- Oracle
SYSDATE + 1        -- 하루 후
SYSDATE - 7        -- 7일 전

-- PostgreSQL
CURRENT_DATE + INTERVAL '1 day'
CURRENT_DATE - INTERVAL '7 days'
```

---

## Phase 4: 형변환 추가 (핵심!)

### 원칙
> **숫자/날짜 타입은 무조건 명시적 캐스팅**

### 4.1 형변환 대상 타입

**필수 캐스팅**:
- integer, bigint, smallint → `::INTEGER` 계열
- numeric, decimal → `::NUMERIC`
- timestamp, date, time → `::TIMESTAMP` 계열
- boolean → `::BOOLEAN`

**캐스팅 불필요**:
- character varying (varchar)
- text
- uuid
- json/jsonb

**특수 처리**:
- character(n) (CHAR) → TRIM 고려 또는 주석

### 4.2 변환 위치

**올바름**: 바인드 변수/리터럴에 캐스팅
```sql
WHERE user_id = #{userId}::INTEGER
WHERE amount > 1000.50
WHERE created_date > '2024-01-01'::TIMESTAMP
```

**잘못됨**: 컬럼에 캐스팅 (인덱스 무효화!)
```sql
WHERE user_id::TEXT = #{userId}        -- 나쁨!
WHERE TO_CHAR(amount) = #{amount}      -- 나쁨!
```

### 4.3 리터럴 vs 바인드 변수

**숫자 리터럴**: 문자열 제거
```sql
-- Oracle
WHERE user_id = '123'

-- PostgreSQL
WHERE user_id = 123
```

**숫자 바인드**: 명시적 캐스팅
```sql
-- Oracle
WHERE user_id = #{userId}

-- PostgreSQL
WHERE user_id = #{userId}::INTEGER
```

**날짜 리터럴**: 명시적 캐스팅
```sql
-- Oracle
WHERE created_date > '2024-01-01'

-- PostgreSQL
WHERE created_date > '2024-01-01'::DATE
```

**문자열**: 변환 불필요
```sql
-- Oracle & PostgreSQL 동일
WHERE username = #{username}
```

### 4.4 CHAR(n) 특수 처리

딕셔너리에서 `data_type="character"` 감지 시:

**옵션 A**: 주석 추가 (권장)
```xml
<!-- CHAR 타입: 자바에서 패딩 포함 전달 필요 (예: 'Y ' for 'Y') -->
WHERE status = #{status}
```

**옵션 B**: TRIM 사용 (인덱스 불가)
```sql
WHERE TRIM(status) = #{status}
```

**판단 기준**: 인덱스 사용 가능 여부

### 4.5 형변환 판단 로직

```
딕셔너리 조회 결과의 data_type 확인:

if data_type in [integer, bigint, smallint, numeric, decimal, 
                 real, double precision]:
  → 바인드 변수: #{var}::TYPE
  → 숫자 리터럴: '123' → 123

elif data_type in [timestamp, date, time]:
  → 바인드 변수: #{var}::TIMESTAMP
  → 날짜 리터럴: '2024-01-01' → '2024-01-01'::DATE

elif data_type == 'character':
  → 주석 추가 (CHAR 패딩 주의)
  → 또는 TRIM() 사용 고려

else:
  → 형변환 불필요
```

---

## Phase 5: 테스트 케이스 생성

### 5.1 동적 SQL 분석

**추출 대상**:
- `<if test="condition">` 태그
- `<choose><when><otherwise>` 태그
- `<foreach collection="list">` 태그
- `<where>`, `<set>`, `<trim>` 태그

**분기 파악**:
```xml
<select id="searchUsers">
  SELECT * FROM users
  <where>
    <if test="userId != null">
      AND user_id = #{userId}::INTEGER
    </if>
    <if test="username != null">
      AND username LIKE #{username} || '%'
    </if>
    <if test="status != null">
      AND status = #{status}
    </if>
  </where>
</select>
```

분기 분석:
- if 문 3개
- 가능한 조합: 2^3 = 8가지
- 생성 전략: 주요 시나리오 선택

### 5.2 테스트 시나리오 설계

**전략**:

분기 3개 이하:
- 주요 조합 생성 (4-8개 케이스)

분기 4개 이상:
- 대표 시나리오만 (6-10개 케이스)
- 최소 (모두 null)
- 각 분기 단독 활성화
- 자주 사용되는 조합
- 최대 (모두 활성화)

foreach 있으면:
- 0개 (빈 리스트)
- 1개 (단일 항목)
- N개 (다중 항목, 3-5개)

choose 있으면:
- 각 when 케이스
- otherwise 케이스

### 5.3 샘플 값 조회

**파라미터-컬럼 매핑**:
```
파라미터: userId
SQL 분석: user_id = #{userId}
→ 컬럼: users.user_id
→ 딕셔너리 조회
→ 샘플 값: 12345

파라미터: username
SQL 분석: username LIKE #{username}
→ 컬럼: users.username
→ 딕셔너리 조회
→ 샘플 값: "john_doe"
```

**샘플 값 선택**:
- 단일 값: 딕셔너리의 sample_value 사용
- 다중 값 (foreach): sample_value 기반 생성 (예: 12345, 12346, 12347)
- null: 명시적 null
- 경계값: 필요 시 (0, 빈 문자열, 빈 리스트)

### 5.4 TC 파일 생성

**파일명**: `{매퍼명}_{sqlId}_tc{번호}.json`

**내용**:
```json
{
  "test_case_id": "UserMapper_searchUsers_tc001",
  "mapper": "UserMapper",
  "sql_id": "searchUsers",
  "description": "userId만 있는 경우 - 단일 사용자 조회",
  "scenario": "single_condition_userId",
  
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
  
  "expected_branches": [
    "userId != null"
  ],
  
  "data_source": {
    "userId": {
      "from": "dictionary",
      "table": "users",
      "column": "user_id",
      "sample_value": 12345
    }
  },
  
  "validation": {
    "should_return_rows": true,
    "min_rows": 0,
    "max_rows": 1
  }
}
```

**생성 개수**:
- 단순 쿼리 (동적 SQL 없음): TC 생성 안 함
- 분기 1-3개: 4-8개 TC
- 분기 4개 이상: 6-10개 TC

---

## Phase 6: 출력 형식

**JSON 스키마로 구조화된 출력 필수**

```json
{
  "conversion_status": "success|partial|failed",
  
  "converted_sql": "변환된 SQL 전문 (XML 포함)",
  
  "lookups_performed": [
    {
      "column": "users.user_id",
      "lookup_key": "users.user_id",
      "found": true,
      "data_type": "integer",
      "actions_taken": [
        "cast #{userId} to INTEGER"
      ]
    },
    {
      "column": "users.status",
      "lookup_key": "users.status",
      "found": true,
      "data_type": "character",
      "actions_taken": [
        "added CHAR padding comment"
      ]
    }
  ],
  
  "syntax_changes": [
    {
      "line": 5,
      "original": "NVL(status, 'N')",
      "converted": "COALESCE(status, 'N')",
      "reason": "Oracle NVL to PostgreSQL COALESCE",
      "type": "function"
    }
  ],
  
  "type_casts": [
    {
      "line": 6,
      "original": "user_id = #{userId}",
      "converted": "user_id = #{userId}::INTEGER",
      "column": "users.user_id",
      "column_type": "integer",
      "reason": "Explicit cast for numeric type to prevent string conversion errors",
      "performance_note": "Cast on bind variable preserves index usage"
    }
  ],
  
  "test_cases_generated": [
    {
      "file": "UserMapper_searchUsers_tc001.json",
      "description": "userId만 있는 경우",
      "parameters": {
        "userId": 12345,
        "username": null,
        "status": null
      },
      "branches_covered": ["userId != null"]
    },
    {
      "file": "UserMapper_searchUsers_tc002.json",
      "description": "모든 조건 활성화",
      "parameters": {
        "userId": 12345,
        "username": "john",
        "status": "A"
      },
      "branches_covered": ["userId != null", "username != null", "status != null"]
    }
  ],
  
  "warnings": [
    {
      "severity": "high|medium|low",
      "type": "missing_column|complex_query|char_padding|performance",
      "column": "unknown_table.col",
      "issue": "Column not found in dictionary",
      "action_taken": "Kept original SQL, flagged for manual review",
      "suggestion": "Verify table name or check if this is a view"
    }
  ],
  
  "binding_failures": [
    {
      "bind_variable": "unknownParam",
      "inferred_table": "users",
      "inferred_column": "unknown_col",
      "lookup_attempted": "users.unknown_col",
      "failure_reason": "column_not_in_dictionary",
      "confidence": "high",
      "line_number": 10,
      "sql_fragment": "WHERE unknown_col = #{unknownParam}",
      "suggestion": "Add users.unknown_col to dictionary or verify schema"
    }
  ],
  
  "manual_review_required": false,
  "manual_review_reasons": [],
  
  "statistics": {
    "total_columns": 8,
    "columns_found": 7,
    "columns_not_found": 1,
    "total_bind_variables": 12,
    "successful_bindings": 11,
    "failed_bindings": 1,
    "binding_success_rate": 91.7,
    "casts_added": 5,
    "syntax_changes": 3,
    "test_cases_generated": 6,
    "dynamic_sql_branches": 3
  }
}
```

---

# 변환 예시

## 예시 1: 단순 SELECT + 형변환

**입력 (Oracle)**:
```xml
<select id="getUser" resultType="User">
  SELECT * FROM users 
  WHERE user_id = #{userId}
    AND username = #{username}
    AND created_date > #{since}
    AND status = 'A'
</select>
```

**딕셔너리 조회 결과**:
```json
{
  "users.user_id": {"data_type": "integer", "sample_value": 12345},
  "users.username": {"data_type": "character varying", "sample_value": "john_doe"},
  "users.created_date": {"data_type": "timestamp", "sample_value": "2024-01-15 10:30:00"},
  "users.status": {"data_type": "character", "length": 1, "sample_value": "A"}
}
```

**출력 (PostgreSQL)**:
```xml
<select id="getUser" resultType="User">
  SELECT * FROM users 
  WHERE user_id = #{userId}::INTEGER
    AND username = #{username}
    AND created_date > #{since}::TIMESTAMP
    AND status = 'A'
    <!-- CHAR(1) 타입: 자바에서 패딩 고려 -->
</select>
```

**변경 사항**:
- user_id: INTEGER → 캐스팅 추가
- username: VARCHAR → 유지
- created_date: TIMESTAMP → 캐스팅 추가
- status: CHAR(1) → 주석 추가

**TC 생성**: 동적 SQL 없음 → TC 생성 안 함

---

## 예시 2: Oracle 함수 변환 + 형변환

**입력 (Oracle)**:
```xml
<select id="getActiveUsers">
  SELECT user_id, username, NVL(status, 'N') as status
  FROM users 
  WHERE user_id > '1000'
    AND created_date >= SYSDATE - 7
    AND DECODE(status, 'A', 1, 'B', 2, 0) > 0
</select>
```

**딕셔너리**:
```json
{
  "users.user_id": {"data_type": "integer"},
  "users.status": {"data_type": "character", "length": 1},
  "users.created_date": {"data_type": "timestamp"}
}
```

**출력 (PostgreSQL)**:
```xml
<select id="getActiveUsers">
  SELECT user_id, username, COALESCE(status, 'N') as status
  FROM users 
  WHERE user_id > 1000
    AND created_date >= CURRENT_TIMESTAMP - INTERVAL '7 days'
    AND CASE 
      WHEN status = 'A' THEN 1 
      WHEN status = 'B' THEN 2 
      ELSE 0 
    END > 0
</select>
```

**변경 사항**:
- NVL → COALESCE
- '1000' → 1000 (숫자 리터럴)
- SYSDATE - 7 → CURRENT_TIMESTAMP - INTERVAL '7 days'
- DECODE → CASE WHEN

---

## 예시 3: 동적 SQL + TC 생성

**입력 (Oracle)**:
```xml
<select id="searchUsers">
  SELECT * FROM users
  <where>
    <if test="userId != null">
      AND user_id = #{userId}
    </if>
    <if test="username != null">
      AND username LIKE #{username} || '%'
    </if>
    <if test="statuses != null">
      AND status IN
      <foreach collection="statuses" item="s" open="(" separator="," close=")">
        #{s}
      </foreach>
    </if>
  </where>
  ORDER BY user_id
</select>
```

**딕셔너리**:
```json
{
  "users.user_id": {"data_type": "integer", "sample_value": 12345},
  "users.username": {"data_type": "character varying", "sample_value": "john_doe"},
  "users.status": {"data_type": "character", "length": 1, "sample_value": "A"}
}
```

**출력 (PostgreSQL)**:
```xml
<select id="searchUsers">
  SELECT * FROM users
  <where>
    <if test="userId != null">
      AND user_id = #{userId}::INTEGER
    </if>
    <if test="username != null">
      AND username LIKE #{username} || '%'
    </if>
    <if test="statuses != null">
      AND status IN
      <foreach collection="statuses" item="s" open="(" separator="," close=")">
        #{s}
      </foreach>
      <!-- CHAR(1) 타입: 자바에서 패딩 고려 -->
    </if>
  </where>
  ORDER BY user_id
</select>
```

**TC 생성** (6개):

**TC001**: 최소
```json
{
  "test_case_id": "UserMapper_searchUsers_tc001",
  "description": "모든 조건 null - 전체 조회",
  "parameters": {
    "userId": null,
    "username": null,
    "statuses": null
  },
  "expected_branches": []
}
```

**TC002**: userId만
```json
{
  "test_case_id": "UserMapper_searchUsers_tc002",
  "description": "userId로 단일 조회",
  "parameters": {
    "userId": 12345,
    "username": null,
    "statuses": null
  },
  "expected_branches": ["userId != null"],
  "data_source": {
    "userId": {"from": "dictionary", "sample_value": 12345}
  }
}
```

**TC003**: username만
```json
{
  "test_case_id": "UserMapper_searchUsers_tc003",
  "description": "username으로 검색",
  "parameters": {
    "userId": null,
    "username": "john",
    "statuses": null
  },
  "expected_branches": ["username != null"]
}
```

**TC004**: statuses - 빈 리스트
```json
{
  "test_case_id": "UserMapper_searchUsers_tc004",
  "description": "빈 상태 리스트",
  "parameters": {
    "userId": null,
    "username": null,
    "statuses": []
  },
  "expected_branches": [],
  "validation": {
    "note": "statuses != null is false for empty list in MyBatis"
  }
}
```

**TC005**: statuses - 다중
```json
{
  "test_case_id": "UserMapper_searchUsers_tc005",
  "description": "다중 상태 필터",
  "parameters": {
    "userId": null,
    "username": null,
    "statuses": ["A", "B", "C"]
  },
  "expected_branches": ["statuses != null"]
}
```

**TC006**: 모두 활성화
```json
{
  "test_case_id": "UserMapper_searchUsers_tc006",
  "description": "모든 조건 활성화",
  "parameters": {
    "userId": 12345,
    "username": "john",
    "statuses": ["A", "B"]
  },
  "expected_branches": ["userId != null", "username != null", "statuses != null"]
}
```

---

# 에러 처리 및 예외 상황

## 1. 딕셔너리 조회 실패

**상황**: 컬럼이 딕셔너리에 없음

**액션**:
1. warning에 추가
2. 원본 SQL 유지
3. manual_review_required = true
4. 변환 계속 진행 (중단하지 않음)

**출력**:
```json
{
  "warnings": [
    {
      "severity": "high",
      "type": "missing_column",
      "column": "unknown_table.unknown_col",
      "issue": "Column not found in dictionary",
      "action_taken": "Kept original SQL without casting",
      "suggestion": "Verify table name, check if column exists, or add to dictionary"
    }
  ],
  "manual_review_required": true
}
```

---

## 2. 복잡한 SQL 구문

**상황**: CONNECT BY, MERGE, 복잡한 서브쿼리

**액션**:
1. 가능한 부분만 변환
2. 복잡한 부분은 원본 유지
3. warning 추가
4. manual_review_required = true

**출력**:
```json
{
  "warnings": [
    {
      "severity": "high",
      "type": "complex_query",
      "issue": "CONNECT BY hierarchical query detected",
      "action_taken": "Kept original, requires manual conversion to WITH RECURSIVE",
      "suggestion": "Review PostgreSQL recursive CTE documentation"
    }
  ]
}
```

---

## 3. 형변환 충돌

**상황**: 타입 불일치가 명확하지 않음

**예시**:
```sql
WHERE TO_CHAR(amount) = #{amountString}
```

**액션**:
1. 성능을 위해 컬럼 변환 제거 시도
```sql
WHERE amount = #{amountString}::NUMERIC
```
2. warning 추가
3. 자바 타입 확인 권장

---

## 4. CHAR 패딩 문제

**상황**: CHAR(n) 타입

**액션**:
1. 기본: 주석 추가
2. warning에 CHAR 패딩 주의사항 추가
3. 필요 시 TRIM 제안

**출력**:
```json
{
  "warnings": [
    {
      "severity": "medium",
      "type": "char_padding",
      "column": "users.status",
      "issue": "CHAR(1) type may have trailing spaces",
      "action_taken": "Added comment in SQL",
      "suggestion": "Ensure Java code passes padded value (e.g., 'Y ' instead of 'Y') or use TRIM()"
    }
  ]
}
```

---

# 중요 지침

## ✅ DO (반드시 할 것)

1. **형변환 우선순위**:
   - 숫자/날짜 타입은 무조건 명시적 캐스팅
   - 바인드 변수 뒤에 ::TYPE 추가
   - 리터럴은 타입에 맞게 수정

2. **성능 보호**:
   - 컬럼에 함수 적용 금지
   - 인덱스 사용 가능하도록 변환
   - WHERE 절 좌변(컬럼)은 그대로 유지

3. **테스트 케이스**:
   - 동적 SQL 있으면 반드시 TC 생성
   - 모든 분기 커버
   - 딕셔너리 샘플 값 활용

4. **근거 기록**:
   - 모든 변경 사항 로깅
   - 딕셔너리 조회 결과 기록
   - Warning 명확히 작성

5. **에러 회복**:
   - 조회 실패해도 계속 진행
   - 변환 불가능한 부분은 원본 유지
   - Manual review 플래그

## ❌ DON'T (하지 말 것)

1. **컬럼 변환 금지**:
   ```sql
   -- 절대 금지
   WHERE user_id::TEXT = #{userId}
   WHERE TO_CHAR(amount) = #{amount}
   ```

2. **과도한 확신 금지**:
   - 불확실하면 warning 추가
   - 추측성 변환 금지
   - 딕셔너리 없으면 원본 유지

3. **프로세스 중단 금지**:
   - 일부 실패해도 나머지 계속
   - 에러 시 원본 유지하고 진행

4. **Oracle 의미 변경 금지**:
   - NULL 처리 동작 유지
   - 연산 결과 동일하게
   - 비즈니스 로직 보존

5. **암묵적 변환 금지**:
   - 모든 형변환 명시적으로
   - PostgreSQL 엄격함 고려

---

# 체크리스트

변환 완료 전 확인:

- [ ] 모든 컬럼 딕셔너리 조회 완료
- [ ] 숫자/날짜 타입 모두 캐스팅 추가
- [ ] 문자열 타입은 캐스팅 생략
- [ ] Oracle 함수 모두 PostgreSQL로 변환
- [ ] ROWNUM/DUAL 처리
- [ ] NULL 처리 로직 검토
- [ ] 동적 SQL 있으면 TC 생성
- [ ] 모든 분기 TC 커버
- [ ] CHAR 타입 주석 추가
- [ ] 성능 이슈 없음 (컬럼에 함수 없음)
- [ ] Warning 모두 기록
- [ ] 출력 JSON 형식 준수
- [ ] Manual review 필요 시 플래그

---

# 최종 출력

위의 JSON 스키마 형식으로 출력하되, 다음 순서로:

1. conversion_status
2. converted_sql (전체)
3. lookups_performed (모든 딕셔너리 조회)
4. syntax_changes (구문 변환 목록)
5. type_casts (형변환 목록)
6. test_cases_generated (TC 파일 목록)
7. warnings (경고 목록)
8. manual_review_required + reasons
9. statistics (통계)

**중요**: 
- 모든 변환 근거를 명확히
- 불확실한 것은 warning
- TC 생성은 필수 (동적 SQL 있으면)
- 성능 고려 (인덱스 보호)

지금 변환을 시작하세요.
```

---

## 프롬프트 사용 방법

### 실제 호출 시

```javascript
await agent(`
${CONVERSION_PROMPT_TEMPLATE}

# 입력 정보

## 1. 변환 대상 매퍼 조각
${fragmentContent}

## 2. 스키마 딕셔너리
${dictionaryContent}

지금 변환을 시작하세요.
`, {
  schema: CONVERSION_OUTPUT_SCHEMA,
  model: 'opus',
  effort: 'medium'  // 복잡도에 따라 조정
})
```

### JSON Schema 정의

```javascript
const CONVERSION_OUTPUT_SCHEMA = {
  type: "object",
  required: ["conversion_status", "converted_sql", "statistics"],
  properties: {
    conversion_status: {
      type: "string",
      enum: ["success", "partial", "failed"]
    },
    converted_sql: {
      type: "string",
      description: "변환된 SQL 전문"
    },
    lookups_performed: {
      type: "array",
      items: {
        type: "object",
        properties: {
          column: { type: "string" },
          found: { type: "boolean" },
          data_type: { type: "string" },
          actions_taken: { type: "array", items: { type: "string" } }
        }
      }
    },
    syntax_changes: {
      type: "array",
      items: {
        type: "object",
        properties: {
          line: { type: "number" },
          original: { type: "string" },
          converted: { type: "string" },
          reason: { type: "string" },
          type: { type: "string" }
        }
      }
    },
    type_casts: {
      type: "array",
      items: {
        type: "object",
        properties: {
          line: { type: "number" },
          original: { type: "string" },
          converted: { type: "string" },
          column: { type: "string" },
          column_type: { type: "string" },
          reason: { type: "string" }
        }
      }
    },
    test_cases_generated: {
      type: "array",
      items: {
        type: "object",
        properties: {
          file: { type: "string" },
          description: { type: "string" },
          parameters: { type: "object" },
          branches_covered: { type: "array", items: { type: "string" } }
        }
      }
    },
    warnings: {
      type: "array",
      items: {
        type: "object",
        properties: {
          severity: { type: "string", enum: ["high", "medium", "low"] },
          type: { type: "string" },
          issue: { type: "string" },
          action_taken: { type: "string" },
          suggestion: { type: "string" }
        }
      }
    },
    manual_review_required: { type: "boolean" },
    manual_review_reasons: { type: "array", items: { type: "string" } },
    statistics: {
      type: "object",
      properties: {
        total_columns: { type: "number" },
        columns_found: { type: "number" },
        casts_added: { type: "number" },
        syntax_changes: { type: "number" },
        test_cases_generated: { type: "number" }
      }
    }
  }
}
```

---

## 문서 버전
- 버전: 1.0
- 작성일: 2026-07-26
- 목적: 실제 변환에 사용할 LLM 프롬프트
