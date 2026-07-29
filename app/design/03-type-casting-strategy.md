# PostgreSQL 형변환 전략

## 핵심 원칙

**PostgreSQL은 Oracle과 달리 타입 체크가 엄격합니다.**
- Oracle: 암묵적 형변환 허용 (숫자 컬럼 = '123' → 자동 변환)
- PostgreSQL: 명시적 형변환 필요 (숫자 컬럼 = '123' → 에러 발생)

**기본 전략**:
> 딕셔너리에서 숫자/날짜 타입이면 **무조건 명시적 캐스팅 추가**

---

## 1. 형변환 대상 타입

### 필수 캐스팅 타입

| PostgreSQL 타입 | 캐스팅 구문 | 이유 |
|-----------------|------------|------|
| **integer** | `::INTEGER` | 문자열 전달 시 에러 방지 |
| **bigint** | `::BIGINT` | 큰 숫자 처리 |
| **smallint** | `::SMALLINT` | 작은 숫자 처리 |
| **numeric(p,s)** | `::NUMERIC` | 정밀도 보장, 소수점 처리 |
| **decimal(p,s)** | `::DECIMAL` | numeric과 동일 |
| **real** | `::REAL` | 부동소수점 |
| **double precision** | `::DOUBLE PRECISION` | 배정밀도 부동소수점 |
| **timestamp** | `::TIMESTAMP` | 날짜/시간 문자열 변환 |
| **timestamp with time zone** | `::TIMESTAMPTZ` | 타임존 포함 |
| **date** | `::DATE` | 날짜만 |
| **time** | `::TIME` | 시간만 |
| **boolean** | `::BOOLEAN` | true/false 변환 |

### 캐스팅 불필요 타입

| PostgreSQL 타입 | 캐스팅 | 이유 |
|-----------------|--------|------|
| **character varying** (varchar) | 불필요 | 문자열 타입 매칭 |
| **text** | 불필요 | 문자열 타입 |
| **char(n)** | 불필요* | *단, TRIM 고려 필요 |
| **json/jsonb** | 불필요 | 문자열 자동 파싱 |
| **uuid** | 불필요 | 문자열 자동 변환 |

---

## 2. 바인드 변수 캐스팅 위치

### 올바른 위치: 바인드 변수 뒤

```sql
-- ✅ 올바름: 바인드 변수에 캐스팅
WHERE user_id = #{userId}::INTEGER
WHERE amount > #{minAmount}::NUMERIC
WHERE created_date BETWEEN #{startDate}::TIMESTAMP AND #{endDate}::TIMESTAMP

-- ✅ 복잡한 표현식도 동일
WHERE user_id IN (#{id1}::INTEGER, #{id2}::INTEGER, #{id3}::INTEGER)
WHERE amount + #{adjustment}::NUMERIC > 1000
```

### 잘못된 위치: 컬럼에 캐스팅

```sql
-- ❌ 나쁨: 컬럼에 캐스팅 (인덱스 무효화)
WHERE user_id::TEXT = #{userId}
WHERE CAST(amount AS TEXT) = #{amount}
WHERE TO_CHAR(created_date, 'YYYY-MM-DD') = #{date}

-- 이유: 
-- 1. 인덱스 사용 불가 (Full Table Scan)
-- 2. 성능 저하
-- 3. 컬럼 모든 행을 변환해야 함
```

**원칙**:
> 컬럼은 그대로, 바인드 변수/리터럴을 컬럼 타입에 맞춤

---

## 3. 리터럴 vs 바인드 변수 처리

### 리터럴 변환

**숫자 리터럴**: 문자열 제거
```sql
-- Before (Oracle)
WHERE user_id = '123'
WHERE amount > '1000.50'

-- After (PostgreSQL)
WHERE user_id = 123
WHERE amount > 1000.50

-- 이유: 리터럴은 코드에서 바로 수정 가능, 가장 깔끔
```

**날짜 리터럴**: 명시적 캐스팅
```sql
-- Before (Oracle)
WHERE created_date > '2024-01-01'
WHERE order_time = '2024-01-01 10:30:00'

-- After (PostgreSQL)
WHERE created_date > '2024-01-01'::DATE
WHERE order_time = '2024-01-01 10:30:00'::TIMESTAMP

-- 이유: 날짜 형식 명확화, 파싱 에러 방지
```

### 바인드 변수 변환

**숫자 바인드**: 명시적 캐스팅 추가
```sql
-- Before (Oracle)
WHERE user_id = #{userId}
WHERE amount > #{minAmount}

-- After (PostgreSQL)
WHERE user_id = #{userId}::INTEGER
WHERE amount > #{minAmount}::NUMERIC

-- 이유: 자바에서 String 전달해도 안전
```

**날짜 바인드**: 명시적 캐스팅 추가
```sql
-- Before (Oracle)
WHERE created_date > #{date}
WHERE order_time BETWEEN #{start} AND #{end}

-- After (PostgreSQL)
WHERE created_date > #{date}::TIMESTAMP
WHERE order_time BETWEEN #{start}::TIMESTAMP AND #{end}::TIMESTAMP

-- 이유: 날짜 문자열 자동 변환
```

**문자열 바인드**: 변환 불필요
```sql
-- Before (Oracle)
WHERE username = #{username}
WHERE status = #{status}

-- After (PostgreSQL)
WHERE username = #{username}
WHERE status = #{status}

-- 변환 없음: VARCHAR 타입이므로 그대로 유지
```

---

## 4. 딕셔너리 기반 판단 로직

### LLM 판단 프로세스

```
Step 1: SQL 파싱
  WHERE user_id = #{userId} 발견
  → 컬럼: "users.user_id"
  → 바인드 변수: "userId"

Step 2: 딕셔너리 조회
  lookup("users.user_id")
  → {
      "data_type": "integer",
      "cast_hint": {
        "needs_cast_from_string": true,
        "cast_syntax": "::INTEGER"
      }
    }

Step 3: 타입 분류
  if data_type in [integer, bigint, smallint, numeric, decimal, 
                   real, double precision, timestamp, date, time, boolean]:
    → 캐스팅 필요
  else:
    → 캐스팅 불필요

Step 4: 변환 적용
  #{userId} → #{userId}::INTEGER
```

### 타입별 자동 판단 규칙

```javascript
function needsCasting(dataType) {
  // 숫자 타입
  if (['integer', 'bigint', 'smallint', 
       'numeric', 'decimal', 
       'real', 'double precision'].includes(dataType)) {
    return { needs: true, syntax: `::${dataType.toUpperCase()}` }
  }
  
  // 날짜/시간 타입
  if (['timestamp', 'timestamp with time zone', 
       'date', 'time'].includes(dataType)) {
    return { needs: true, syntax: `::${dataType.toUpperCase()}` }
  }
  
  // Boolean
  if (dataType === 'boolean') {
    return { needs: true, syntax: '::BOOLEAN' }
  }
  
  // 문자열 타입 (캐스팅 불필요)
  if (['character varying', 'text', 'character'].includes(dataType)) {
    return { needs: false }
  }
  
  // 기타
  return { needs: false }
}
```

---

## 5. 실전 예시

### 예시 1: 단순 SELECT

**Oracle 원본**:
```sql
<select id="getUser">
  SELECT * FROM users 
  WHERE user_id = #{userId}
    AND username = #{username}
    AND created_date > #{since}
</select>
```

**딕셔너리 조회**:
```json
{
  "users.user_id": {"data_type": "integer"},
  "users.username": {"data_type": "character varying"},
  "users.created_date": {"data_type": "timestamp"}
}
```

**PostgreSQL 변환**:
```sql
<select id="getUser">
  SELECT * FROM users 
  WHERE user_id = #{userId}::INTEGER
    AND username = #{username}
    AND created_date > #{since}::TIMESTAMP
</select>
```

**변경 사항**:
- `user_id`: integer → 캐스팅 추가
- `username`: varchar → 유지
- `created_date`: timestamp → 캐스팅 추가

---

### 예시 2: 리터럴 포함

**Oracle 원본**:
```sql
<select id="getActiveUsers">
  SELECT * FROM users 
  WHERE status = 'A'
    AND user_id > '1000'
    AND created_date > '2024-01-01'
</select>
```

**딕셔너리 조회**:
```json
{
  "users.status": {"data_type": "character", "length": 1},
  "users.user_id": {"data_type": "integer"},
  "users.created_date": {"data_type": "timestamp"}
}
```

**PostgreSQL 변환**:
```sql
<select id="getActiveUsers">
  SELECT * FROM users 
  WHERE status = 'A'
    AND user_id > 1000
    AND created_date > '2024-01-01'::TIMESTAMP
</select>
```

**변경 사항**:
- `status = 'A'`: char → 유지 (리터럴도 문자)
- `user_id > '1000'`: integer → **'1000' → 1000** (문자열 제거)
- `created_date > '2024-01-01'`: timestamp → 캐스팅 추가

---

### 예시 3: 복잡한 조건

**Oracle 원본**:
```sql
<select id="getOrders">
  SELECT * FROM orders 
  WHERE user_id = #{userId}
    AND amount BETWEEN #{minAmount} AND #{maxAmount}
    AND status IN ('A', 'B', 'C')
    AND created_date >= #{startDate}
</select>
```

**딕셔너리 조회**:
```json
{
  "orders.user_id": {"data_type": "bigint"},
  "orders.amount": {"data_type": "numeric", "precision": 10, "scale": 2},
  "orders.status": {"data_type": "character", "length": 1},
  "orders.created_date": {"data_type": "timestamp"}
}
```

**PostgreSQL 변환**:
```sql
<select id="getOrders">
  SELECT * FROM orders 
  WHERE user_id = #{userId}::BIGINT
    AND amount BETWEEN #{minAmount}::NUMERIC AND #{maxAmount}::NUMERIC
    AND status IN ('A', 'B', 'C')
    AND created_date >= #{startDate}::TIMESTAMP
</select>
```

**변경 사항**:
- `user_id`: bigint → 캐스팅
- `amount BETWEEN`: numeric → 양쪽 모두 캐스팅
- `status IN`: char → 유지 (리터럴 문자)
- `created_date`: timestamp → 캐스팅

---

### 예시 4: INSERT 구문

**Oracle 원본**:
```sql
<insert id="insertOrder">
  INSERT INTO orders (user_id, amount, status, created_date)
  VALUES (#{userId}, #{amount}, #{status}, #{createdDate})
</insert>
```

**딕셔너리 조회**:
```json
{
  "orders.user_id": {"data_type": "bigint"},
  "orders.amount": {"data_type": "numeric"},
  "orders.status": {"data_type": "character varying"},
  "orders.created_date": {"data_type": "timestamp"}
}
```

**PostgreSQL 변환**:
```sql
<insert id="insertOrder">
  INSERT INTO orders (user_id, amount, status, created_date)
  VALUES (#{userId}::BIGINT, #{amount}::NUMERIC, #{status}, #{createdDate}::TIMESTAMP)
</insert>
```

**변경 사항**:
- VALUES 절의 바인드 변수도 동일하게 캐스팅
- 숫자/날짜만 캐스팅, 문자열(status)은 유지

---

### 예시 5: UPDATE 구문

**Oracle 원본**:
```sql
<update id="updateAmount">
  UPDATE orders 
  SET amount = amount + #{adjustment},
      updated_date = #{now}
  WHERE user_id = #{userId}
    AND status = #{status}
</update>
```

**딕셔너리 조회**:
```json
{
  "orders.amount": {"data_type": "numeric"},
  "orders.updated_date": {"data_type": "timestamp"},
  "orders.user_id": {"data_type": "bigint"},
  "orders.status": {"data_type": "character varying"}
}
```

**PostgreSQL 변환**:
```sql
<update id="updateAmount">
  UPDATE orders 
  SET amount = amount + #{adjustment}::NUMERIC,
      updated_date = #{now}::TIMESTAMP
  WHERE user_id = #{userId}::BIGINT
    AND status = #{status}
</update>
```

**변경 사항**:
- SET 절의 바인드 변수도 캐스팅
- WHERE 절도 동일 규칙 적용

---

## 6. 특수 케이스

### CHAR(n) 타입 - TRIM 고려

**문제**:
```sql
-- Oracle: 패딩 자동 무시
'Y' = 'Y '  → TRUE

-- PostgreSQL: 엄격한 비교
'Y' = 'Y '  → FALSE
```

**해결 방법**:

**방법 A**: TRIM 사용 (인덱스 불가)
```sql
WHERE TRIM(status) = #{status}
```

**방법 B**: 자바에서 패딩 전달 (권장)
```sql
WHERE status = #{status}
-- 자바: params.put("status", "Y ");  // 공백 포함
```

**방법 C**: 컬럼 타입 변경 (DDL 수정)
```sql
ALTER TABLE users ALTER COLUMN status TYPE VARCHAR(1);
```

**LLM 처리**:
```
1. 딕셔너리 조회: data_type="character", length=1
2. 주석 추가:
   <!-- CHAR(1) 타입: 자바에서 패딩 포함 전달 또는 TRIM 고려 -->
   WHERE status = #{status}
3. Warning 리스트에 추가:
   "CHAR 타입 패딩 주의 필요"
```

### NULL 처리 함수와 형변환

**Oracle**:
```sql
WHERE NVL(amount, 0) > #{threshold}
```

**PostgreSQL 변환**:
```sql
WHERE COALESCE(amount, 0) > #{threshold}::NUMERIC
```

**판단**:
- `amount`는 NUMERIC 컬럼
- `COALESCE(amount, 0)` 결과도 NUMERIC
- `#{threshold}` 캐스팅 필요

### 연산 결과와 형변환

**Oracle**:
```sql
WHERE amount * 1.1 > #{maxAmount}
WHERE SUBSTR(code, 1, 2) = #{prefix}
WHERE ROUND(amount, 2) = #{targetAmount}
```

**PostgreSQL 변환**:
```sql
WHERE amount * 1.1 > #{maxAmount}::NUMERIC
WHERE SUBSTR(code, 1, 2) = #{prefix}
WHERE ROUND(amount, 2) = #{targetAmount}::NUMERIC
```

**판단**:
- 연산 결과 타입 추론
- `amount * 1.1` → NUMERIC
- `SUBSTR(...)` → TEXT
- `ROUND(amount, 2)` → NUMERIC

### IN 절 형변환

**Oracle**:
```sql
WHERE user_id IN (#{id1}, #{id2}, #{id3})
```

**PostgreSQL 변환**:
```sql
WHERE user_id IN (#{id1}::INTEGER, #{id2}::INTEGER, #{id3}::INTEGER)
```

**MyBatis foreach 사용 시**:
```xml
<select id="getUsersByIds">
  SELECT * FROM users 
  WHERE user_id IN
  <foreach collection="userIds" item="id" open="(" separator="," close=")">
    #{id}::INTEGER
  </foreach>
</select>
```

---

## 7. 형변환 누락 시 에러

### 실제 에러 메시지

```sql
-- SQL
WHERE user_id = #{userId}

-- 자바에서 String 전달
params.put("userId", "123");

-- PostgreSQL 에러
ERROR: operator does not exist: integer = text
HINT: No operator matches the given name and argument types. 
      You might need to add explicit type casts.
```

### 해결
```sql
WHERE user_id = #{userId}::INTEGER
```

---

## 8. 성능 고려사항

### 올바른 패턴 (인덱스 사용 가능)

```sql
-- ✅ 바인드 변수에 캐스팅
WHERE user_id = #{userId}::INTEGER
-- → 인덱스 사용 가능

-- ✅ 리터럴 타입 변경
WHERE user_id = 123
-- → 인덱스 사용 가능
```

### 잘못된 패턴 (인덱스 무효화)

```sql
-- ❌ 컬럼에 함수 적용
WHERE user_id::TEXT = #{userId}
-- → 인덱스 사용 불가 (Full Scan)

-- ❌ 컬럼 변환
WHERE TO_CHAR(user_id) = #{userId}
-- → 인덱스 사용 불가

-- ❌ 컬럼 계산
WHERE user_id + 0 = #{userId}::INTEGER
-- → 인덱스 사용 불가
```

**원칙**:
> WHERE 절 좌변(컬럼)은 그대로, 우변(바인드/리터럴)을 맞춤

---

## 9. LLM 프롬프트 가이드

### 형변환 판단 체크리스트

```
각 바인드 변수에 대해:

1. 딕셔너리 조회
   lookup("table.column") → data_type 확인

2. 타입 분류
   - integer/bigint/smallint → ::INTEGER 계열
   - numeric/decimal → ::NUMERIC
   - timestamp/date/time → ::TIMESTAMP 계열
   - varchar/text → 캐스팅 불필요
   - character(n) → 주석 추가 (CHAR 패딩)

3. 변환 적용
   #{var} → #{var}::TYPE

4. 리터럴 별도 처리
   - 숫자 리터럴: '123' → 123
   - 날짜 리터럴: '2024-01-01' → '2024-01-01'::DATE

5. 변경 사항 기록
   - 원본
   - 변환 결과
   - 이유
```

### 출력 형식

```json
{
  "converted_sql": "...",
  "type_casts": [
    {
      "variable": "userId",
      "column": "users.user_id",
      "column_type": "integer",
      "cast_applied": "::INTEGER",
      "reason": "숫자 타입, String 전달 대비"
    },
    {
      "variable": "username",
      "column": "users.username",
      "column_type": "character varying",
      "cast_applied": null,
      "reason": "문자열 타입, 캐스팅 불필요"
    }
  ]
}
```

---

## 10. MyBatis 대안 문법 (참고만)

### 대안 1: jdbcType 지정

```xml
<!-- PostgreSQL 캐스팅 대신 -->
<select id="getUser">
  WHERE user_id = #{userId, jdbcType=INTEGER}
</select>
```

**특징**:
- MyBatis가 PreparedStatement.setInt() 호출
- 자바 타입 변환 필요
- SQL에 캐스팅 구문 없음

### 대안 2: typeHandler 사용

```xml
<!-- typeHandler 등록 -->
<select id="getUser">
  WHERE user_id = #{userId, typeHandler=StringToIntegerHandler}
</select>
```

**특징**:
- 커스텀 변환 로직
- 프로젝트 전역 설정 가능
- 복잡도 증가

### 대안 3: javaType + jdbcType

```xml
<select id="getUser">
  WHERE user_id = #{userId, javaType=String, jdbcType=INTEGER}
</select>
```

**특징**:
- 명시적 타입 매핑
- 코드 가독성 저하

### 권장 방법: PostgreSQL 네이티브 캐스팅

```xml
<!-- 가장 명확하고 간단 -->
<select id="getUser">
  WHERE user_id = #{userId}::INTEGER
</select>
```

**이유**:
1. SQL 레벨에서 명확
2. MyBatis 설정 불필요
3. 자바 타입 무관하게 안전
4. 디버깅 쉬움 (SQL 로그에 그대로 표시)
5. 다른 쿼리 툴에서도 동일하게 동작

---

## 11. 체크리스트

### 변환 시 확인 사항

- [ ] 모든 숫자 타입 바인드 변수에 캐스팅 추가
- [ ] 모든 날짜/시간 타입 바인드 변수에 캐스팅 추가
- [ ] 문자열 타입은 캐스팅 생략
- [ ] 숫자 리터럴 문자열 제거 ('123' → 123)
- [ ] 날짜 리터럴 캐스팅 추가
- [ ] CHAR(n) 타입 주석 추가
- [ ] 컬럼에 캐스팅하지 않음 (인덱스 보호)
- [ ] IN 절 각 항목 캐스팅
- [ ] BETWEEN 양쪽 캐스팅
- [ ] INSERT/UPDATE VALUES 절 캐스팅

### 검증 사항

- [ ] 딕셔너리 조회 성공
- [ ] 캐스팅 구문 정확성
- [ ] 인덱스 사용 가능 확인
- [ ] 변경 사항 로깅
- [ ] Warning 리스트 작성

---

## 문서 버전
- 버전: 1.0
- 작성일: 2026-07-26
- 목적: PostgreSQL 형변환 전략 상세 정의
