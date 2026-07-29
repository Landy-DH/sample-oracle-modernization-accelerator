# OMA 개발 작업 로그

## 규칙
- **작업 전**: 이 파일을 처음부터 끝까지 읽고 중복 작업 방지
- **작업 후**: 반드시 로그 작성
- **형식**: 최신 작업이 맨 위

---

## 2026-07-28 | 오류유형 기반 반복 수정 루프 설계 (design/20) + 실패 분석 리포트

### 배경
- thepop 재변환·검증 결과 507건 중 통과 299 / 실패 208.
- 실패를 유형별로 분류하니 실제 변환결함(재변환 대상)은 최대 56건, 나머지 152건은
  테스트데이터/TC생성/오탐(source·target 동일 에러) 성격.
- 사용자 아이디어: 변환/검증 후 자동으로 오류유형을 뽑고 번호를 매겨, 사용자가
  "N번 유형 수정하자"라고 하면 LLM 대화형으로 조각을 고치고 재머지→재검증→재분석을
  에러 0까지 반복하는 프로세스를 정규화하자.

### 작업 내용
- `design/20-iterative-repair-loop.md` (신규): 반복 수정 루프 전체 설계.
  - 루프: convert→merge→validate→**analyze(유형분류+번호)**→(유형선택)→**repair
    (조각 파일 수정)**→merge→validate→analyze 수렴.
  - `repair-plan.json` 계약(유형 번호 + 영향 조각 `frag_id` 리스트 + 대표 에러).
  - repair 전용 프롬프트(원본+현재변환+검증에러 3입력, 최소 수정, 함수매핑 하드코딩
    금지·힌트는 데이터로).
  - 오탐(F) 자동 격리(source==target 에러), 정규 도구 목록
    (`analyze_failures.py`/`repair_type.py`/기존 `reset_failed_fragments.py`).
- README 설계문서 표에 20번 등록.
- 실패 분석 산출물 생성: `reports/failure-analysis.json`, `failure-analysis.csv`,
  `failure-report.md` (208건 유형/그룹/매퍼 집계).

### 다음
- `analyze_failures.py`/`repair_type.py` 구현(설계 20 기준).
- 우선 유형 A(미변환 함수 21건: to_char 1인자/nvl/to_date 1인자)부터 repair 착수 예정.

---

## 2026-07-28 | 조각 파일명 충돌 수정 + Phase4 병렬화 + 전체 재실행 (thepop)

### 배경
- validate 0/507 전멸. 원인: 조각 식별자가 `{mapper}__{sql_id}`라 statement_type이
  빠져, `<resultMap>`과 `<select>`가 같은 id를 공유하는 MyBatis 표준 패턴에서
  두 조각이 같은 파일명으로 충돌(MainOrderMapper) → 병합 시 resultMap 소실 →
  MyBatis "Could not find result map" 연쇄 실패.
- 재변환이 필요한 김에 dead config였던 MAX_WORKERS를 실제 병렬화에 연결.

### 작업 내용
- `orchestrator.py`: `_fragment_id(mapper, sql_id, statement_type)` 헬퍼 도입,
  저장/체크포인트키/원본로드/변환로드 4곳 통일. phase_conversion을
  ThreadPoolExecutor(max_workers=MAX_WORKERS)로 병렬화(LLM 호출만 워커, 체크포인트/
  저장/summary는 as_completed로 메인스레드 순차).
- `llm_client.py`: `_rate_lock`으로 `_respect_rate_limit` thread-safe화(RPM 직렬).
- `tests/integration/test_workflow.py`: 파일명 단언 갱신 + resultMap/select id공유
  회귀 테스트 + 병렬 변환 테스트 추가. 전체 227 passed.

### 결과 (thepop)
- fragment 307조각(충돌 해소로 306→307), convert 307/307 실패0(7워커 병렬),
  merge 36매퍼. MainOrderMapper resultMap/select 각 1개 보존 확인.
- validate: **0/507 → 299/507(59%)**.

---

## 2026-07-28 | 실패 조각 선택 재변환 유틸 + 가이드 반영 (thepop)

### 배경
- thepop 전체 변환 결과 conversion-summary: success 302 / failed 3 / partial 1.
- failed 3건은 예외가 아니라 LLM이 `conversion_status=failed`로 반환한 케이스
  (error 없음). 전체 재실행 없이 실패 3개만 재변환 필요.

### 작업 내용
- `scripts/reset_failed_fragments.py` (신규): Phase4 실패/부분 조각만 골라
  체크포인트를 되돌려(`completed_fragments`에서 제거 + phase4~7 pending 복귀)
  다음 `--phase convert`에서 해당 조각만 재변환되게 함.
  - report.status 자동 식별(`--status failed partial`) 또는 `--fragment` 명시 지정
  - `--dry-run` 지원, 체크포인트는 `.bak-<run_id>`로 자동 백업
  - report.json은 순수 JSON 파싱(정규식 SQL/XML 파싱 금지 규칙 준수)
- `design/13-error-handling-restart.md` §2.4 신규: "실패 조각만 선택 재변환" 절차
  문서화 + false negative(오탐) 주의사항 기재.

### 재변환 결과 (thepop, --status failed)
- `NoticeMapper__retrieveGscmNoticeList`: failed → **success** (NVL/(+)/TO_CHAR 정상 변환)
- `StoreSearchGscmMapper__retrieveStrSrchRsltList`: failed → **success**
- `StoreSearchGscmMapper__retrieveStoreInfoDetail`: still failed = **오탐**.
  원본이 이미 PG 호환(regexp_replace 'g'/LEFT JOIN/COALESCE)이라 LLM이
  원본 그대로 반환 + failed 표기. converted==original, 실제 결함 아님 → validate에서 확인.
- phase4_conversion/phase5_merge 재완료(36개 매퍼 병합).

---

## 2026-07-28 | EPAS→PostgreSQL 소스 지원 구현 (19-multisource-target-guide.md 조합 B)

### 작업 내용
- EPAS(EDB Postgres) 소스 플러그인 신규 구현 및 파이프라인 조합 B(EPAS→PG) 지원
- 참고 템플릿: `source_oracle.py`(소스 역할) + `target_postgres.py`(psycopg2 연결)

### 구현 내용
- `oma/plugins/source_epas.py` (신규): `EpasSource(SourceDB)`
  - `connect()`: psycopg2 연결. Oracle의 service_name→SID 폴백 **없음**(PG 와이어 프로토콜)
  - `get_schema_name()`: target_schema > schema > username (Oracle과 달리 대문자화 안 함)
  - `get_sql_dialect()`: `"epas"`
- `oma/plugins/factory.py`: `_SOURCE_PLUGINS`에 `"epas": EpasSource` 등록.
  create_source의 local_keys가 epas면 SOURCE_DATABASE→`database` 키로 매핑(oracle은 `sid`)
- `oma/plugins/__init__.py`: EpasSource export
- `oma/validation/java_bridge.py`: `source_type` 주입. `_source_db_config()`가 epas일 때
  `jdbc:postgresql://host:port/database` + `org.postgresql.Driver`로 분기.
  from_config가 SOURCE_DB_TYPE 전달. 기본값 oracle(하위호환)
- `oma/converter/dialect_rules.json`: `epas_to_postgres` STUB 해제 → 최소변환 원칙/함수 정규화 명시

### 주의사항
- 딕셔너리 빌더는 **타겟(PostgreSQL)** 기준이라 수정 불필요 (가이드 B-3)
- EPAS 시크릿(oma-source-admin/service)은 `database` 키 사용. connect가 database→sid 폴백 흡수
- 테스트/실행은 반드시 `python3.11` 사용 (기본 python3=3.9, design/18 규칙). pytest는 3.11 user-site에 설치

### 파일 위치
- `oma/plugins/source_epas.py` (신규, ~130 lines)
- `oma/plugins/factory.py`, `oma/plugins/__init__.py`, `oma/validation/java_bridge.py` (수정)
- `oma/converter/dialect_rules.json` (수정)
- `tests/unit/test_plugins.py`, `tests/unit/test_java_bridge.py` (테스트 추가)

### 테스트
- [x] 단위 테스트: EpasSource 연결/스키마/방언/폴백없음, factory epas 선택, java_bridge epas URL
- [ ] PoC 대표 매퍼 5개 검증 (진행)

---

## 2026-07-28 | 배포 준비: 익명화 + preflight 가이드 + 멀티조합 점검

### 1) 프로젝트 고유 흔적 완전 제거 (익명화)
- daiso/com.daiso→acme/com.acme, wmson/WMSON→appdb/APPDB,
  com.kns→com.example, GRIDPAGING→PAGING_ROWNUM, WcsPropertyUtil→
  ContextPropertyUtil, CmFunction→CommonFunction (코드/설정/테스트/문서 99파일)
- APPLICATION_NAME=wms→oma, SOURCE_WORKSPACE→placeholder(/path/to/source/application)
- 원본 흔적(daiso/wmson/com.kns) 0건 확인. (sample-app은 익명화용 범용명이라 유지)

### 2) 배포용 정리
- 삭제: projects/(산출물 전체), oma-poc*.properties, *.old, __pycache__,
  .pytest_cache, java-validator/target
- 유지: 코드(oma/java-validator src/scripts/tests), 문서(*.md), oma.properties,
  requirements.txt, pytest.ini, templates

### 3) Pre-flight 가이드 생성 기능 (요청 2번)
- oma/preflight/guide.py 신설: PreflightReport → 조치 가이드 + 설정 스텁
  - build_config_stubs: variables/ognl_methods/type_aliases 스텁(값 채우기용)
  - build_markdown_guide: 이슈별 "어디에 무엇을 반영할지" Markdown 안내
- orchestrator.preflight()가 preflight-report.json + preflight-config-stubs.json
  + preflight-guide.md 3종 생성
- 실 검증: OGNL 5종/${} 11종/별칭 55종 각각 조치방법 안내 생성 확인
- test_preflight_guide.py (5)

### 4) 멀티 소스/타겟 투입 가능성 점검 (요청 3번)
- 현재 실전 가능: Oracle→PostgreSQL 만 (PoC 검증)
- Oracle→MySQL, EPAS→PostgreSQL: 구조(팩토리/dialect슬롯/프롬프트)는 열림,
  구현 미완(플러그인/딕셔너리/JDBC URL 분기/dialect 실검증 필요)
- TODO에 조합별 필요작업 체크리스트 기록

### 테스트
- [x] 전체 214 passed

---

## 2026-07-28 | PoC2 + 타임아웃 근본버그 2건 수정 (config화)

### PoC2 (다른 매퍼 5개: 조회 위주 - realTimeInvn/center/invnMoveHistory/ilbhs/ctglevel)
- 16조각 실제 LLM 변환 성공, 병합 5개
- 검증 완주(1분48초): 통과 0/29. 매퍼 특성상(대량페이징/다중조인/날짜조건)
  더미 파라미터로 정상실행 어려움. 실패: ORA-00904(미존재컬럼)7, resultMap로드7,
  ORA-00920(연산자)5, 쿼리타임아웃5, 결과차이3, ORA-01861(날짜)2
- 파이프라인 자체는 정상. 검증도구가 실제 결과차이(column/value_mismatch)도 검출

### 버그1: boto3 read_timeout 미설정 → 대형 조각 변환 무한 매달림
- 증상: 15KB 집계쿼리 조각 변환이 수분+ (timeout). 단순 호출은 8.9초 정상
- 원인: bedrock 클라이언트에 read_timeout 미설정(기본 60초). 대형 조각 응답이
  60초 넘으면 botocore가 끊고, 우리 재시도(3회)가 각각 재시도 → 수분 매달림
- 수정: _get_client에 botocore Config(read_timeout=LLM_TIMEOUT_SECONDS,
  connect_timeout=30, retries max_attempts=0). LLM_TIMEOUT_SECONDS 120→300,
  LLM_MAX_OUTPUT_TOKENS=16000 신설
- 효과: 15KB 조각 80초에 완료, PoC2 16조각 4분54초 완주

### 버그2: JDBC 쿼리 타임아웃 미설정 → 대량조회가 검증 전체 막음
- 증상: selectInvnMoveHistory(PAGING_ROWNUM 대량조회)가 필터없는 더미파라미터로
  25초+ 스캔. 5개×62초(소스30+타겟30) → 프로세스 300초 초과
- 수정: DatabaseExecutor.setQueryTimeout 추가. config화:
  VALIDATION_QUERY_TIMEOUT=10, VALIDATION_PROCESS_TIMEOUT=600
  (java_bridge가 요청 JSON에 queryTimeoutSeconds 전달 → Java Request→Executor)
- 효과: 대량조회 10초에 취소(ORA-01013/PG canceling)되고 검증 완주(1분48초)

### 설계 개선
- 타임아웃 3종을 oma.properties에서 관리 (LLM_TIMEOUT_SECONDS,
  VALIDATION_QUERY_TIMEOUT, VALIDATION_PROCESS_TIMEOUT) - 재빌드 없이 조정
- VALIDATION_PROCESS_TIMEOUT 기본 -1(무제한)로 변경: 실전은 수천 SQL이라 전체
  시간 예측 불가 → 개별 쿼리 타임아웃으로 제어, 전체 상한은 옵트인(양수 설정 시).
  java_bridge: timeout<=0 이면 subprocess timeout=None(무제한)

### 테스트
- [x] 전체 209 passed, JAR 재빌드 OK

---

## 2026-07-28 | 프롬프트 재설계 + TC param_mappings 연결 (멀티 소스/타겟)

### 배경
- PoC에서 TC가 "SAMPLE" 더미값만 써서 검증 대량 실패(NOT NULL/길이 위반).
  원인: LLM이 파악한 param→column 매핑이 TC 생성으로 연결 안 됨(프롬프트 미비).

### 1) 프롬프트 재설계 (멀티 소스/타겟 구조)
- oma/converter/dialect_rules.json: oracle→postgres/mysql, epas→postgres 슬롯.
  oracle→pg만 실채움, 나머지는 STUB(실데이터 검증 전). Opus 신뢰로 함수매핑
  나열 대신 최소 힌트만.
- prompts.py 재작성:
  - build_system_prompt(source,target): 방언 힌트 주입, 지침은 시스템 프롬프트로
  - 함수변환 디테일/퓨샷 최소화(모델 판단), 형변환+param_mappings만 상세
  - INSERT 컬럼↔VALUES 위치매핑 가이드 (변수명≠컬럼명, foreach 가변 대응)
  - 출력에 param_mappings[{param,column,data_type,sample_value,cast_applied}] 추가

### 2) Converter/Generator 연결
- Converter: source_type/target_type 주입, LLM param_mappings → TC 생성기로 전달
  (_extract_param_columns). ConversionResult/report에 param_mappings 보존.
- TestCaseGenerator:
  - 정적(필수) 파라미터도 모든 시나리오에 채움(_static_params) - INSERT VALUES 등
  - char_max_length로 문자열 샘플값 길이 절단(_fit_length) - char(1)→"S"

### 3) 실 검증 효과 (insertMaster)
- param_mappings 9종 전부 매핑, surkey→interface_log.inserturkey(위치매핑 성공)
- 타입 정확: ifid=numeric→1, iftype=char(1)→"S", varchar→"SAMPLE"
- 검증 통과: 재변환 후 11/45. 길이초과(ORA-12899) 20건 완전 해소

### 4) 방침 결정 (사용자)
- <selectKey>/useGeneratedKeys로 DB가 채우는 keyProperty를 TC에서 제외하는
  로직은 구현 안 함. 이런 케이스는 소수인데 generator 복잡도/버그위험 큼.
  → 검증 리포트의 오류를 보고 사람이 판단·수정 (도구는 변환·검증·리포트,
    최종 판단은 사람). 프로젝트 철학과 일치.

### 테스트
- [x] 전체 209 passed

---

## 2026-07-27 | Week 4 Day 19: PoC 테스트 (실제 LLM 변환 e2e)

### 작업 내용
- 대표 매퍼 5개 선별해 실제 Bedrock 변환 포함 전체 파이프라인 e2e
- 검증 계정 분리(admin/service) 버그 수정, TC namespace 버그 수정

### PoC 구성
- projects/wms-poc/source/ 에 진짜 원본 5개 복사 (OGNL/PAGING_ROWNUM/camelMap 포함)
  - 단순조회+Oracle함수: wms-master-itemmanager
  - 동적SQL: wms-master-owner
  - 복합(동적+함수+DML): LoggingMapper
  - 순수DML: wms-inbound-order-update
  - 리포트성: wms-report-invenToryHistory
- oma-poc.properties (딕셔너리는 wms 것 재사용)

### 결과
- 변환: 17조각 100% success (실제 Bedrock, 약 3.5분)
  NVL→COALESCE, TO_CLOB→CAST(AS TEXT), SYSDATE→CURRENT_TIMESTAMP, ::NUMERIC
- 병합: 5개 매퍼 재조립 성공
- 검증: 통과 10/45 (22.2%). 실패 35 = TC데이터 제약미충족(17)+매퍼로드(14)+
  순수변환/결과차이(2)+기타. varchar(1) 길이초과 등 실제 스키마차이 검출
- 보고서: projects/wms-poc/reports/POC-REPORT.md

### 버그 수정 2건
1. **TC namespace 누락**: TestCaseGenerator가 namespace를 안 채워
   Java에서 "Mapped Statements does not contain" (mapper.sqlId로 조회, 실제는
   namespace.sqlId). → TestCase에 namespace 필드 추가, generate/to_dict/converter
   연결. (테스트 21 통과)
2. **검증 계정 오류**: 검증을 admin(system)으로 실행 → APPDB 테이블 ORA-00942.
   딕셔너리=admin, 검증=service 원칙에 맞게 properties에 SOURCE_SERVICE_SECRET/
   TARGET_SERVICE_SECRET 분리, run_oma._build_validation이 service 사용.
   → 서비스계정(appdb)으로 재실행하니 통과 0→10

### 테스트
- [x] 전체 209 passed

---

## 2026-07-27 | Week 4 Day 18: Main Script (run_oma.py CLI)

### 작업 내용
- scripts/run_oma.py - CLI 진입점

### 구현 내용
- argparse: --config / --phase / --preflight / --retry-failed
- parse_phases: all 또는 콤마구분 별칭(dictionary/copy/fragment/convert/merge/
  validate/copy_target) → 정식 Phase 목록
- build_orchestrator: 실행할 Phase에 필요한 협력자만 지연 조립
  (dictionary/validate→target 플러그인, convert→Converter+LLM, validate→검증)
  → 불필요한 DB/Bedrock 연결 회피
- --preflight: 사전 점검만 실행. --retry-failed: 실패 조각 목록 조회
- setup_logger로 파일/콘솔 로깅

### 실 CLI 검증
- python3.11 scripts/run_oma.py --preflight → 매퍼197/OGNL5/${}11/별칭55 리포트
- python3.11 scripts/run_oma.py --phase copy,fragment
  → 복사197 + 치환(1360+1569) + 분할3048 실제 동작

### 테스트
- tests/unit/test_run_oma.py (10, importlib로 스크립트 로드)
- [x] 전체 209 passed

---

## 2026-07-27 | Week 4 Day 16-17: Workflow Orchestrator

### 작업 내용
- oma/workflow/orchestrator.py - 전체 파이프라인(preflight + Phase 1-7) 통합
- oma/preprocess/special_variables.py - 특수변수 치환 정식 모듈화(scripts에서 이관)

### 구현 내용
- **WorkflowOrchestrator**: run(phases) + Phase별 메서드, 체크포인트 연동
  - preflight(): 사전점검 스캔 → preflight-report.json + config-template.json
  - phase_dictionary: DictionaryBuilder(target 플러그인)
  - phase_copy_mappers: 소스→original 복사 + SpecialVariableSubstitutor 치환
  - phase_fragment: split_workspace + mapping.json + 조각 XML 저장
  - phase_conversion: Converter로 변환, 체크포인트로 완료조각 스킵(재시작),
    converted/*.xml + *.report.json + testcases/*.json + conversion-summary.json
  - phase_merge: mapping.json 기반 조각→원본구조 재조립
  - phase_validation: ValidationOrchestrator 위임(미주입 시 스킵)
  - phase_copy_target: merged→TARGET_WORKSPACE 복사
- 협력자(target/converter/validation) 주입 가능
- **SpecialVariableSubstitutor**: 변수/OGNL 치환, XML 이스케이프, --no-ognl 대응

### 버그 수정
- phase_fragment: splitter.source_workspace를 original_dir로 맞춤
  (안 그러면 source_file이 절대경로가 되어 merge에서 경로 불일치)

### 실 e2e 검증 (sample-app, LLM은 fake)
- preflight: 매퍼197, OGNL 5종, ${} 11종, 미지별칭 55종
- Phase2: 복사197 + 치환(변수1360+OGNL1569)
- Phase3: 3048 조각
- Phase4: converted 3048 + report.json 3048 + TC 3048, summary success 3048
- Phase5: 병합 197
- Phase7: 타겟복사 197

### 안전 이슈 수정
- Phase7이 TARGET_WORKSPACE(/workspace/target = 기존 acme 앱 소스)에 덮어씀 발견
  → target/src(방금 생성분 197개, 20분내 수정 확인)만 제거, 기존 acme-* 보존
  → TARGET_WORKSPACE=${PROJECT_WORK_DIR}/target-output 로 변경(안전한 전용 경로)

### 테스트
- tests/integration/test_workflow.py (6, fake converter)
- [x] 전체 199 passed

---

## 2026-07-27 | Week 3 Day 15: Validation Orchestrator (Week 3 완료)

### 작업 내용
- oma/validation/orchestrator.py - 검증 전체 플로우 제어

### 구현 내용
- **ValidationOrchestrator.validate_all(testcase_dir)** → 요약 dict
  1) load_test_cases: TC JSON 로드 (개별 실패 건너뜀)
  2) bridge.validate_batch: Java 검증 (배치)
  3) comparator.compare: 결과 비교
  4) reporter.generate_all_reports: 리포트 생성
  - 빈 디렉토리면 빈 리포트, 없는 디렉토리는 ValidationError
- from_config: bridge/comparator/reporter를 Config+자격증명으로 구성
- 의존성 주입 구조 (bridge/comparator/reporter)

### resultMap 44건 이슈 처리
- acme 특유 케이스로 판단, 딥다이브 보류 (사용자 결정)
- 사전 점검 스캐너가 검출하는 것으로 충분. 개별 매퍼 로드 실패는 건너뛰고
  나머지로 부분 검증 진행 (LenientConfiguration의 loadMapper가 이미 건너뜀)

### 테스트
- tests/integration/test_validation.py (5, bridge mock)
- [x] 전체 193 passed

### Week 3 완료 요약
- Day 11-12 Java Validator / Day 13 Bridge / Day 14 Comparator&Reporter /
  Day 15 Orchestrator. + Pre-flight 스캐너(계획 외) 추가.
- 검증 파이프라인 완성: TC → Java(BoundSql 추출·실행) → 비교 → 리포트

---

## 2026-07-27 | Pre-flight 스캐너 + OGNL 치환 + 타입별칭 폴백

### 1) Pre-flight 스캐너 (oma/preflight/scanner.py)
- 목적: "돌려보기 전엔 모르는" 이슈(OGNL/${}변수/미지별칭/파싱오류/프로시저)를
  변환 전에 스캔해 리포트 → 사용자가 설정 채우게 함
- MapperScanner.scan_dir → PreflightReport (5개 카테고리), build_config_template
- lxml 파싱 + str 토큰 스캔(정규식X). 파싱 실패해도 토큰은 텍스트로 검출
- 실 sample-app 스캔 결과:
  - OGNL: isNotEmpty 1545 / isEmpty 19 / CommonFunction.notEmpty 5 / ContextPropertyUtil 10
  - ${}: PAGING_ROWNUM 52 + sortord/orderby1~3/sort1~3 등 동적 정렬 변수 다수(신규 발견)
  - 미지 별칭: camelMap 999 + xxxVO/xxxDTO 수십 종(신규 발견 — Java 로드 실패 원인)
  - 파싱오류 0, 프로시저 13개 매퍼
- 테스트 9개

### 2) OGNL 치환 (substitute_special_variables.py에 통합)
- special_variables.json에 ognl_methods 추가:
  StringUtil@isNotEmpty/CommonFunction@notEmpty → " != null",
  StringUtil@isEmpty → " == null"
- @Class@method(arg) → (arg != null) 로 str 치환. --no-ognl 플래그(실전용)
- 실전 방침: 고객 OGNL 클래스를 classpath 등록. 테스트는 치환으로 우회
- 실 치환: 특수변수 1360 + OGNL 1569건, XML 197/197 유효

### 3) 타입 별칭 폴백 (LenientConfiguration.java)
- MyBatis Configuration의 TypeAliasRegistry 오버라이드: 미지 별칭 →
  resolveAlias 실패 시 HashMap 폴백 (검증은 resultType 클래스 불필요)
- camelMap 매퍼 로드+SQL추출 성공 확인 (이전 실패 → 해결)
- 잔여: 44개 매퍼 여전히 로드 실패 (resultMap이 VO 생성자 요구 34, HashMap
  부적합 8, 중복id 2) → 백로그. resultMap 무시 전략 등 추가 필요

### 테스트
- Python 188 passed, Java 재빌드 성공

---

## 2026-07-27 | 비교 완전일치 전환 + 특수변수 선치환 + OGNL 이슈 발견

### 1) Comparator: tolerance 제거 → 완전 일치
- 요구사항: 소스/타겟 결과는 완벽히 일치해야 함 (근사 허용 불가)
- _values_equal: 숫자 tolerance 제거. int/float 정확 동치(5==5.0)만 허용,
  값 다르면 불일치. 문자열 strip 제거 → CHAR 패딩("Y" vs "Y ")도 불일치로 판정
- 생성자에서 tolerance 파라미터 제거
- test_comparator: tolerance 테스트 → 완전일치 테스트로 교체 (15개)

### 2) 특수 바인드 변수 선치환 (PAGING_ROWNUM 2종 + sysdate)
- 배경: 프레임워크가 런타임 주입하는 변수라 TC 파라미터로 바인딩 불가
  - #{PAGING_ROWNUM_TOP/BOTTOM} (#{}·${} 양형태), #{sysdate}(989),
    #{sysdate,mode=IN,jdbcType=VARCHAR}(4) → 대소문자·옵션형태 포함
- 방식: source→projects/wms/mappers/original 복사 후, 복사본에서만 치환
  (원본 source는 불변 확인). oracle 값으로 치환 → 이후 LLM이 postgres로 변환
- 스크립트: scripts/substitute_special_variables.py + special_variables.json
  - str 스캔(정규식X), 토큰 루트명 대소문자무시 매칭, 옵션형태 흡수
  - 안전장치: /source/ 경로에서 실행 금지
- **버그 발견·수정**: PAGING_ROWNUM_BOTTOM 값의 "ROWNUM <= 1000"의 < 가 XML을
  깨뜨림(98/197 파싱 실패) → 치환값을 XML 이스케이프(&,<,>)하도록 수정.
  재검증: 197/197 파싱 성공, 파싱 시 텍스트는 <로 복원, splitter 3048조각 통과
- 정식 반영은 오케스트레이터(Phase2 복사) 완성 후. 지금은 검증용 선치환

### 3) OGNL 정적 메서드 이슈 (미해결, 백로그)
- 실측: test= 조건 1798개 중 1261개(70%)가 @com.example...StringUtil@isNotEmpty(...)
- 문제: Java Validator가 getBoundSql 시 이 클래스가 classpath에 없으면 OGNL
  평가 실패 → <if> 분기 안 됨. TC 생성기도 조건 의미 모름
- 대응 방안 미정 (실 프로젝트 JAR classpath 추가 vs stub 구현) → 백로그 기록,
  실 검증 직전 결정 필요

### 테스트
- [x] 전체 179 passed

---

## 2026-07-27 | Week 3 Day 14: Comparator & Reporter

### 작업 내용
- oma/validation/comparator.py - 소스/타겟 실행 결과 비교
- oma/validation/reporter.py - 검증 리포트 생성

### 구현 내용
- **ResultComparator.compare(validation_result)** → Comparison
  - 우선순위: 실행성공/스킵 → 행수 → 컬럼집합(대소문자무시) → 값(행별/컬럼별)
  - 숫자 tolerance(기본 0.001), CHAR 패딩(양끝 공백) 무시, NULL 처리
  - 실패유형: execution_error/row_count_mismatch/column_mismatch/value_mismatch
  - 값 불일치 상세 최대 20건, 대용량 샘플 결과 note
- **ValidationReporter.generate_all_reports(comparisons)** → 요약 dict
  - 콘솔 요약 + validation-summary.json + validation-details.json +
    validation-failures.csv(실패만)
  - 성공률은 스킵 제외 기준 (passed / (total-skipped))

### 설계 판단
- 문서(11번)의 HTML 리포트는 방대해 향후 확장으로 미룸.
  콘솔/JSON/CSV 핵심 3종 우선 구현 (자동화·Excel 검토에 충분)

### 실 검증 (통합)
- Java ValidationResult 형태 3건(통과/행수불일치/스킵) → 비교 → 리포트
  → 성공률 50%(스킵 제외), CSV에 실패 1건, 3종 파일 생성 확인

### 파일/테스트
- oma/validation/{comparator,reporter}.py
- tests/unit/test_comparator.py (14), test_reporter.py (8)
- [x] 전체 178 passed

---

## 2026-07-27 | Week 3 Day 13: Python Validation Bridge

### 작업 내용
- oma/validation/java_bridge.py - Java Validator(JAR) 호출 브리지

### 구현 내용
- **JavaValidationBridge**: build_request / validate_batch / _run_jar / from_config
  - 배치 호출: TC 다건을 1회 프로세스 호출로 전달 (JVM/매퍼 로딩 반복 회피)
  - 시크릿→JDBC URL 변환:
    - Oracle: jdbc:oracle:thin:@//host:port/service (service_name, PDB 대응)
    - PostgreSQL: jdbc:postgresql://host:port/database
  - subprocess.run(stdin=요청JSON) → stdout JSON 파싱
  - 타임아웃/실행실패/JAR없음/파싱실패 → ValidationError
  - 자격증명 주입(테스트 용이), 로그에 미출력
- from_config: MAPPER_WORK_DIR 기반 original(소스)/merged(타겟) 경로 자동 구성

### 설계 판단
- 문서 예시는 TC당 프로세스 1개(느림) → 배치 1프로세스로 개선
  (Java JAR이 배치 요청 지원하도록 Day11-12에 설계)
- 소스 매퍼=mappers/original, 타겟 매퍼=mappers/merged 규약

### 실 검증
- 브리지→JAR e2e: 테스트 매퍼로 "SELECT 1 AS one WHERE x = ?" 동적 SQL 완성 +
  실제 PostgreSQL 실행, status=ok 확인
- 단위 테스트 11개 (subprocess mock): URL구성/배치/타임아웃/에러/빈입력/from_config

### 파일/테스트
- oma/validation/java_bridge.py
- tests/unit/test_java_bridge.py (11)
- [x] 전체 156 passed

---

## 2026-07-27 | Week 3 Day 11-12: Java Validator

### 작업 내용
- java-validator/ Maven 프로젝트 신규 생성 (Java 17, MyBatis 3.5.13)
- MyBatis getBoundSql 기반 SQL 추출 + DB 실행 검증 엔진

### 구현 내용
- **pom.xml**: MyBatis/ojdbc11/postgresql/mysql-connector/gson,
  maven-compiler-plugin 3.11(release 17), shade 플러그인으로 fat jar
- **모델**: TestCase(getStatementId), ExtractedSql, ExecutionResult
  (select/dml/skipped/failure 팩토리), ValidationResult
- **SqlExtractor**: getBoundSql(parameters)로 동적 SQL 완성.
  ParameterMapping 순서대로 값 추출(additionalParameters=foreach 우선 → MetaObject
  → Map → parameterObject 폴백)
- **DatabaseExecutor**: PreparedStatement 실행. 프로시저(CALL/EXEC/BEGIN..END) 스킵,
  DML(INSERT/UPDATE/DELETE/MERGE) 트랜잭션 롤백, SELECT 최대 1만행 샘플링,
  예외 시 안전 롤백+AutoCommit 복원
- **ValidationService**: main. stdin JSON 요청 → 소스/타겟 팩토리 2개 구성
  (같은 namespace+id라도 SQL 다르므로 분리) → TC별 추출·실행 → stdout JSON
- **MapperFactoryBuilder**: 디렉토리 재귀로 매퍼 XML 로드 (._ 제외, 실패 시 계속)
- **SingleConnectionDataSource**: close 무시 프록시 커넥션 (MyBatis Environment용)

### 설계 판단 (문서 대비)
- 10-validation-design.md는 단일 SqlExtractor 예시지만, 소스(원본 Oracle 매퍼)와
  타겟(변환된 PG 매퍼)은 SQL이 다르므로 SqlSessionFactory를 2개로 분리 구현
- Oracle 접속은 실제 검증 시 oracledb(Python)와 별개로 Java는 ojdbc11 사용

### 빌드/실 검증
- mvn package 성공 → java-validator/target/oma-validator.jar (15MB fat jar)
- 잘못된 JSON → error JSON 반환 확인
- 실 PostgreSQL 연결 + 테스트 매퍼로 동적 SQL 추출 확인:
  status/ids 파라미터 → "WHERE status = ? AND id IN (?,?,?)" (foreach 3개 전개)
  (users 테이블은 미존재라 실행은 실패 = 예상된 동작. 추출/바인딩/실행/에러/JSON
   전 과정 정상)

### 파일
- java-validator/pom.xml
- java-validator/src/main/java/com/oma/validator/{ValidationService, SqlExtractor,
  DatabaseExecutor, MapperFactoryBuilder, SingleConnectionDataSource}.java
- java-validator/src/main/java/com/oma/validator/model/{TestCase, ExtractedSql,
  ExecutionResult, ValidationResult}.java

### 참고
- .gitignore에 java-validator/target/ 추가 필요 (다음 커밋 전)
- 파이썬 테스트 145개는 영향 없음 (Java 별도 모듈)

---

## 2026-07-27 | 디렉토리 재구성: oma2/oma → oma/app (최종 레이아웃)

### 배경
- OMA는 환경구성/스키마변환/앱변환 3가지로 구성. 현재 이 코드는 "앱 변환"임
- 최종 목표 구조: /workspace/oma/{env, schema, app} 로 3개를 합칠 예정
- 지금은 앱 변환 고도화 단계 → 폴더명을 app으로 명확히

### 조치 (전부 rename, 삭제 없음)
1. /workspace/oma (기존 env/schema 자산, aws-samples 저장소) → /workspace/oma-legacy
   (git 연결 없음 확인, tar 백업 2개도 존재하여 안전)
2. /workspace/oma2/oma → /workspace/oma2/app
3. /workspace/oma2 → /workspace/oma
   → 최종: 우리 작업 = /home/ec2-user/workspace/oma/app
4. oma.properties: OMA_BASE_DIR=/workspace/oma2/oma → /workspace/oma/app

### 하드코딩 점검 결과
- 코드(.py): 절대경로 하드코딩 0건 (전부 OMA_BASE_DIR 파생, test_config는 __file__ 상대)
- 살아있는 하드코딩은 oma.properties의 OMA_BASE_DIR 1곳뿐 → 수정 완료
- 문서(02/07/09): 예시 경로를 workspace/oma/app 으로 현행화

### 검증
- config: PROJECT_WORK_DIR=/workspace/oma/app/projects/wms 정상
- 딕셔너리 14,114컬럼 로드 정상 (산출물은 rename으로 자동 따라옴)
- 전체 145 passed
- 향후 env/schema를 oma/ 아래로 합치면 oma2 접미사 없이 최종 구조 완성

---

## 2026-07-27 | 작업 경로 정정: OMA_BASE_DIR을 코드 위치와 일치

### 문제
- 코드는 /home/ec2-user/workspace/oma2/oma 에 있는데, OMA_BASE_DIR이
  /home/ec2-user/workspace/oma 로 돼 있어 작업 산출물이 엉뚱한 곳(oma)에 생성됨
- 게다가 /home/ec2-user/workspace/oma 는 별도 git 저장소(다른 프로젝트)였음

### 조치
- oma.properties: OMA_BASE_DIR=/home/ec2-user/workspace/oma → .../oma2/oma
- 기존 산출물 projects/ 폴더만 신 위치로 이동 (mv). 구 위치의 다른 프로젝트
  파일(app/env/schema/.git 등)은 건드리지 않음
- .gitignore 신규 생성: /projects/, __pycache__, .pytest_cache 등 제외

### 검증
- 새 경로 PROJECT_WORK_DIR=.../oma2/oma/projects/wms
- 딕셔너리(14,114컬럼)·조각(3,048개) 이동 후 정상 로드
- 전체 112 passed

---

## 2026-07-27 | Week 2 Day 10: Checkpoint (Week 2 완료)

### 작업 내용
- oma/workflow/checkpoint.py - 워크플로우 진행 상황 저장 및 재시작 지원

### 구현 내용
- **CheckpointManager**: Phase 1-7 진행 + Phase4 조각 단위 완료/실패 추적
  - mark_phase_started/completed, is_completed, current_phase, is_fresh_run
  - mark_fragment_completed(멱등)/failed(can_retry=retry<3), get_pending_fragments,
    get_retryable_failures, clear_failure
  - update_statistics, reset
  - 완료 조각은 set으로도 유지 → 대규모 pending 조회 O(1)
- **원자적 저장**: tmp 파일 작성 후 os.replace (중간 크래시 시 손상 방지)
- **재시작**: 파일 로드로 상태 복원, 손상 파일이면 자동 재생성
- datetime timezone-aware(now(timezone.utc)), 시간함수 주입 가능(테스트)
- 디렉토리 경로 주면 .checkpoint.json 자동 사용

### 설계 보완 (문서 대비)
- 13-error-handling-restart.md는 datetime.utcnow()(deprecated) 사용 →
  now(timezone.utc)로 교체
- completed_fragments 리스트 + set 병행으로 조회 성능 확보

### 파일/테스트
- oma/workflow/checkpoint.py
- tests/unit/test_checkpoint.py (16)
- pytest.ini: python_classes를 매칭 안 되는 패턴으로 (도메인 클래스 오수집 방지)
- [x] 전체 145 passed

### Week 2 완료 요약
- Day 6 TypeCaster / Day 7 TCGenerator / Day 8 Converter / Day 9 Merger /
  Day 10 Checkpoint 전부 완료. 변환 파이프라인(분할→변환→병합)+재시작 기반 완성

---

## 2026-07-27 | Week 2 Day 9: Merger

### 작업 내용
- oma/merger/combiner.py - 변환 조각을 원본 매퍼 구조로 재조립

### 구현 내용
- **MapperCombiner**: merge / merge_with_report / merge_to_string / merge_to_file
  - 원본 매퍼를 뼈대로 파싱 후, 각 statement를 변환 조각으로 교체(요소 치환)
  - (statement_type, sql_id) 키로 조각 매칭, id 없는 요소는 splitter의
    합성 id(__el_{tag}_{index}) 규칙과 동일하게 매칭
  - 원본 tail 승계로 들여쓰기/포맷 유지, namespace/DOCTYPE/순서/주석 보존
  - MergeReport: replaced / not_replaced(조각없어 원본유지) / unused_fragments
- lxml 사용 (정규식 XML 조작 금지)

### 버그 수정
- lxml: encoding="unicode" + xml_declaration 동시 사용 불가 →
  UTF-8 바이트로 직렬화 후 decode

### 실 검증 (sample-app)
- 단일 매퍼: namespace/DOCTYPE/statement 순서 완전 보존 확인
- 전체 197개 매퍼 split→merge 라운드트립: 성공 197 / 실패 0 (0.3s)

### 파일/테스트
- oma/merger/combiner.py
- tests/unit/test_merger.py (9)
- [x] 전체 129 passed

---

## 2026-07-27 | Week 2 Day 8: Converter (통합)

### 작업 내용
- oma/converter/converter.py - 변환 통합 오케스트레이터
- oma/converter/prompts.py - LLM 변환 프롬프트 (SYSTEM + build_conversion_prompt)

### 구현 내용
- **Converter.convert(fragment)** → ConversionResult
  1) SqlAnalyzer 분석 → 2) manual_review 전략이면 LLM 없이 스킵(사유 기록)
  3) LLM invoke_json 변환 → 4) TestCaseGenerator로 TC 생성 → 5) 통합
  - LLM 실패 시 status=failed, 원본 유지, manual_review 플래그 (중단 안 함)
  - warning 있으면 manual_review_required=True
- **build_dictionary_subset**: 2단계 문자열 감지(파싱 아님)
  - 1단계: 조각에 등장하는 테이블명 집합 추출
  - 2단계: 그 테이블 소속 + 컬럼명도 조각에 등장하는 컬럼만 채택
  - 테이블 식별 실패 시 컬럼명 단독 매칭 폴백
- prompts.py: 캐스팅/함수변환/동적태그 보존/CHAR 경고 지침 + 출력 JSON 계약

### 실 Bedrock e2e 검증 + 발견/수정
- 초기 subset이 컬럼명 단독 매칭 → CTKEY 하나가 44개 테이블에 매칭되어
  400 상한 초과, 정작 필요한 테이블 컬럼 누락 위험 발견
  → 테이블+컬럼 2단계 매칭으로 개선 (실제 조각에서 400→8개로 정확화)
- 변환 정확성 확인:
  - SND_ROW(numeric) → #{sndRow}::NUMERIC 캐스팅
  - SND_NO(varchar) → 캐스팅 없음
  - SYSDATE → CURRENT_TIMESTAMP 함수 변환
  - varchar 위주 매퍼(취소 update)는 캐스팅 0건이 정답(LLM 올바른 판단)

### 파일/테스트
- oma/converter/{converter,prompts}.py
- tests/integration/test_converter.py (8, LLM mock)
- [x] 전체 120 passed (단위 112 + 통합 8)

---

## 2026-07-27 | Week 2 Day 7: Test Case Generator

### 작업 내용
- oma/testcase/generator.py - 동적 SQL 테스트 케이스 생성기

### 구현 내용
- **TestCaseGenerator**: extract_dynamic_elements / generate / to_dict
  - lxml로 <if>/<choose>/<foreach> 추출 (XML 구조 → 결정론적, 정규식 아님)
  - #{param} 추출은 토큰 스캔(str.find), ageRange.min→ageRange 루트명
  - 시나리오: <if> 최소+각단일+최대, <choose> 각 when+otherwise,
    <foreach> 0/1/N개
  - 샘플 값: param_columns 매핑 + 딕셔너리 sample_value 우선, 없으면 타입 기본값
  - TC id 형식 {mapper}_{sqlId}_tc{NNN}
- DynamicElement/TestCase 데이터클래스

### 버그 발견·수정 (실 데이터 검증 중)
- **lxml tail 혼입**: <if> 요소의 params에 </if> 뒤 정적 파라미터까지 포함됨
  - 원인: etree.tostring(element)가 요소의 tail(닫는 태그 뒤 형제 텍스트)까지
    직렬화 → if 바깥 #{sysdate} 등이 if 파라미터로 오인됨
  - 수정: 직렬화 전 element.tail을 임시 제거 후 복원
  - 회귀 테스트 추가(test_if_params_exclude_tail_text)
  - 실제 매퍼(updaetInboundOrderHeader): 수정 후 TC 8→2개로 정확화

### 설계 판단
- 04-test-case-generation.md는 LLM이 파라미터-컬럼 매핑/조건 의미까지 추론하는
  전제. 여기서는 구조적으로 추출 가능한 것(동적 태그, #{param})만 결정론적으로
  처리하고, 매핑/의미 해석은 param_columns 주입 또는 LLM 단계로 위임

### 파일/테스트
- oma/testcase/generator.py
- tests/unit/test_testcase_generator.py (13)
- pytest.ini 추가 (python_classes=Check* — 도메인 TestCase 오수집 방지)
- [x] 전체 112 passed

---

## 2026-07-27 | Week 2 Day 6: Type Caster

### 작업 내용
- oma/converter/type_caster.py - 딕셔너리 기반 타입 캐스팅 엔진

### 구현 내용
- **TypeCaster**: cast_for_column / apply_bind_cast / build_type_casts
  - cast_for_column: 딕셔너리 cast_hint로 캐스팅 구문/경고 판단
    (숫자·날짜→::TYPE, varchar/text→없음, CHAR→경고, 미발견→경고)
  - apply_bind_cast: #{var} 토큰에 ::TYPE 추가. str.find 기반(정규식 X),
    멱등(이미 캐스팅된 것 재적용 안 함), #{var,jdbcType=..} 형태는 미변경
  - build_type_casts: (bind_var→column) 매핑으로 전체 변환 + type_casts/warnings 리포트
- CastResult/TypeCastReport 데이터클래스

### 설계 판단 (문서 03과의 관계)
- 03-type-casting-strategy.md는 LLM이 SQL을 파싱해 바인드↔컬럼 매핑 후 캐스팅하는
  전제. 우리는 정규식 SQL 파싱 금지 → TypeCaster는 SQL을 파싱하지 않고,
  (bind_var→column) 매핑을 입력으로 받아 딕셔너리 근거로 결정론적 캐스팅만 수행.
  바인드↔컬럼 매핑 추론은 LLM 변환 단계(Day 8 converter)의 책임.
- 이렇게 분리하면: 파싱=LLM(비결정), 캐스팅=엔진(결정/검증가능)

### 실 검증
- wms 딕셔너리: snd_row(numeric)→::NUMERIC, snd_no(varchar)→없음,
  downloadyn(char)→경고. build_type_casts로 실제 조각 변환 확인

### 파일/테스트
- oma/converter/type_caster.py
- tests/unit/test_type_caster.py (10)
- [x] 전체 99 passed

---

## 2026-07-27 | Week 1 Day 4-5: LLM Client + SQL Analyzer

### 작업 내용
- oma/converter/llm_client.py - AWS Bedrock Claude 호출
- oma/converter/sql_analyzer.py - SQL 크기/복잡도 분석 및 전략 분류

### 구현 내용
- **LLMClient**: invoke(텍스트)/invoke_json(JSON 파싱). Anthropic Messages API
  포맷(invoke_model, anthropic_version=bedrock-2023-05-31)
  - _respect_rate_limit: RPM 기반 최소 간격 준수
  - calculate_backoff: 지수 백오프 base*(2**n), 상한 300초
  - 재시도: Throttling/ServiceUnavailable/Timeout 등만 재시도, 그 외 즉시 실패
    (예외 클래스명 + botocore ClientError code 판별)
  - _strip_code_fence: ```json 펜스 제거 후 파싱 (정규식 미사용)
  - bedrock 클라이언트 주입 가능 (테스트), 자격증명/본문 로그 미출력
- **SqlAnalyzer**: analyze/classify_complexity/select_conversion_strategy
  - 복잡도 = JOIN + <if>*2 + <choose>*3 + <foreach>*2 (단순 카운팅)
  - 레벨: simple/moderate/complex/very_complex
  - 전략: standard / standard_with_compression / chunked / manual_review

### 실 검증
- Bedrock 실제 호출 성공: invoke_json으로 NVL(name,'?') → COALESCE(name,'?')
- sample-app 3,048 조각 분석: standard 3,047 / chunked 1
  (최대 조각 53,294자 = 17.7K토큰, complex → chunked 전략)

### 주의사항 / 문서와의 차이
- 14-large-sql-handling.md의 청킹 예시는 정규식으로 SQL을 파싱함 → 하드 룰 위반.
  SqlAnalyzer는 크기/복잡도 산출 + 전략 분류까지만 하고, 실제 의미단위 분할은
  converter 단계에서 구조 기반(비정규식)으로 별도 구현 예정
- 모델 ID: global.anthropic.claude-opus-4-8 (config BEDROCK_MODEL_ID)

### 파일/테스트
- oma/converter/{llm_client,sql_analyzer,__init__}.py
- tests/unit/test_llm_client.py (11), test_sql_analyzer.py (9)
- [x] 전체 89 passed

---

## 2026-07-27 | Week 1 Day 3: Fragmenter 모듈

### 작업 내용
- oma/fragmenter/splitter.py 생성 - MyBatis 매퍼를 SQL ID별 조각으로 분할
- 소스 임시 설정: SOURCE_WORKSPACE=.../source/sample-app

### 구현 내용
- **Fragment/MapperSplitResult** 데이터클래스
- **MapperSplitter**: split/split_file/split_workspace/find_mapper_files/
  build_mapping
  - lxml.etree 파서 (no_network, load_dtd=False, resolve_entities=False,
    strip_cdata=False) — 외부 DTD 네트워크 차단 + CDATA 보존, 정규식 미사용
  - 최상위 statement(select/insert/update/delete/sql/resultMap/parameterMap)를
    조각으로 분리, id 없는 요소(cache 등)는 합성 id로 손실 없이 보존
  - build_mapping: 조각↔원본 매핑(mapping.json 내용) 생성
  - 개별 매퍼 파싱 실패는 건너뛰고 계속 (전체 중단 방지)

### 실 DB/파일 검증 (sample-app)
- 전체 스캔에서 매퍼 후보 10,282개(._ 제외) 발견
- **핵심 발견**: 10,085개는 app-migration/pipeline(그들의 기존 마이그레이션
  백업/산출물), 실제 소스 매퍼는 src/main의 197개뿐
  → MAPPER_EXCLUDE_DIRS(app-migration 등)로 제외 처리
- 실제 매퍼 197개 → 3,048 조각 (실패 0). 동적SQL(<if>/<choose>/<foreach>) 및
  CDATA 온전히 보존. namespace 없는 매퍼/ id 없는 조각 0
- projects/wms/mappers/fragmented/ 에 조각 3,048개 + mapping.json 저장 확인

### 주의사항 / 발견
- macOS AppleDouble 파일(._*.xml) 35개는 매퍼 후보에서 제외
- 이스케이프 안 된 '<'(예: WHERE lvl < 3)는 엄격 XML 파서에서 실패 →
  MyBatis는 관대하나 lvl<3 같은 패턴은 CDATA/&lt; 필요. 실제 소스엔 없었고
  백업파일 1건에서만 발생 → 파싱 실패 시 파일/라인 포함 ConversionError로 보고
- 조각 파일 저장 로직은 검증 스크립트에서 수행. 정식 저장은 workflow orchestrator
  단계에서 통합 예정 (splitter는 분할/매핑까지 책임)

### 파일/테스트
- oma/fragmenter/{splitter,__init__}.py
- tests/unit/test_fragmenter.py (14)
- [x] 전체 69 passed

---

## 2026-07-27 | DB 연결 플러그인 (연결 중심 최소 구현) + 딕셔너리 e2e

### 작업 내용
- oma/plugins/ DB 연결 플러그인 구현 및 builder 연동
- 시크릿→플러그인→builder 정식 경로로 wms 딕셔너리 생성 검증

### 구현 내용
- **base.py**: BaseDB(ABC) + SourceDB/TargetDB. connect/disconnect/
  get_connection/get_schema_name/get_sql_dialect/test_connection, 컨텍스트매니저
- **source_oracle.py**: OracleSource. oracledb(thin) 사용,
  service_name 먼저 시도 → 실패 시 SID 폴백 (PDB/비CDB 자동 대응)
- **target_postgres.py**: PostgresTarget. psycopg2, connect_timeout,
  스키마=schema|username
- **factory.py**: create_source/create_target. SOURCE/TARGET_DB_TYPE로 선택,
  USE_SECRETS_MANAGER=true면 시크릿, false면 config 로컬값으로 자격증명 구성.
  SecretsManager 주입 가능(테스트 용이)
- **builder 연동**: DictionaryBuilder(config, target=플러그인) 지원.
  커넥션+스키마를 플러그인에서 자동 획득 (기존 connection/TARGET_SCHEMA 경로 유지)

### 검증 (실 DB)
- create_target(config) → test_connection() True
- builder.build() → schema=appdb, 14,114개 컬럼 생성 (정식 경로, 수동 주입 X)

### 주의사항
- Oracle 드라이버는 oracledb(thin). requirements.txt cx-Oracle → oracledb 정정
- 시크릿의 sid 키는 실제 service_name일 수 있음 → 폴백 로직으로 흡수
- edb/tibero/mysql 플러그인은 미구현 (팩토리에서 명확한 ConfigError)

### 파일/테스트
- oma/plugins/{base,source_oracle,target_postgres,factory,__init__}.py
- tests/unit/test_plugins.py (13), test_dictionary_builder(+1 target 주입)
- [x] 전체 55 passed

---

## 2026-07-27 | Secrets 컨벤션 정리 + 프로젝트명 wms 전환

### 작업 내용
- AWS Secrets Manager: 기존 시크릿을 우리 컨벤션 이름으로 동일 내용 복사 생성
- oma.properties: APPLICATION_NAME=oma → wms (wms 프로젝트로 딕셔너리 생성 확인용)

### 시크릿 매핑 (내용 동일, 이름만 컨벤션화)
- oma-secret-oracle-admin    → oma-source-admin
- oma-secret-oracle-service  → oma-source-service
- oma-secret-postgres-admin  → oma-target-admin
- oma-secret-postgres-service→ oma-target-service
- 컨벤션: 제품 공통(oma-*), source=oracle / target=postgres
- 검증: 4개 모두 원본과 내용 MATCH, SecretsManager 로더로 조회 성공

### 주의사항
- 새 시크릿은 create-secret로 생성(기존 존재 시 put-secret-value로 갱신하도록 처리)
- properties의 SOURCE/TARGET_SECRET_NAME은 이미 oma-source-admin/
  oma-target-service 라 변경 불필요
- APPLICATION_NAME 변경으로 작업 경로가 projects/wms/ 로 자동 전환됨
- test_config: APPLICATION_NAME=="oma" 하드코딩 단정 제거 (값 비의존으로 수정)

### 테스트
- [x] 전체 41 passed

---

## 2026-07-27 | Week 1 Day 2: Dictionary 모듈

### 작업 내용
- `oma/dictionary/builder.py` 생성 - 타겟 DB 메타데이터 → 딕셔너리 생성
- `oma/dictionary/loader.py` 생성 - 딕셔너리 로드 및 조회
- `oma/dictionary/__init__.py` - export

### 구현 내용
- **DictionaryBuilder**: build/extract_metadata/collect_samples/
  generate_cast_hints/save_to_file
  - information_schema.columns 조회로 메타데이터 추출
  - 테이블별 샘플 1건 수집 (개별 실패 시 경고 후 계속)
  - 캐스팅 힌트: 숫자→needs_cast_from_string+cast_syntax, CHAR→needs_trim,
    날짜→::TIMESTAMP 등. 규칙은 _NUMERIC_CAST_SYNTAX 등 모듈 상수로 분리
  - connection 주입 가능 (테스트 용이), 식별자는 psycopg2.sql.Identifier로
    안전 조합 (문자열 포맷/인젝션 금지)
  - 샘플 값은 _to_serializable로 JSON 직렬화 (date/Decimal → str)
- **DictionaryLoader**: load(캐싱)/lookup(대소문자 무관, 미발견 시
  {"found": False})/has. 조회 실패해도 예외 없이 진행 (설계 원칙)

### 주의사항
- builder는 **타겟 DB(PostgreSQL)** 기준. TARGET_SCHEMA/TARGET_* 설정 사용
- lookup 결과에 found를 더할 때 원본 딕셔너리를 훼손하지 않도록 복사본 반환
- collect_samples는 SELECT * 사용 (컬럼 순서 = information_schema 순서와 무관,
  cursor.description으로 컬럼명 매핑)

### 파일 위치
- `oma/dictionary/builder.py` (~330 lines)
- `oma/dictionary/loader.py` (~130 lines)

### 테스트
- [x] `tests/unit/test_dictionary_builder.py` (8, fake connection)
- [x] `tests/unit/test_dictionary_loader.py` (10)
- [x] 전체 41 passed

---

## 2026-07-27 | 문서 현행화: 멀티 프로젝트 경로 반영

### 작업 내용
- 모든 설계 문서의 작업 경로를 `app/` → `projects/<APPLICATION_NAME>/` 로 갱신
- testcases/reports/.checkpoint.json 위치를 mappers 밖(프로젝트 폴더 직속)으로 정정
- README에 코드 모듈(공통) vs 작업 디렉토리(프로젝트별) 구분 및 새 트리 추가

### 갱신 파일
- README.md: utils/logger/exceptions 구현 반영, projects/ 트리 추가, 상태 라벨,
  Python 3.11 권장 명시
- 07-configuration-guide.md: PROJECT_WORK_DIR 등 신규 키 설명 추가
- 09-file-locations.md: 최상위 트리 재작성 + 요약표 경로 갱신
- 02-conversion-workflow.md: 상단/최종 구조 트리 재작성, 체크포인트 경로
- 04-test-case-generation.md, 08-binding-failure-tracking.md: 구조 트리 재작성
- 13/11/00 문서: MAPPER_WORK_DIR 하위 reports/testcases 참조 → 신규 키로 치환

### 방법
- Python str.replace 1회성 스크립트(_update_paths.py)로 일괄 치환 후 삭제
  (sed 금지 규칙 준수). 트리 그림은 직접 수정
- 검증: 잔여 app/ 경로 grep 0건, 단위 테스트 23 passed

### 미처리 (별도 이슈)
- 02 문서에 `oracle_dictionary.json` 잔존 → 범용 이름 `schema_dictionary.json`
  으로의 전환은 경로 현행화와 별개 작업이라 이번 범위에서 제외

---

## 2026-07-27 | 멀티 프로젝트 지원: 작업 경로를 projects/<APPLICATION_NAME> 아래로

### 작업 내용
- `oma.properties`의 작업/산출물 경로를 프로젝트명별 계층으로 변경
- 목적: 여러 프로젝트를 동시에 처리해도 산출물이 섞이지 않도록

### 구현 내용
- `PROJECT_WORK_DIR=${OMA_BASE_DIR}/projects/${APPLICATION_NAME}` 신설
- `MAPPER_WORK_DIR`, `SCHEMA_DICT_PATH`를 PROJECT_WORK_DIR 기준으로 변경
  (기존 `${OMA_BASE_DIR}/app/...` → `${PROJECT_WORK_DIR}/...`)
- `TESTCASE_DIR`, `REPORT_DIR`, `CHECKPOINT_PATH` 추가 (모두 프로젝트 폴더 아래)
- 결과: `.../projects/oma/{mappers,output,testcases,reports,.checkpoint.json}`

### 주의사항
- **코드 모듈(converter/plugins/utils/validation/workflow 등)은 프로젝트 공통**
  이므로 프로젝트별로 나누지 않음 (코드 복제 방지). 프로젝트명 계층은 오직
  실행 중 생성되는 "작업 데이터"에만 적용됨
- `${APPLICATION_NAME}`은 [oma] 섹션에 정의돼 있으나 Config의 다중 패스
  치환으로 정상 해결됨 (섹션은 평탄화됨)

### 파일 위치
- `oma.properties` (Conversion Settings 섹션)
- `tests/unit/test_config.py` (경로 assert 갱신 + test_config_per_project_work_dir 추가)

### 테스트
- [x] 전체 23 passed

---

## 2026-07-26 | Week 1 Day 1: 기반 유틸리티 모듈

### 작업 내용
- 프로젝트 패키지 구조 생성 (oma/*, tests/*, scripts/)
- `requirements.txt` 작성
- `oma/utils/exceptions.py` 생성 - 공용 예외 계층
- `oma/utils/config.py` 생성 - oma.properties 로더
- `oma/utils/secrets.py` 생성 - AWS Secrets Manager 연동
- `oma/utils/logger.py` 생성 - 로깅 설정
- `oma/utils/__init__.py` - 공개 API export

### 구현 내용
- **exceptions**: `OMAError` 베이스 + `ConfigError`, `ConversionError`,
  `ValidationError`, `LLMError`, `DatabaseError`. message + context(dict) 지원
- **Config**: INI 섹션 헤더 무시, 전체/인라인 주석 제거, `${VAR}` 치환
  (설정 키 우선 → 환경 변수), int/float 자동 형변환, get_int/get_bool/get_list
  - 정규식 미사용 (str.partition/find 로 파싱) — 코딩 가이드라인 준수
- **SecretsManager**: boto3 클라이언트 주입 가능(테스트 용이), 인스턴스 캐싱,
  SecretString→JSON dict 파싱. 편의 함수 `get_secret(secret_name, region)` 제공
- **setup_logger**: 콘솔+선택적 파일 핸들러, 핸들러 중복 방지, LOG_LEVEL 폴백

### 주의사항
- Config는 전역 변수 없이 인스턴스로만 사용 (의존성 주입)
- 시크릿 값은 로그에 절대 남기지 않음
- `get_secret` 편의 함수와 `SecretsManager` 클래스를 중복 조회 로직으로 각각
  만들지 말 것 — 편의 함수는 내부적으로 클래스를 재사용함

### 파일 위치
- `oma/utils/exceptions.py` (~70 lines)
- `oma/utils/config.py` (~300 lines)
- `oma/utils/secrets.py` (~150 lines)
- `oma/utils/logger.py` (~140 lines)

### 테스트
- [x] `tests/unit/test_config.py` (12)
- [x] `tests/unit/test_secrets.py` (6, mock)
- [x] `tests/unit/test_logger.py` (4)
- [x] 전체 22 passed (python3.11 -m pytest tests/unit)

### 환경 메모
- 시스템 python3 = 3.9.25 (pip 없음). python3.11 사용 권장 (README 요구사항 일치)
- pytest 9.1.1 은 python3.11 에 설치됨. 테스트는 `python3.11 -m pytest` 로 실행

---
