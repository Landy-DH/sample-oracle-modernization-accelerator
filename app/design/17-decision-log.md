# OMA 의사결정 기록 (Decision Log)

## 목적

OMA 설계 및 구현 과정에서 내린 중요한 결정들을 기록하여, 나중에 "왜 이렇게 했지?"라는 질문에 답할 수 있도록 함

---

## 결정 001: SqlSessionFactory vs XML Parser

**날짜**: 2026-07-26  
**결정자**: 설계팀  
**문서**: `10-validation-design.md`

### 상황
검증 시 MyBatis 매퍼에서 실제 실행될 SQL을 추출하는 방법 선택 필요

### 선택지
**A) XML Parser + 정규식**
- XML 파싱해서 `<select>`, `<if>` 등 추출
- 정규식으로 동적 SQL 처리
- 바인드 변수 수동 치환

**B) MyBatis SqlSessionFactory**
- MyBatis의 `BoundSql` API 사용
- `BoundSql boundSql = ms.getBoundSql(parameters)`
- 동적 SQL 자동 평가

### 선택
✅ **B) SqlSessionFactory**

### 이유
1. **정확성**: MyBatis가 직접 처리 → 100% 정확
2. **동적 SQL**: `<if>`, `<choose>`, `<foreach>` 자동 평가
3. **`<include>` 해결**: refid 참조 자동 해결
4. **실전 검증**: 사용자 피드백 "XML 파서는 품질 낮았음"

### 트레이드오프
**장점**:
- 정확성 100%
- 유지보수 쉬움 (MyBatis가 알아서)

**단점**:
- Java 의존성 필요
- Python-Java 통신 필요 (subprocess, JSON)
- 복잡도 증가

**결론**: 정확성 > 복잡성

### 영향
- Java 검증 모듈 필요 (`java-validator/`)
- Python-Java 브릿지 필요 (`java_bridge.py`)
- Maven 빌드 추가

---

## 결정 002: WORK_LOG.md 폐기

**날짜**: 2026-07-27  
**결정자**: 설계팀  

### 상황
코드 변경 이력을 어디에 기록할지 선택 필요

### 선택지
**A) WORK_LOG.md (중앙 집중)**
- 모든 작업 이력을 한 파일에
- 장점: 전체 이력 한눈에
- 단점: 파일별 상세 이력 파악 어려움

**B) 파일별 변경 이력 (분산)**
- 각 파일 상단에 변경 이력 작성
- 장점: 파일 보면 바로 이력 확인
- 단점: 전체 이력 파악 어려움

**C) 둘 다 사용**
- WORK_LOG.md: 전체 이력
- 파일별: 상세 이력
- 단점: 중복, 유지보수 부담

### 선택
✅ **B) 파일별 변경 이력만**

### 이유
1. **버그 원인 즉시 파악**: 파일 열면 바로 이력 보임
2. **중복 제거**: WORK_LOG.md와 중복 불필요
3. **AI 코딩 효율**: AI가 파일 읽으면 이력도 자동 읽음

### 대안
- README.md에 디렉토리 구조 + 모듈 설명
- WORK_LOG.md → 삭제
- 파일별 이력 → 유지

### 영향
- WORK_LOG.md 삭제
- README.md 강화
- 15-coding-guidelines.md에 파일별 이력 규칙 명시

---

## 결정 003: Dictionary 기반 타입 캐스팅

**날짜**: 2026-07-26  
**결정자**: 설계팀  
**문서**: `01-migration-principles.md`, `03-type-casting-strategy.md`

### 상황
PostgreSQL은 엄격한 타입 시스템 → Oracle에서는 `'123'`이 자동 변환되지만 PostgreSQL은 에러

### 선택지
**A) LLM이 추론**
- LLM에게 "타입 맞춰서 변환해줘"
- 장점: 간단
- 단점: 부정확, 일관성 없음

**B) 딕셔너리 기반**
- PostgreSQL 스키마에서 정확한 타입 추출
- 딕셔너리에 저장
- LLM이 딕셔너리 조회 후 캐스팅

### 선택
✅ **B) 딕셔너리 기반**

### 이유
1. **정확성**: 실제 DB 스키마 기반 → 100% 정확
2. **일관성**: 같은 컬럼은 항상 같은 타입
3. **디버깅**: 딕셔너리 보면 타입 정보 명확

### 구현
1. Phase 1: PostgreSQL 메타데이터 추출
2. `schema_dictionary.json` 생성
3. LLM에게 딕셔너리와 함께 프롬프트 제공
4. LLM이 조회 후 `#{userId}::INTEGER` 적용

### 영향
- `dictionary/builder.py` 필요
- Phase 1 필수 (딕셔너리 없으면 변환 불가)

---

## 결정 004: 대용량 SQL 청킹 전략

**날짜**: 2026-07-27  
**결정자**: 설계팀  
**문서**: `14-large-sql-handling.md`

### 상황
매우 큰 SQL (50,000자 이상)은 LLM 토큰 제한에 걸림

### 선택지
**A) 그냥 실패 처리**
- 50,000자 이상은 에러
- 장점: 간단
- 단점: 변환 불가능한 매퍼 발생

**B) 청킹 (의미 단위 분할)**
- SELECT, FROM, JOIN, WHERE 등으로 분할
- 각 청크 개별 변환
- 재조립

**C) 요약 후 변환**
- LLM에게 SQL 요약 요청
- 요약본 변환
- 원본에 적용

### 선택
✅ **B) 청킹 (의미 단위 분할)**

### 이유
1. **확실성**: 각 청크는 의미 단위 → 정확
2. **유연성**: 복잡도에 따라 분할 크기 조절
3. **검증 가능**: 각 청크 개별 검증

### 전략
1. **50,000자 이하**: 표준 변환
2. **50,000자 이상**: 청킹
   - SELECT 절
   - FROM 절
   - JOIN 절들
   - WHERE 절
   - 동적 SQL 블록들
3. **극단적 케이스**: 수동 검토

### 영향
- `sql_analyzer.py` 필요
- `chunked_conversion()` 함수 필요

---

## 결정 005: 대용량 결과셋 샘플링

**날짜**: 2026-07-27  
**결정자**: 설계팀  
**문서**: `14-large-sql-handling.md`

### 상황
검증 시 SELECT 결과가 수십만 행이면 메모리 부족

### 선택지
**A) 전체 비교**
- 모든 행 비교
- 장점: 100% 정확
- 단점: 메모리 초과, 매우 느림

**B) 샘플링**
- 일부만 비교
- 장점: 빠름, 메모리 안전
- 단점: 100% 정확하지 않음

**C) 행 개수만 비교**
- COUNT(*) 비교
- 장점: 매우 빠름
- 단점: 값 차이 못 잡음

### 선택
✅ **B) 샘플링 (계층적)**

### 이유
1. **실용성**: 100% 비교는 비현실적
2. **통계적 신뢰도**: 5,000개 샘플이면 충분
3. **경계값 포함**: 처음/마지막 포함으로 엣지 케이스 확인

### 전략
**10,000 행 이하**: 전체 비교

**10,000 행 이상**: 샘플링
- 처음 1,000
- 중간 3,000 (균등 분포)
- 마지막 1,000
- 총 5,000 비교

**신뢰도**: Medium (95% 매치율 이상 → Passed)

### 영향
- `DatabaseExecutor.java`에 샘플링 로직
- `comparator.py`에 샘플 비교 로직
- 리포트에 샘플링 여부 표시

---

## 결정 006: DML 트랜잭션 롤백

**날짜**: 2026-07-27  
**결정자**: 설계팀  
**문서**: `10-validation-design.md`

### 상황
검증 시 INSERT/UPDATE/DELETE 실행하면 실제 데이터 변경됨

### 선택지
**A) DML 스킵**
- INSERT/UPDATE/DELETE는 검증 안 함
- 장점: 안전
- 단점: DML 검증 못 함

**B) 트랜잭션 롤백**
- 실행 후 롤백
- 장점: 실행 가능 여부 검증, 데이터 안전
- 단점: 트랜잭션 관리 필요

**C) 별도 테스트 DB**
- 테스트 전용 DB 사용
- 장점: 안전하게 실행 가능
- 단점: 테스트 DB 구축 필요

### 선택
✅ **B) 트랜잭션 롤백**

### 이유
1. **검증 가능**: DML도 실행 가능 여부 확인
2. **데이터 안전**: 롤백으로 원상복구
3. **간단**: 추가 인프라 불필요

### 구현
```java
connection.setAutoCommit(false);
try {
    // INSERT/UPDATE/DELETE 실행
    result = ps.executeUpdate();
} finally {
    connection.rollback();  // 무조건 롤백
    connection.setAutoCommit(true);
}
```

### 영향
- `DatabaseExecutor.java`에 트랜잭션 로직
- 리포트에 "rolled_back: true" 표시

---

## 결정 007: 프로시저 실행 스킵

**날짜**: 2026-07-27  
**결정자**: 설계팀  
**문서**: `10-validation-design.md`

### 상황
프로시저는 내부에서 COMMIT 호출 가능 → 롤백 불가능

### 선택지
**A) 프로시저도 실행**
- CALL procedure()
- 장점: 완전한 검증
- 단점: COMMIT 호출 시 데이터 변경됨

**B) 프로시저 스킵**
- CALL 감지 시 실행하지 않음
- 장점: 안전
- 단점: 프로시저 검증 못 함

### 선택
✅ **B) 프로시저 스킵**

### 이유
1. **안전성**: 데이터 변경 위험 없음
2. **프로시저는 별도 검증**: 애플리케이션 레벨 검증과 분리
3. **명확한 리포팅**: 스킵 사유 명확히 기록

### 구현
```java
if (sql.startsWith("CALL ") || sql.startsWith("EXECUTE ")) {
    return ExecutionResult.skipped(
        "Procedure call skipped - would modify data",
        sql
    );
}
```

### 영향
- 리포트에 "skipped_test_cases" 섹션
- 프로시저는 수동 검토 권장

---

## 결정 008: Rate Limit 준수 방식

**날짜**: 2026-07-27  
**결정자**: 설계팀  
**문서**: `13-error-handling-restart.md`

### 상황
LLM API는 RPM (Requests Per Minute) 제한 있음

### 선택지
**A) 요청 전 대기**
- 매 요청 전 min_interval 대기
- 장점: 단순
- 단점: 불필요한 대기 (느림)

**B) 마지막 요청 시간 기록**
- 마지막 요청 시간 체크
- interval 안 지났으면 대기
- 장점: 불필요한 대기 없음

**C) 토큰 버킷**
- 토큰 버킷 알고리즘
- 장점: 정교한 제어
- 단점: 복잡

### 선택
✅ **B) 마지막 요청 시간 기록**

### 이유
1. **효율적**: 불필요한 대기 없음
2. **간단**: 구현 쉬움
3. **충분**: RPM 제한 준수에 충분

### 구현
```python
elapsed = time.time() - self.last_request_time
if elapsed < self.min_interval:
    time.sleep(self.min_interval - elapsed)

self.last_request_time = time.time()
# API 호출
```

### 영향
- `llm_client.py`에 `_respect_rate_limit()` 메서드

---

## 결정 009: 정규식 사용 금지

**날짜**: 2026-07-27  
**결정자**: 설계팀  
**문서**: `15-coding-guidelines.md`, `CLAUDE.md`

### 상황
SQL/XML 파싱 방법 선택

### 선택지
**A) 정규식**
- re.search(), re.findall()
- 장점: 빠르고 간단
- 단점: 중첩 구조 처리 불가

**B) 파서 (lxml, sqlparse)**
- 전용 파서 사용
- 장점: 정확, 중첩 처리 가능
- 단점: 약간 느림

### 선택
✅ **B) 전용 파서**

### 이유
1. **정확성**: SQL/XML은 중첩 구조 → 정규식으로 불가능
2. **유지보수**: 정규식은 깨지기 쉬움
3. **실전 경험**: 정규식 파싱은 항상 문제 발생

### 예외
**단순 패턴 감지만 허용**:
```python
# ✅ 허용
has_dblink = re.search(r'@[\w\.]+', sql)  # DBLINK 있는지만
is_procedure = sql.startswith('CALL ')

# ❌ 금지
columns = re.findall(r'SELECT\s+(.+?)\s+FROM', sql)  # 파싱
```

### 영향
- CLAUDE.md에 명시 (자동 로드)
- 15-coding-guidelines.md에 상세 설명
- 모든 AI 프롬프트에 "정규식 금지" 명시

---

## 결정 010: sed 절대 금지

**날짜**: 2026-07-27  
**결정자**: 설계팀  
**문서**: `15-coding-guidelines.md`, `CLAUDE.md`

### 상황
파일 처리 방법 선택

### 선택지
**A) sed**
- 빠르고 간편
- 단점: 플랫폼 의존적, 디버깅 어려움

**B) Python**
- 파일 읽어서 처리
- 장점: 플랫폼 독립적, 디버깅 쉬움

### 선택
✅ **B) Python**

### 이유
1. **플랫폼 독립성**: macOS vs Linux sed 차이
2. **디버깅**: Python은 디버깅 쉬움
3. **유지보수**: Python 코드가 명확

### 영향
- 모든 파일 처리는 Python
- CLAUDE.md에 명시

---

## 결정 011: 파일 크기 제한 500 lines

**날짜**: 2026-07-27  
**결정자**: 설계팀  
**문서**: `15-coding-guidelines.md`

### 상황
한 파일에 얼마나 많은 코드를 넣을지

### 선택지
**A) 제한 없음**
- 단점: 유지보수 어려움

**B) 500 lines**
- 장점: 적당한 크기, 관리 쉬움

**C) 1000 lines**
- 단점: 너무 큼

### 선택
✅ **B) 500 lines**

### 이유
1. **가독성**: 500 lines면 한눈에 파악 가능
2. **단일 책임**: 500 넘으면 너무 많은 책임
3. **AI 코딩**: AI가 한 번에 처리하기 좋은 크기

### 영향
- 500 초과 시 즉시 분할
- Code review 시 체크

---

## 결정 012: Python + Java 하이브리드

**날짜**: 2026-07-26  
**결정자**: 설계팀  
**문서**: `10-validation-design.md`

### 상황
검증 모듈 언어 선택

### 선택지
**A) Python만**
- XML 파서로 SQL 추출
- 단점: 부정확

**B) Java만**
- 전체를 Java로
- 단점: 복잡, Python 생태계 활용 못함

**C) Python + Java 하이브리드**
- Python: 오케스트레이션, 비교, 리포팅
- Java: MyBatis SQL 추출, DB 실행
- 통신: JSON (stdin/stdout)

### 선택
✅ **C) 하이브리드**

### 이유
1. **정확성**: MyBatis (Java) 필수
2. **생산성**: Python이 오케스트레이션에 유리
3. **분리**: 각자 잘하는 일만

### 트레이드오프
**장점**:
- 정확성 100%
- Python 생태계 활용

**단점**:
- 복잡도 증가
- 프로세스 간 통신 필요

**결론**: 정확성 > 복잡성

### 영향
- Java 프로젝트 필요 (`java-validator/`)
- Python-Java 브릿지 (`java_bridge.py`)

---

## 의사결정 원칙

### 1. 정확성 > 성능
- 정확하지 않으면 무용지물
- 느려도 정확하면 OK

### 2. 유지보수성 > 간결성
- 코드가 길어도 명확하면 OK
- 짧아도 이해 안 되면 NG

### 3. 안전성 > 기능성
- 데이터 변경 위험은 회피
- DML 롤백, 프로시저 스킵

### 4. 명시적 > 암묵적
- 설정 파일에 명시
- 하드코딩 금지

---

## 문서 버전
- 버전: 1.0
- 작성일: 2026-07-27
- 목적: 의사결정 기록 및 근거
