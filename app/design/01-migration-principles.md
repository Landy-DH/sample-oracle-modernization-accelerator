# Oracle → PostgreSQL 매퍼 마이그레이션 기본 원칙

## 핵심 아키텍처

```
[1] 스키마 딕셔너리 생성
     ↓
[2] 조회 함수 제공
     ↓
[3] LLM이 매퍼 변환하면서 함수 호출
     ↓
[4] 형변환 명시적 처리
     ↓
[5] 테스트 케이스 자동 생성
     ↓
[6] 검증
```

---

## 1. 스키마 딕셔너리 설계

### 목적
- 모든 테이블.컬럼의 PostgreSQL 타입 정보 보관
- LLM이 조회해서 정확한 형변환 판단 근거로 사용

### 딕셔너리 구조
```
키: "table.column" (소문자)
값: {
  - 테이블명
  - 컬럼명
  - PostgreSQL 데이터 타입
  - nullable 여부
  - 길이/정밀도/스케일
  - 샘플 값 (실제 데이터 1건)
  - 형변환 힌트
}
```

### 필수 정보
- **data_type**: integer, varchar, timestamp, numeric 등
- **샘플 값**: 실제 데이터 1건 (타입 확인용)
- **형변환 힌트**: 
  - 문자열→숫자 캐스팅 필요 여부
  - CHAR 타입 TRIM 필요 여부
  - 날짜 캐스팅 문법

### 생성 방법
- PostgreSQL information_schema.columns 조회
- 각 테이블 LIMIT 1로 샘플 데이터 수집
- JSON 파일로 저장

---

## 2. 조회 함수 설계

### 함수 인터페이스
```
입력: "table.column" (문자열)
출력: {
  found: true/false,
  data_type: "integer",
  is_nullable: false,
  numeric_precision: 32,
  sample_value: 12345,
  cast_hint: {
    needs_cast_from_string: true,
    cast_syntax: "::INTEGER",
    performance_note: "리터럴은 숫자로, 바인드는 ::cast"
  }
}
```

### 구현 형태
- 스탠드얼론 스크립트 (node schema-lookup.js "users.user_id")
- 또는 JSON 파일을 Read로 직접 읽기
- LLM이 Bash tool로 실행하거나 Read로 파싱

### 조회 실패 시
- found: false 반환
- LLM은 보수적 변환 + warning 추가

---

## 3. LLM 프롬프트 전략

### 기본 원칙

**역할 정의**
```
당신은 Oracle SQL을 PostgreSQL로 변환하는 전문가입니다.
스키마 딕셔너리 조회 함수를 활용하여 정확한 형변환을 수행하세요.
```

**핵심 지침**
1. **구문 변환**: Oracle 전용 문법 → PostgreSQL 표준
2. **형변환 명시**: 모든 비교 연산에서 타입 체크 + 캐스팅 (숫자/날짜 타입 필수)
3. **테스트 케이스 생성**: 동적 SQL 분기별 TC 자동 생성
4. **성능 고려**: 컬럼에 함수 적용 최소화
5. **검증 가능**: 모든 변환 근거를 로깅

### 프롬프트 구조

#### Phase 1: 컬럼 추출
```
입력된 매퍼 SQL을 분석하여:
1. WHERE 절의 모든 컬럼 추출
2. JOIN 조건의 모든 컬럼 추출  
3. SELECT/INSERT/UPDATE의 모든 컬럼 추출
4. 테이블.컬럼 형태로 정규화

예시:
WHERE user_id = #{userId} 
  → "users.user_id" 추출 (FROM 절에서 테이블 파악)
```

#### Phase 2: 딕셔너리 조회
```
각 컬럼에 대해:
1. 조회 함수 실행: lookup("users.user_id")
2. 반환된 타입 정보 확인
3. 형변환 필요 여부 판단

조회 결과 해석:
- data_type: "integer" → 숫자 타입
- needs_cast_from_string: true → 바인드 변수에 ::cast 필요
- needs_trim: true → CHAR 타입, TRIM() 고려
```

#### Phase 3: 변환 규칙 적용

**리터럴 변환**
```
WHERE user_id = '123'
→ lookup("users.user_id") → integer
→ 변환: WHERE user_id = 123
→ 이유: 리터럴 문자열을 숫자로 수정 (타입 매칭)
```

**바인드 변수 변환**
```
WHERE user_id = #{userId}
→ lookup("users.user_id") → integer
→ 변환: WHERE user_id = #{userId}::INTEGER
→ 이유: PreparedStatement에 명시적 캐스팅 (자바에서 String 전달해도 안전)
```

**CHAR 타입 처리**
```
WHERE status = #{status}
→ lookup("users.status") → char(1)
→ 옵션 A: WHERE TRIM(status) = #{status}
→ 옵션 B: WHERE status = #{status} (자바에서 'Y ' 패딩 전달)
→ 선택: 옵션 B 권장 (인덱스 사용 가능)
→ 주석 추가: 자바에서 CHAR 패딩 주의
```

**날짜 리터럴**
```
WHERE created_date > '2024-01-01'
→ lookup("users.created_date") → timestamp
→ 변환: WHERE created_date > '2024-01-01'::TIMESTAMP
→ 이유: 명시적 타입 캐스팅
```

**JOIN 조건**
```
FROM users u JOIN orders o ON u.user_id = o.user_id
→ lookup("users.user_id") → integer
→ lookup("orders.user_id") → integer
→ 변환: 불필요 (양쪽 타입 동일)
```

**NULL 처리 함수**
```
NVL(status, 'N')
→ lookup("users.status") → varchar/char
→ 변환: COALESCE(status, 'N')
→ 추가 체크: 타입 일관성 (NULL 대체값 타입)
```

#### Phase 4: 테스트 케이스 생성
```
동적 SQL 분기 분석 및 TC 생성:

1. 동적 SQL 태그 추출
   - <if test="...">
   - <choose><when><otherwise>
   - <foreach collection="...">

2. 테스트 시나리오 설계
   - 분기 조합 분석
   - 대표 케이스 선택 (최소/단일/조합/최대)
   - foreach: 0개/1개/N개 케이스

3. 샘플 값 조회
   - 파라미터-컬럼 매핑 추론
   - 딕셔너리에서 샘플 값 가져오기

4. TC 파일 생성
   - 파일명: {매퍼명}_{sqlId}_tc{번호}.json
   - 내용: 파라미터, 기대 분기, 샘플 값, 검증 규칙
```

#### Phase 5: 출력 형식

```json
{
  "converted_sql": "변환된 SQL 전문",
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
  "warnings": [
    {
      "column": "unknown_table.unknown_col",
      "issue": "Column not found in dictionary",
      "action": "Kept original, manual review needed"
    }
  ],
  "test_cases_generated": [
    {
      "file": "UserMapper_searchUsers_tc001.json",
      "description": "userId만 있는 경우",
      "branches_covered": ["userId != null"]
    }
  ]
}
```

---

## 4. 전체 워크플로우

### Step 1: 사전 준비
**목표**: 스키마 딕셔너리 생성

**작업**:
- PostgreSQL 접속하여 스키마 메타데이터 추출
- 각 테이블 샘플 데이터 1건 조회
- JSON 파일로 저장
- 조회 함수 테스트

**결과물**:
- schema-dictionary.json
- schema-lookup 스크립트/함수

---

### Step 2: 매퍼 파일 수집
**목표**: 변환 대상 파일 리스트

**작업**:
- MyBatis 매퍼 XML 파일 모두 찾기
- 복잡도별 분류 (단순 CRUD / 복잡한 쿼리)
- 우선순위 결정

**LLM 역할**:
- find 명령으로 **/*.xml 검색
- SQL 복잡도 분석 (JOIN 수, 서브쿼리 여부)

---

### Step 3: 매퍼 변환 (핵심)
**목표**: SQL 구문 + 형변환

**LLM에게 제공**:
- 변환 프롬프트 (위의 Phase 1~4)
- 딕셔너리 조회 방법
- 매퍼 파일 내용

**LLM 작업 흐름**:
1. SQL 파싱하여 모든 테이블.컬럼 추출
2. 각 컬럼마다 딕셔너리 조회 함수 실행
3. 조회 결과 기반 형변환 판단 (숫자/날짜 타입 필수 캐스팅)
4. 구문 변환 (NVL→COALESCE 등) 수행
5. 명시적 캐스팅 추가
6. 동적 SQL 분기 분석 및 테스트 케이스 생성
7. 변환 근거와 함께 출력

**병렬 처리**:
- 매퍼 파일별로 독립적 변환 가능
- Workflow pipeline 활용

**결과물**:
- 변환된 매퍼 XML
- 변경 사항 로그
- 테스트 케이스 파일 (TC)
- Warning 리스트

---

### Step 4: 검증
**목표**: 변환 정확성 확인

**검증 항목**:
1. **구문 검증**: PostgreSQL에서 PREPARE 테스트
2. **타입 검증**: 모든 비교 연산의 타입 매칭 확인
3. **누락 검증**: 조회되지 않은 컬럼 찾기
4. **의미 검증**: 원본과 의미적 동등성
5. **TC 기반 검증**: 생성된 테스트 케이스로 Oracle/PostgreSQL 결과 비교

**TC 활용 검증**:
```
각 TC 파일에 대해:
1. Oracle에서 실행 (원본 SQL + 파라미터)
2. PostgreSQL에서 실행 (변환 SQL + 파라미터)
3. 결과 비교 (행 수, 컬럼 값, NULL 처리)
4. 차이점 리포트
```

**LLM 역할** (독립적 에이전트):
```
원본 SQL과 변환 SQL을 비교:
- 같은 결과를 리턴하는가?
- 형변환이 의미를 바꾸지 않았는가?
- 성능에 악영향은 없는가?
- NULL 처리가 동일한가?
- 동적 SQL 모든 분기 커버되었는가?

스키마 딕셔너리 재조회하여 크로스체크
```

---

### Step 5: 수동 검토 대상 추출
**목표**: 사람이 봐야 할 케이스 분류

**자동 처리 불가 케이스**:
- 딕셔너리에 없는 컬럼 (동적 테이블? 뷰? 오타?)
- CONNECT BY 계층 쿼리 (WITH RECURSIVE 복잡)
- MERGE 구문 (ON CONFLICT 복잡)
- 복잡한 DECODE/CASE 중첩
- ${} 동적 SQL

**LLM 출력**:
```json
{
  "manual_review_needed": [
    {
      "file": "UserMapper.xml",
      "line": 45,
      "reason": "Column 'dynamic_table.col' not in dictionary",
      "suggestion": "Check if this is a view or verify table name"
    }
  ]
}
```

---

## 5. 프롬프트 세부 지침

### 형변환 우선순위

**1순위: 리터럴 수정**
```sql
WHERE user_id = '123' 
→ WHERE user_id = 123
(문자열 리터럴을 숫자로 - 가장 깔끔)
```

**2순위: 바인드 변수 캐스팅**
```sql
WHERE user_id = #{userId}
→ WHERE user_id = #{userId}::INTEGER
(자바 코드 수정 없이 안전)
```

**3순위: 컬럼 캐스팅 (비추천)**
```sql
WHERE user_id::TEXT = #{userId}
(인덱스 사용 불가, 성능 저하)
```

### 성능 고려 사항

**인덱스 무효화 방지**
```sql
나쁨: WHERE TRIM(status) = 'Y'
좋음: WHERE status = 'Y '  (CHAR 패딩 포함)

나쁨: WHERE TO_CHAR(user_id) = '123'
좋음: WHERE user_id = 123
```

**LLM 판단 기준**:
- 컬럼에 함수 적용하면 warning + 성능 노트
- 대안 제시 (리터럴 변환 등)
- 불가피한 경우만 허용

### CHAR 타입 특수 처리

**문제 인식**:
```sql
Oracle: 'Y' = 'Y '  → TRUE (패딩 무시)
PostgreSQL: 'Y' = 'Y '  → FALSE (엄격)
```

**LLM 전략**:
```
딕셔너리 조회 시 data_type="character" 감지
→ 옵션 제시:
  A. TRIM(column) 사용 (인덱스 불가)
  B. 자바에서 'Y ' 패딩 전달 (권장)
  C. 컬럼 타입을 VARCHAR로 변경 (DDL 수정)
```

### NULL 처리 차이

**Oracle vs PostgreSQL**
```sql
Oracle: 'A' || NULL → 'A'
PostgreSQL: 'A' || NULL → NULL

Oracle: NVL(col, default)
PostgreSQL: COALESCE(col, default)
```

**LLM 변환**:
```
NVL → COALESCE (직접 대응)
Concat에서 NULL → COALESCE 추가
'A' || col → 'A' || COALESCE(col, '')
```

---

## 6. 에러 처리 전략

### 딕셔너리 조회 실패
```
컬럼: "unknown.column"
조회 결과: {found: false}

LLM 액션:
1. Warning 추가
2. 원본 유지 (변환 안 함)
3. 수동 검토 플래그
4. 계속 진행 (중단하지 않음)
```

### 복잡한 표현식
```sql
WHERE DECODE(status, 'A', 1, 'B', 2, 3) = #{value}

LLM 액션:
1. DECODE → CASE 변환
2. 결과 타입 추론 (숫자)
3. #{value}에 ::INTEGER 추가
4. 복잡도 노트
```

### 애매한 타입
```sql
WHERE col = #{param}
조회: col은 VARCHAR
param 용도: 불명확 (숫자? 문자?)

LLM 액션:
1. VARCHAR이므로 캐스팅 불필요
2. 주석: "자바에서 String 전달 권장"
3. Warning: "param 타입 확인 필요"
```

---

## 7. 출력물 구조

### 변환된 매퍼 파일
- 원본 구조 유지
- 변환된 SQL 삽입
- 주석으로 변경 사항 표시 (선택적)

### 변환 리포트
```json
{
  "file": "UserMapper.xml",
  "status": "success",
  "statistics": {
    "total_queries": 15,
    "columns_checked": 87,
    "casts_added": 23,
    "test_cases_generated": 42,
    "warnings": 2
  },
  "lookups": [...],
  "changes": [...],
  "test_cases": [
    {
      "file": "UserMapper_searchUsers_tc001.json",
      "description": "userId만 있는 경우",
      "branches_covered": ["userId != null"]
    }
  ],
  "warnings": [...]
}
```

### 수동 검토 리스트
```json
[
  {
    "file": "OrderMapper.xml",
    "query_id": "complexQuery",
    "issue": "CONNECT BY hierarchy",
    "action_needed": "Convert to WITH RECURSIVE manually"
  }
]
```

---

## 8. 품질 보장

### 자동 검증
- PostgreSQL PREPARE 구문 테스트
- 타입 매칭 크로스체크
- 딕셔너리 커버리지 (조회 성공률)

### LLM 이중 검증
- 변환 LLM: 변환 수행
- 검증 LLM: 독립적 검토 (adversarial)
- 불일치 시 수동 검토

### TC 기반 자동 테스트
```
생성된 TC 파일로 실제 쿼리 실행:
- 각 TC의 파라미터로 Oracle SQL 실행
- 동일 파라미터로 PostgreSQL SQL 실행
- 결과 비교 (행 수, 컬럼 값, NULL 처리)
- 모든 동적 SQL 분기 커버리지 확인
- 차이점 리포트 생성
```

---

## 9. 핵심 성공 요소

### 딕셔너리 품질
- ✅ 모든 컬럼 포함
- ✅ 정확한 타입 정보
- ✅ 유효한 샘플 값
- ✅ 형변환 힌트 제공

### 프롬프트 명확성
- ✅ 조회 함수 사용법 명시
- ✅ 변환 규칙 우선순위
- ✅ 출력 형식 구조화
- ✅ 에러 처리 지침

### LLM 자율성
- ✅ 원칙 제시, 세부는 LLM 판단
- ✅ 예시로 패턴 학습
- ✅ Warning으로 불확실성 표현
- ✅ 검증 가능한 출력

### 프로세스 견고성
- ✅ 조회 실패해도 계속 진행
- ✅ 병렬 처리 (파일별 독립)
- ✅ 검증 단계 분리
- ✅ 수동 검토 대상 명확화

---

## 10. Opus 4.8 활용 포인트

**높은 추론 능력 활용**
- 복잡한 SQL 파싱
- 타입 추론 (딕셔너리 + 컨텍스트)
- 성능 영향 판단
- 의미적 동등성 검증

**구조화된 출력**
- JSON schema로 일관된 결과
- 파싱 오류 없이 자동화 가능

**장문 컨텍스트**
- 딕셔너리 전체 + 매퍼 + 프롬프트
- 큰 매퍼 파일도 한 번에 처리

**불확실성 표현**
- Warning으로 자연스럽게 플래그
- 과도한 확신 지양

**Effort 레벨 조절**
- 단순 CRUD: low effort
- 복잡한 쿼리: high effort
- 검증 단계: high effort

---

## 주요 제약사항

### 처리 불가 항목
- **${} 동적 SQL**: 런타임 값 예측 불가, 별도 전략 필요
- **동적 테이블명**: 딕셔너리 조회 불가
- **뷰(View)**: 스키마 딕셔너리에 포함 여부에 따라

### 수동 처리 권장
- CONNECT BY 계층 쿼리 (WITH RECURSIVE 복잡도 높음)
- MERGE 구문 (비즈니스 로직 이해 필요)
- 복잡한 PL/SQL 블록

---

## 문서 버전
- 버전: 1.0
- 작성일: 2026-07-26
- 목적: Oracle → PostgreSQL MyBatis 매퍼 마이그레이션 기본 원칙
