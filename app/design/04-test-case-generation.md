# 동적 SQL 테스트 케이스 자동 생성

## 목적

MyBatis 매퍼의 동적 SQL(if, choose, foreach 등) 분기를 체계적으로 테스트하기 위해, LLM이 자동으로 테스트 케이스를 생성합니다.

**핵심 가치**:
- 모든 분기 조합을 빠짐없이 테스트
- 실제 데이터 기반 테스트 (딕셔너리 샘플 값 활용)
- Oracle과 PostgreSQL 결과 비교 자동화
- 변환 정확성 검증

---

## 1. 동적 SQL 분기 패턴

### MyBatis 동적 SQL 태그

| 태그 | 역할 | 분기 생성 |
|------|------|----------|
| `<if test="...">` | 조건부 SQL | 참/거짓 2가지 |
| `<choose><when><otherwise>` | 다중 선택 | N가지 경로 |
| `<foreach>` | 반복 | 0개/1개/N개 케이스 |
| `<where>` | 동적 WHERE | 조건 조합 |
| `<set>` | 동적 SET | 필드 조합 |
| `<trim>` | 접두/접미 제거 | 조합 케이스 |

### 예시: 분기가 많은 매퍼

```xml
<select id="searchUsers" resultType="User">
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
    <if test="minAge != null">
      AND age >= #{minAge}::INTEGER
    </if>
    <if test="userIds != null">
      AND user_id IN
      <foreach collection="userIds" item="id" open="(" separator="," close=")">
        #{id}::INTEGER
      </foreach>
    </if>
  </where>
  ORDER BY user_id
</select>
```

**가능한 분기 조합**: 2^5 = 32가지 (5개 if 문)

---

## 2. 테스트 케이스 생성 전략

### 기본 원칙

1. **대표 케이스 선택**: 모든 조합이 아닌 의미 있는 케이스
2. **경계값 테스트**: null, 빈 리스트, 단일값, 다중값
3. **실제 데이터 사용**: 딕셔너리 샘플 값 활용
4. **분기 커버리지**: 모든 if/when/foreach 최소 1회 실행

### 생성 전략

**전략 A**: 주요 시나리오 (권장)
```
1. 모든 조건 null (최소 케이스)
2. 각 조건 하나씩 활성화 (단일 분기)
3. 자주 사용되는 조합 (비즈니스 로직 기반)
4. 모든 조건 활성화 (최대 케이스)
```

**전략 B**: 전체 조합 (소규모 분기용)
```
- 분기 3개 이하: 모든 조합 (2^3 = 8개)
- 분기 4개 이상: 전략 A 사용
```

---

## 3. 테스트 케이스 파일 구조

### 파일명 규칙

```
${TESTCASE_DIR}/
  ├─ UserMapper_searchUsers_tc001.json
  ├─ UserMapper_searchUsers_tc002.json
  ├─ UserMapper_searchUsers_tc003.json
  ├─ OrderMapper_getOrders_tc001.json
  └─ ...

형식: {매퍼명}_{sqlId}_tc{번호}.json
```

### TC 파일 내용

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
    "status": null,
    "minAge": null,
    "userIds": null
  },
  
  "parameter_types": {
    "userId": "INTEGER",
    "username": "VARCHAR",
    "status": "CHAR(1)",
    "minAge": "INTEGER",
    "userIds": "INTEGER[]"
  },
  
  "expected_branches": [
    "userId != null"
  ],
  
  "expected_sql_pattern": {
    "oracle": "SELECT * FROM users WHERE user_id = ?",
    "postgres": "SELECT * FROM users WHERE user_id = ?::INTEGER"
  },
  
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
    "max_rows": 1,
    "check_columns": ["user_id", "username", "status"]
  }
}
```

---

## 4. LLM 테스트 케이스 생성 프로세스

### Step 1: 동적 SQL 분석

**입력**: 매퍼 조각 파일
```xml
<select id="searchUsers">
  SELECT * FROM users
  <where>
    <if test="userId != null">AND user_id = #{userId}::INTEGER</if>
    <if test="username != null">AND username LIKE #{username} || '%'</if>
    <if test="status != null">AND status = #{status}</if>
  </where>
</select>
```

**LLM 작업**:
```
1. 동적 SQL 태그 추출
   - <if test="userId != null">
   - <if test="username != null">
   - <if test="status != null">

2. 파라미터 추출
   - userId
   - username
   - status

3. 분기 조건 파악
   - 3개 if 문 → 2^3 = 8가지 조합
```

### Step 2: 테스트 시나리오 설계

**LLM 판단**:
```
분기 수: 3개 (적음)
→ 전략: 주요 시나리오 선택

생성할 테스트 케이스:
1. 모두 null (최소)
2. userId만 (가장 일반적)
3. username만 (검색 케이스)
4. status만 (필터링)
5. userId + status (일반적 조합)
6. 모두 있음 (최대)

총 6개 케이스
```

### Step 3: 딕셔너리에서 샘플 값 조회

**각 파라미터별 조회**:

```
파라미터: userId
→ 매핑 컬럼: users.user_id
→ 딕셔너리 조회: lookup("users.user_id")
→ 샘플 값: 12345

파라미터: username
→ 매핑 컬럼: users.username
→ 딕셔너리 조회: lookup("users.username")
→ 샘플 값: "john_doe"

파라미터: status
→ 매핑 컬럼: users.status
→ 딕셔너리 조회: lookup("users.status")
→ 샘플 값: "A"
```

### Step 4: TC 파일 생성

**TC001**: userId만
```json
{
  "test_case_id": "UserMapper_searchUsers_tc001",
  "description": "userId만 있는 경우",
  "parameters": {
    "userId": 12345,
    "username": null,
    "status": null
  },
  "expected_branches": ["userId != null"]
}
```

**TC002**: username만
```json
{
  "test_case_id": "UserMapper_searchUsers_tc002",
  "description": "username으로 검색",
  "parameters": {
    "userId": null,
    "username": "john",
    "status": null
  },
  "expected_branches": ["username != null"]
}
```

**TC003**: 모두 있음
```json
{
  "test_case_id": "UserMapper_searchUsers_tc003",
  "description": "모든 조건 활성화",
  "parameters": {
    "userId": 12345,
    "username": "john",
    "status": "A"
  },
  "expected_branches": ["userId != null", "username != null", "status != null"]
}
```

---

## 5. 복잡한 동적 SQL 케이스

### foreach 테스트 케이스

**매퍼**:
```xml
<select id="getUsersByIds">
  SELECT * FROM users
  WHERE user_id IN
  <foreach collection="userIds" item="id" open="(" separator="," close=")">
    #{id}::INTEGER
  </foreach>
</select>
```

**테스트 케이스**:

**TC001**: 빈 리스트
```json
{
  "test_case_id": "UserMapper_getUsersByIds_tc001",
  "description": "빈 리스트 - 예외 처리 확인",
  "parameters": {
    "userIds": []
  },
  "expected_branches": ["foreach: 0 items"],
  "validation": {
    "should_error": true,
    "error_type": "empty_in_clause"
  }
}
```

**TC002**: 단일 항목
```json
{
  "test_case_id": "UserMapper_getUsersByIds_tc002",
  "description": "단일 ID",
  "parameters": {
    "userIds": [12345]
  },
  "expected_branches": ["foreach: 1 item"],
  "data_source": {
    "userIds[0]": {
      "from": "dictionary",
      "sample_value": 12345
    }
  }
}
```

**TC003**: 다중 항목
```json
{
  "test_case_id": "UserMapper_getUsersByIds_tc003",
  "description": "다중 ID",
  "parameters": {
    "userIds": [12345, 12346, 12347]
  },
  "expected_branches": ["foreach: 3 items"],
  "data_source": {
    "userIds": {
      "from": "dictionary_multiple",
      "sample_values": [12345, 12346, 12347]
    }
  }
}
```

### choose/when/otherwise 테스트 케이스

**매퍼**:
```xml
<select id="getUsersByType">
  SELECT * FROM users
  <where>
    <choose>
      <when test="type == 'id'">
        user_id = #{value}::INTEGER
      </when>
      <when test="type == 'name'">
        username = #{value}
      </when>
      <when test="type == 'email'">
        email = #{value}
      </when>
      <otherwise>
        1=0
      </otherwise>
    </choose>
  </where>
</select>
```

**테스트 케이스**:

**TC001**: type='id'
```json
{
  "test_case_id": "UserMapper_getUsersByType_tc001",
  "description": "ID로 조회",
  "parameters": {
    "type": "id",
    "value": "12345"
  },
  "expected_branches": ["when: type == 'id'"],
  "expected_sql_pattern": {
    "postgres": "WHERE user_id = ?::INTEGER"
  }
}
```

**TC002**: type='name'
```json
{
  "test_case_id": "UserMapper_getUsersByType_tc002",
  "description": "이름으로 조회",
  "parameters": {
    "type": "name",
    "value": "john_doe"
  },
  "expected_branches": ["when: type == 'name'"],
  "expected_sql_pattern": {
    "postgres": "WHERE username = ?"
  }
}
```

**TC003**: otherwise
```json
{
  "test_case_id": "UserMapper_getUsersByType_tc003",
  "description": "잘못된 type - otherwise",
  "parameters": {
    "type": "invalid",
    "value": "anything"
  },
  "expected_branches": ["otherwise"],
  "expected_sql_pattern": {
    "postgres": "WHERE 1=0"
  },
  "validation": {
    "should_return_rows": false
  }
}
```

---

## 6. 딕셔너리 활용 전략

### 샘플 값 선택 규칙

**단일 값**:
```
딕셔너리에 샘플 값이 있으면 그대로 사용:
- users.user_id → 12345
- users.username → "john_doe"
- users.status → "A"
```

**다중 값 (foreach용)**:
```
옵션 A: 딕셔너리에 여러 샘플 저장
  "sample_values": [12345, 12346, 12347]

옵션 B: 단일 샘플 값에서 생성
  12345 → [12345, 12346, 12347] (증가)

옵션 C: 실제 DB 조회
  SELECT user_id FROM users LIMIT 3
```

**엣지 케이스 (우선 생성)**:
```
1. NULL 값:
   - 명시적 null
   - 각 타입별 NULL 처리 확인

2. 빈 값:
   - 빈 문자열: ""
   - 빈 리스트: []
   - 공백만: "   "

3. 특수 숫자:
   - 0 (zero)
   - -1 (음수)
   - 최소값: -2147483648 (INTEGER)
   - 최대값: 2147483647 (INTEGER)

4. 날짜 경계:
   - '1900-01-01' (과거)
   - '9999-12-31' (미래)
   - CURRENT_DATE (현재)

5. 특수 문자열:
   - NULL 문자열: "NULL"
   - SQL 인젝션: "'; DROP TABLE--"
   - 유니코드: "한글", "日本語"
   - 긴 문자열: 1000자 이상

6. Boolean:
   - true/false
   - 1/0
   - 'Y'/'N'
   - 't'/'f' (PostgreSQL)
```

**엣지 케이스 우선 전략**:
```
TC 생성 순서:
1. 엣지 케이스 TC (NULL, 빈값, 경계값) - 우선
2. 일반 케이스 TC (정상 데이터)
3. 브랜치 커버리지 TC (동적 SQL 분기)

예시:
- TC001: userId = NULL (엣지)
- TC002: userId = 0 (엣지)
- TC003: userId = -1 (엣지)
- TC004: userId = 12345 (정상)
- TC005: userId = 12345 AND status = 'A' (브랜치)
```

### 컬럼 매핑 추론

**명시적 매핑 (이상적)**:
```xml
<!-- resultMap으로 매핑 명확 -->
<parameterMap id="userParams">
  <parameter property="userId" jdbcType="INTEGER"/>
  <parameter property="username" jdbcType="VARCHAR"/>
</parameterMap>
```

**추론 기반 (일반적)**:
```
파라미터: userId
SQL 내용: user_id = #{userId}
→ 추론: userId → users.user_id

파라미터: username
SQL 내용: username LIKE #{username}
→ 추론: username → users.username
```

**LLM 추론 프로세스**:
```
1. SQL에서 #{param} 찾기
2. 주변 컨텍스트 확인 (컬럼명 = #{param})
3. FROM 절에서 테이블 파악
4. 테이블.컬럼 매핑 생성
5. 딕셔너리 조회
```

---

## 7. 변환 프롬프트 통합

### 변환 시 TC 생성 추가

**Phase 4 변환 프롬프트에 추가**:

```
# 변환 작업

## 1. SQL 구문 변환
[기존 변환 로직]

## 2. 형변환 추가
[기존 형변환 로직]

## 3. 테스트 케이스 생성 (신규)

### 동적 SQL 분석
- <if>, <choose>, <foreach> 태그 추출
- 파라미터 목록 및 조건 파악
- 분기 조합 분석

### 테스트 시나리오 설계
원칙:
- 분기 3개 이하: 주요 조합 (4-8개 케이스)
- 분기 4개 이상: 대표 시나리오 (6-10개 케이스)
- foreach: 0개/1개/N개 케이스 필수
- choose: 각 when + otherwise 케이스

### 샘플 값 조회
각 파라미터에 대해:
1. SQL에서 매핑 컬럼 추론
2. 딕셔너리 조회
3. 샘플 값 가져오기
4. 타입 정보 포함

### TC 파일 생성
각 테스트 케이스:
- 파일명: {매퍼명}_{sqlId}_tc{번호}.json
- 저장 위치: ${TESTCASE_DIR}/
- 내용: 파라미터, 기대 분기, 샘플 값, 검증 규칙

## 출력 형식

{
  "converted_sql": "...",
  "changes": [...],
  "type_casts": [...],
  "test_cases_generated": [
    {
      "file": "UserMapper_searchUsers_tc001.json",
      "description": "userId만 있는 경우",
      "parameters": {...},
      "branches_covered": [...]
    }
  ]
}
```

---

## 8. 워크플로우 통합

### Phase 4 수정: 변환 + TC 생성

```
Phase 4: SQL 변환 + TC 생성

Step 4-1: 변환 준비 (기존)
Step 4-2: 병렬 변환 (기존)

Step 4-3: TC 생성 (신규)
  입력:
    - 변환된 SQL 조각
    - 원본 매퍼 (동적 SQL 포함)
    - 스키마 딕셔너리
  
  작업:
    1. 동적 SQL 분석
    2. 테스트 시나리오 설계
    3. 딕셔너리에서 샘플 값 조회
    4. TC 파일 생성
  
  출력:
    ${TESTCASE_DIR}/
      ├─ UserMapper_searchUsers_tc001.json
      ├─ UserMapper_searchUsers_tc002.json
      └─ ...

Step 4-4: 변환 결과 저장 (기존)
```

### 디렉토리 구조 업데이트

```
${PROJECT_WORK_DIR}/
├─ mappers/
│   ├─ original/
│   ├─ fragmented/
│   ├─ converted/
│   └─ merged/
├─ output/
├─ testcases/              # 신규 (TESTCASE_DIR)
│   ├─ UserMapper_searchUsers_tc001.json
│   ├─ UserMapper_searchUsers_tc002.json
│   ├─ UserMapper_insertUser_tc001.json
│   └─ ...
└─ reports/
```

---

## 9. TC 활용 (검증 단계)

### Phase 6: 검증 시 TC 사용

**검증 프로세스**:

```
각 TC 파일에 대해:

1. TC 파일 읽기
   - 파라미터 로드
   - 기대 분기 확인

2. Oracle에서 실행 (원본)
   - 파라미터 바인딩
   - 쿼리 실행
   - 결과 저장

3. PostgreSQL에서 실행 (변환)
   - 파라미터 바인딩 (형변환 적용)
   - 쿼리 실행
   - 결과 저장

4. 결과 비교
   - 행 수 비교
   - 컬럼 값 비교
   - NULL 처리 비교
   - 정렬 순서 비교

5. 차이점 리포트
   - 불일치 상세
   - 원인 분석
   - 수정 제안
```

**검증 리포트**:
```json
{
  "test_case": "UserMapper_searchUsers_tc001",
  "oracle_result": {
    "row_count": 1,
    "rows": [
      {"user_id": 12345, "username": "john_doe", "status": "A"}
    ]
  },
  "postgres_result": {
    "row_count": 1,
    "rows": [
      {"user_id": 12345, "username": "john_doe", "status": "A"}
    ]
  },
  "comparison": {
    "rows_match": true,
    "values_match": true,
    "issues": []
  },
  "status": "PASS"
}
```

---

## 10. 고급 시나리오

### 복잡한 분기 조합

**매퍼**:
```xml
<select id="complexSearch">
  SELECT * FROM orders o
  JOIN users u ON o.user_id = u.user_id
  <where>
    <if test="userId != null">
      AND o.user_id = #{userId}::INTEGER
    </if>
    <choose>
      <when test="dateRange == 'today'">
        AND o.created_date >= CURRENT_DATE
      </when>
      <when test="dateRange == 'week'">
        AND o.created_date >= CURRENT_DATE - INTERVAL '7 days'
      </when>
      <when test="dateRange == 'month'">
        AND o.created_date >= CURRENT_DATE - INTERVAL '30 days'
      </when>
    </choose>
    <if test="statuses != null">
      AND o.status IN
      <foreach collection="statuses" item="s" open="(" close=")" separator=",">
        #{s}
      </foreach>
    </if>
  </where>
</select>
```

**TC 생성 전략**:
```
분기 분석:
- if (userId): 2가지
- choose (dateRange): 4가지 (3 when + otherwise)
- if (statuses): 2가지

이론적 조합: 2 × 4 × 2 = 16가지

실제 생성 (대표 시나리오):
1. 최소: 모두 null
2. userId만
3. dateRange='today'만
4. statuses만
5. userId + dateRange='week'
6. userId + statuses
7. dateRange='month' + statuses
8. 최대: 모두 활성화

총 8개 TC
```

### 중첩 동적 SQL

**매퍼**:
```xml
<select id="nestedDynamic">
  SELECT * FROM users
  <where>
    <if test="searchType == 'basic'">
      <if test="userId != null">
        AND user_id = #{userId}::INTEGER
      </if>
      <if test="username != null">
        AND username = #{username}
      </if>
    </if>
    <if test="searchType == 'advanced'">
      <if test="ageRange != null">
        AND age BETWEEN #{ageRange.min}::INTEGER AND #{ageRange.max}::INTEGER
      </if>
      <if test="statusList != null">
        AND status IN
        <foreach collection="statusList" item="s" open="(" close=")" separator=",">
          #{s}
        </foreach>
      </if>
    </if>
  </where>
</select>
```

**TC 생성**:
```
경로 분석:
- searchType='basic' → userId/username 조합
- searchType='advanced' → ageRange/statusList 조합

TC 생성:
1. searchType='basic', userId만
2. searchType='basic', username만
3. searchType='basic', 둘 다
4. searchType='advanced', ageRange만
5. searchType='advanced', statusList만
6. searchType='advanced', 둘 다
7. searchType=null (모두 비활성)

총 7개 TC
```

---

## 11. TC 생성 최적화

### 커버리지 vs 효율성

**전략 레벨**:

**레벨 1: 최소 (빠름)**
```
- 모두 null
- 모두 활성화
- 총 2개 TC
```

**레벨 2: 표준 (권장)**
```
- 최소 케이스
- 각 분기 1회씩 활성화
- 주요 조합 (비즈니스 로직)
- 최대 케이스
- 총 4-10개 TC
```

**레벨 3: 철저 (느림)**
```
- 모든 의미 있는 조합
- 경계값 테스트
- 에러 케이스
- 총 10-30개 TC
```

### LLM 판단 기준

```
if (분기 수 <= 2):
  → 레벨 3 (모든 조합)
elif (분기 수 <= 4):
  → 레벨 2 (표준)
else:
  → 레벨 2 (대표 시나리오만)

foreach 있으면:
  → 0개/1개/3개 케이스 추가

choose 있으면:
  → 각 when + otherwise 케이스
```

---

## 12. 체크리스트

### TC 생성 시 확인 사항

- [ ] 모든 동적 SQL 태그 분석
- [ ] 파라미터-컬럼 매핑 정확
- [ ] 딕셔너리에서 샘플 값 조회
- [ ] 각 분기 최소 1회 커버
- [ ] foreach 0개/1개/N개 케이스
- [ ] choose 모든 when + otherwise
- [ ] TC 파일명 규칙 준수
- [ ] TC 파일 구조 일관성
- [ ] 기대 분기 명시
- [ ] 검증 규칙 포함

### TC 품질 확인

- [ ] 샘플 값이 실제 존재하는 값
- [ ] 타입 정보 정확
- [ ] null 케이스 포함
- [ ] 경계값 케이스 포함
- [ ] 비즈니스 로직 반영
- [ ] 에러 케이스 고려

---

## 문서 버전
- 버전: 1.0
- 작성일: 2026-07-26
- 목적: 동적 SQL 테스트 케이스 자동 생성 전략
