# 멀티 소스/타겟 구현 착수 가이드 (Claude Code용)

이 문서는 새 소스/타겟 조합(Oracle→MySQL, EPAS→PostgreSQL)을 **이 코드베이스에
추가 구현**하기 위한 상세 지침이다. 이 문서만 보고 바로 구현할 수 있도록 참고 파일,
코드 위치, 패턴, 검증 방법을 명시한다.

> **핵심 원칙**: 이미 완성된 **Oracle→PostgreSQL 구현이 참고 템플릿**이다.
> 기존 파일을 본떠 새 파일을 만들고 팩토리에 등록하는 방식. 새 설계 금지.

---

## 0. 먼저 읽을 것

- `README.md` — 전체 구조/파이프라인
- `15-coding-guidelines.md` — 코딩 규칙 (정규식 SQL 파싱 금지, 파일 상단 변경이력 등)
- `oma.properties` — 설정 키 (SOURCE_DB_TYPE/TARGET_DB_TYPE로 조합 선택)
- 이 문서의 대상 조합 섹션

## 아키텍처 요약 (조합이 갈리는 지점)

파이프라인은 `SOURCE_DB_TYPE`/`TARGET_DB_TYPE`로 조합을 선택한다. 조합에 따라
달라지는 컴포넌트는 **4곳**뿐이고, 나머지(fragmenter/merger/checkpoint/preflight)는
DB 무관하다.

| 컴포넌트 | 파일 | 조합 의존성 |
|----------|------|-------------|
| ① 소스 플러그인 | `oma/plugins/source_*.py` | 소스 DB 연결 |
| ② 타겟 플러그인 | `oma/plugins/target_*.py` | 타겟 DB 연결 + 딕셔너리 스키마 |
| ③ 딕셔너리 빌더 | `oma/dictionary/builder.py` | **타겟** DB 메타데이터 조회 |
| ④ 변환 방언 | `oma/converter/dialect_rules.json` + `prompts.py` | 소스→타겟 SQL 규칙 |
| ⑤ 검증 JDBC URL | `oma/validation/java_bridge.py` | 소스/타겟 JDBC URL |

플러그인 등록: `oma/plugins/factory.py` 의 `_SOURCE_PLUGINS` / `_TARGET_PLUGINS` dict.

---

# 조합 A: Oracle → MySQL

기존 Oracle 소스는 그대로 재사용. **타겟(MySQL)** 쪽만 새로 만든다.

## A-1. 타겟 플러그인 `oma/plugins/target_mysql.py` (신규)

**참고 템플릿**: `oma/plugins/target_postgres.py` (그대로 본뜨기)

- 클래스 `MySQLTarget(TargetDB)` — `oma/plugins/base.py`의 `TargetDB` 상속
- 구현할 메서드 (target_postgres.py와 동일 시그니처):
  - `connect()`: `import mysql.connector` 또는 `pymysql`로 연결.
    - requirements.txt에 mysql 드라이버 추가 필요 (`mysql-connector-python`)
    - URL 아닌 host/port/user/password/database 파라미터로 연결
  - `get_schema_name()`: MySQL은 schema=database 개념. `credentials["database"]` 반환
  - `get_sql_dialect()`: `"mysql"` 반환
- 예외는 `DatabaseError`로 래핑 (target_postgres.py와 동일)

## A-2. 팩토리 등록 `oma/plugins/factory.py`

```python
from oma.plugins.target_mysql import MySQLTarget   # import 추가
_TARGET_PLUGINS = {
    "postgres": PostgresTarget,
    "mysql": MySQLTarget,        # ← 추가
}
```
- `create_target`의 `local_keys` 매핑은 postgres와 동일(host/port/database/schema/
  username/password) — 수정 불필요

## A-3. 딕셔너리 빌더 MySQL 지원 `oma/dictionary/builder.py`

**현재**: PostgreSQL `information_schema.columns` 전용 + psycopg2 하드코딩.

MySQL도 `information_schema.columns`가 있으나 차이점:
- MySQL은 `table_schema`가 DB명. 쿼리의 스키마 필터를 database명으로.
- 컬럼: `character_maximum_length`, `numeric_precision/scale`, `data_type` 동일하게 있음
- **권장 구현**: builder를 dialect별로 분기하거나, 타겟 플러그인이 커넥션을 주는
  현재 구조(`DictionaryBuilder(config, target=plugin)`)를 활용해 SQL만 방언 분기.
  - `extract_metadata()`의 쿼리를 target.get_sql_dialect()로 분기
  - 식별자 인용: PG는 `psycopg2.sql.Identifier`, MySQL은 백틱(`) — 방언 처리 필요
- 샘플 조회 `collect_samples()`의 `SELECT * FROM {schema}.{table} LIMIT 1`은
  MySQL도 유사(백틱 인용만 차이)

## A-4. 변환 방언 `oma/converter/dialect_rules.json`

`oracle_to_mysql` 키가 이미 STUB로 존재. 실검증하며 채울 것:
- `cast_syntax`: MySQL은 `CAST(x AS SIGNED)`/`CAST(x AS DECIMAL)`/`CAST(x AS DATETIME)`
  (PG의 `::TYPE` 문법 없음)
- MySQL 미지원: 시퀀스, 일부 분석함수, `RETURNING` 등 → notes에 명시
- prompts.py는 이미 `build_system_prompt(source, target)`로 방언 주입하므로 수정 불필요

## A-5. 딕셔너리 cast_hint MySQL 문법 `oma/dictionary/builder.py`

`_build_cast_hint()`가 PG 문법(`::INTEGER`) 하드코딩. MySQL은 `CAST(.. AS SIGNED)`.
- dialect 인자를 받아 cast_syntax를 방언별로 생성하도록 확장
- 또는 cast_hint에 타입만 담고, 실제 캐스팅 문법은 LLM(dialect_rules)이 판단하게 위임

## A-6. 검증 JDBC URL `oma/validation/java_bridge.py`

`_target_db_config()`가 PostgreSQL URL 하드코딩:
```python
url = f"jdbc:postgresql://{host}:{port}/{database}"
```
→ 타겟 타입 분기 추가:
```python
# jdbc:mysql://host:port/database, driver=com.mysql.cj.jdbc.Driver
```
- `_MYSQL_DRIVER = "com.mysql.cj.jdbc.Driver"` 상수는 이미 있음
- 브리지가 타겟 dialect를 알도록 생성 시 target_type 주입 필요

## A-7. Java Validator
- pom.xml에 `mysql-connector-j` 이미 있음 → 재빌드만
- MySQL은 `::` 캐스팅 미지원이므로 변환된 SQL이 MySQL 문법이어야 실행됨(A-4 의존)

---

# 조합 B: EPAS(EDB) → PostgreSQL

타겟 PostgreSQL은 그대로 재사용. **소스(EPAS)** 쪽만 새로 만든다.
EPAS는 Oracle 호환 모드 DB지만 접속은 PostgreSQL 프로토콜(psycopg2)을 쓴다.

## B-1. 소스 플러그인 `oma/plugins/source_epas.py` (신규)

**참고 템플릿**: `oma/plugins/source_oracle.py` + `oma/plugins/target_postgres.py`
(연결은 postgres 방식, 역할은 source)

- 클래스 `EpasSource(SourceDB)` — `base.py`의 `SourceDB` 상속
- `connect()`: **psycopg2로 연결** (EPAS는 PG 와이어 프로토콜).
  - Oracle의 service_name→SID 폴백 로직 불필요. host/port/dbname/user/password
- `get_schema_name()`: `credentials["target_schema"]` 또는 username 기반
- `get_sql_dialect()`: `"epas"` 반환

## B-2. 팩토리 등록 `oma/plugins/factory.py`

```python
from oma.plugins.source_epas import EpasSource
_SOURCE_PLUGINS = {
    "oracle": OracleSource,
    "epas": EpasSource,          # ← 추가
}
```
- `create_source`의 `local_keys` 매핑 확인: EPAS는 sid 대신 database 사용할 수 있으니
  local_keys 분기 또는 시크릿 키 확인 필요

## B-3. 딕셔너리
- 딕셔너리는 **타겟(PostgreSQL)** 기준이라 기존 그대로 사용. **수정 불필요.**
  (EPAS는 소스라 메타데이터 추출 대상이 아님)

## B-4. 변환 방언 `dialect_rules.json`
- `epas_to_postgres` STUB를 실검증하며 채움. EPAS는 상당수 문법이 이미 PG 호환이라
  변환량이 적을 것 (notes에 "EPAS 전용 패키지/확장 사용 시 warning")

## B-5. 검증 JDBC URL `oma/validation/java_bridge.py`
- `_source_db_config()`가 Oracle URL 하드코딩(`jdbc:oracle:thin:@//...`).
  → 소스 타입 분기: EPAS는 `jdbc:postgresql://host:port/database` +
    driver `org.postgresql.Driver` (EDB 전용 드라이버 있으면 그것)
- 브리지가 소스 dialect를 알도록 생성 시 source_type 주입 필요

---

# 공통 검증 절차 (PoC 방식 그대로)

새 조합 구현 후, `19-multisource...` 아닌 실제 검증은 PoC 방식으로:

1. **대표 매퍼 5개 선별** (단순조회/동적SQL/함수/DML/복합) → PoC 소스 디렉토리 복사
2. **PoC용 properties** 작성 (`SOURCE_DB_TYPE`/`TARGET_DB_TYPE` 해당 조합, 시크릿)
3. 파이프라인 실행:
   ```
   python3.11 scripts/run_oma.py --config <poc>.properties --preflight
   python3.11 scripts/run_oma.py --config <poc>.properties --phase dictionary
   python3.11 scripts/run_oma.py --config <poc>.properties --phase copy,fragment,convert,merge
   python3.11 scripts/run_oma.py --config <poc>.properties --phase validate
   ```
4. 변환 결과(converted/*.xml, *.report.json)와 검증 리포트 확인
5. 실패 분류: 변환 결함 vs TC데이터 vs 인프라 (PoC-REPORT.md 형식 참고)

# 검증 체크포인트 (조합별 "됐다"의 기준)
- [ ] preflight가 소스 매퍼 스캔 성공 (OGNL/${}/별칭 리포트 생성)
- [ ] Phase1 딕셔너리: 타겟 스키마에서 컬럼 추출 성공 (개수 확인)
- [ ] Phase4 변환: 조각 status=success, 방언 함수변환 정확
      (Oracle→MySQL: NVL→IFNULL, ::TYPE 없음 / EPAS→PG: 최소 변환)
- [ ] Phase5 병합: 원본 구조 보존
- [ ] Phase6 검증: 소스/타겟 실행 결과 비교 (서비스 계정으로)

# 테스트
- 각 새 플러그인은 `tests/unit/test_plugins.py` 패턴으로 mock 단위테스트 추가
- 전체 `python3.11 -m pytest tests -q` 통과 유지

---

## 문서 버전
- 작성일: 2026-07-28
- 목적: Oracle→MySQL, EPAS→PostgreSQL 구현 착수 (Claude Code)
- 현재 검증 완료 조합: Oracle→PostgreSQL (이것이 참고 템플릿)
