# OMA 구현 진행 체크리스트

> 기준 문서: `16-implementation-guide.md` (20일 계획)
> 규칙: 작업 완료 시 `[ ]` → `[x]` 로 체크하고, 상세 내역은 `WORK_LOG.md`에 기록
> 표기: `[x]` 완료 · `[~]` 진행 중 · `[ ]` 예정

**최종 업데이트**: 2026-07-27 (Day 2 완료)

---

## Week 1: 기반 모듈 (Day 1-5)

### Day 1: 프로젝트 초기화 및 Config  ✅ 완료
- [x] Step 1.1: 프로젝트 구조 생성 (oma/*, tests/*, scripts/ + __init__.py)
- [x] Step 1.2: requirements.txt 작성
- [x] Step 1.3: oma/utils/exceptions.py (OMAError 외 5종)
- [x] Step 1.4: oma/utils/config.py + test_config.py
- [x] Step 1.5: oma/utils/secrets.py + test_secrets.py (mock)
- [x] Step 1.6: oma/utils/logger.py + test_logger.py

### Day 2: Dictionary 모듈  ✅ 완료
- [x] Step 2.1: oma/dictionary/builder.py + test_dictionary_builder.py
- [x] Step 2.2: oma/dictionary/loader.py + test_dictionary_loader.py

### Day 3: Fragmenter 모듈  ✅ 완료
- [x] Step 3.1: oma/fragmenter/splitter.py + test_fragmenter.py (lxml, 정규식 금지)
      - 실 검증: sample-app 실제 매퍼 197개 → 3,048 조각 (동적SQL/CDATA 보존)
      - ._ AppleDouble 제외, MAPPER_EXCLUDE_DIRS로 백업/파이프라인 디렉토리 제외

### Day 4-5: LLM Client 및 분석기  ✅ 완료
- [x] Step 4.1: oma/converter/llm_client.py + test_llm_client.py (Rate limit, backoff)
      - 실 검증: Bedrock Claude 호출 성공 (NVL→COALESCE 변환)
- [x] Step 4.2: oma/converter/sql_analyzer.py + test_sql_analyzer.py
      - 실 검증: sample-app 3,048조각 분석 (standard 3047 / chunked 1)
      - 정규식 SQL 파싱 없이 카운팅만 (청킹 분할은 converter 단계로 이연)

---

## Week 2: 변환 모듈 (Day 6-10)

### Day 6: Type Caster  ✅ 완료
- [x] Step 6.1: oma/converter/type_caster.py + test_type_caster.py
      - 딕셔너리 기반 결정론적 캐스팅 엔진 (SQL 파싱 안 함, str.find 멱등)
      - 실 검증: wms 딕셔너리로 numeric→::NUMERIC, varchar 미캐스팅, CHAR 경고

### Day 7: Test Case Generator  ✅ 완료
- [x] Step 7.1: oma/testcase/generator.py + test_testcase_generator.py
      - lxml로 if/choose/foreach 추출, 분기 시나리오(최소/단일/최대, 0/1/N) 생성
      - 실 검증 중 lxml tail 버그 발견·수정 (if 뒤 정적 파라미터 혼입)

### Day 8: Converter (통합)  ✅ 완료
- [x] Step 8.1: oma/converter/converter.py + prompts.py + test_converter.py
      - analyzer→(manual_review 스킵)→LLM 변환→TC 생성 통합
      - 딕셔너리 subset: 테이블+컬럼 2단계 매칭 (400→8개로 정확화)
      - 실 Bedrock e2e: SND_ROW→::NUMERIC, SYSDATE→CURRENT_TIMESTAMP 확인

### Day 9: Merger  ✅ 완료
- [x] Step 9.1: oma/merger/combiner.py + test_merger.py (lxml)
      - 원본 매퍼 뼈대 유지하며 조각 교체 (namespace/DOCTYPE/순서 보존)
      - 실 검증: sample-app 197개 split→merge 라운드트립 성공 0실패

### Day 10: Checkpoint  ✅ 완료
- [x] Step 10.1: oma/workflow/checkpoint.py + test_checkpoint.py
      - Phase 1-7 진행 + Phase4 조각 단위 완료/실패 추적, 재시작 지원
      - 원자적 저장(tmp+os.replace), 손상 파일 자동 복구, 통계 갱신

---

## Week 3: 검증 모듈 (Day 11-15)

### Day 11-12: Java Validator  ✅ 완료
- [x] Step 11.1: java-validator/pom.xml (MyBatis/JDBC/Gson, shade fat jar, Java 17)
- [x] Step 11.2: 모델 클래스 (TestCase/ExtractedSql/ExecutionResult/ValidationResult)
- [x] Step 11.3: SqlExtractor.java (getBoundSql로 동적 SQL 완성 + 파라미터 추출)
- [x] Step 11.4: DatabaseExecutor.java (DML 롤백, 프로시저 스킵, SELECT 샘플링)
- [x] Step 11.5: ValidationService.java (main + stdin/stdout JSON, 소스/타겟 팩토리 2개)
      + MapperFactoryBuilder, SingleConnectionDataSource
      - 빌드 성공(15MB jar), 실 검증: foreach가 (?,?,?)로 펼쳐짐 확인

### Day 13: Python Validation Bridge  ✅ 완료
- [x] Step 13.1: oma/validation/java_bridge.py + test_java_bridge.py (mock)
      - JAR subprocess 호출, 배치 검증(TC 다건 1프로세스), 시크릿→JDBC URL
      - Oracle service_name URL, 타임아웃/에러 처리
      - 실 검증: 브리지→JAR로 동적 SQL 완성+PG 실행 확인

### Day 14: Comparator & Reporter  ✅ 완료
- [x] Step 14.1: oma/validation/comparator.py + test_comparator.py
      - 행수/컬럼/값 비교, 숫자 tolerance, CHAR 패딩 무시, 실패유형 분류
- [x] Step 14.2: oma/validation/reporter.py + test_reporter.py
      - 콘솔 요약 + JSON(summary/details) + CSV(failures), 성공률(스킵 제외)

### Day 15: Validation Orchestrator  ✅ 완료
- [x] Step 15.1: oma/validation/orchestrator.py + test_validation.py
      - TC 로드→JavaBridge 검증→Comparator 비교→Reporter 리포트 통합
      - 개별 TC 로드 실패 건너뜀, from_config 팩토리

---

## Week 4: 통합 및 테스트 (Day 16-20)

### Day 16-17: Workflow Orchestrator  ✅ 완료
- [x] Step 16.1: oma/workflow/orchestrator.py + test_workflow.py
      - preflight + Phase 1-7 통합, 체크포인트 연동, Phase별 메서드 분리
- [x] Step 16.2: 변환 리포트 저장 (오케스트레이터 통합)
      - converted/{mapper}__{sqlId}.xml + .report.json + conversion-summary.json
- [x] Step 16.3: 특수변수 치환/preflight 파이프라인 통합
      - oma/preprocess/special_variables.py 정식 모듈화, Phase2에 편입
- [x] 실 e2e: sample-app 197매퍼 → 복사·치환(1360+1569)·분할(3048)·
      변환(fake)·병합(197)·타겟복사(197) 전체 파일 파이프라인 통과
- [x] Phase7 TARGET_WORKSPACE를 안전한 target-output으로 변경(기존 앱 소스 보호)

### Day 18: Main Script  ✅ 완료
- [x] Step 18.1: scripts/run_oma.py (argparse, --phase, --preflight, --retry-failed)
      - phase 별칭 파싱, 협력자 지연 조립(필요 Phase만 DB/LLM 연결)
      - 실 CLI 검증: --preflight, --phase copy,fragment 동작 확인

### Day 19: PoC 테스트  ✅ 완료
- [x] Step 19.1: 대표 매퍼 5개 선별 (단순조회/동적SQL/Oracle함수/DML/리포트성)
- [x] Step 19.2: 실제 LLM 변환 포함 E2E (copy→fragment→convert→merge→validate)
      - 변환 17조각 100% success (NVL→COALESCE/SYSDATE→CURRENT_TIMESTAMP/::NUMERIC)
      - 검증: 서비스계정(appdb)으로 통과 10/45 (22.2%)
      - 실패 대부분 TC데이터 제약미충족(NOT NULL 등)·검증인프라, 순수 변환결함 2건
      - 보고서: projects/wms-poc/reports/POC-REPORT.md
      - 발견: 검증은 admin 아닌 service 계정으로 실행해야 함 → properties 분리

### Day 20: 문서화 및 정리
- [ ] Step 20.1: 각 파일 변경 이력 검토
- [ ] Step 20.2: README.md 최종 업데이트
- [ ] Step 20.3: 최종 테스트 + 커버리지 측정 (80% 목표)

---

## 멀티 소스/타겟 투입 준비 상태 (2026-07-28 점검)
현재 실전 투입 가능 조합: **Oracle→PostgreSQL 만** (PoC 검증 완료).
나머지는 구조(팩토리/dialect_rules 슬롯)는 열려있으나 구현 미완.

> ★ **구현 착수 시**: `19-multisource-target-guide.md` 참조 (참고 파일/코드 위치/
>   패턴/검증까지 상세). Claude Code가 그 문서만 보고 바로 구현 가능하도록 작성됨.

조합별 필요 작업 요약:

### Oracle→MySQL (투입 전 필요)
- [ ] oma/plugins/target_mysql.py (MySQL 커넥션, mysql-connector-j는 pom에 이미 있음)
- [ ] factory _TARGET_PLUGINS에 mysql 등록
- [ ] DictionaryBuilder MySQL 지원 (information_schema는 유사하나 타입/길이 컬럼 상이)
- [ ] java_bridge._target_db_config MySQL JDBC URL 분기 (현재 postgres 하드코딩)
- [ ] dialect_rules oracle_to_mysql 실검증 (CAST 문법, IFNULL, LIMIT 등) - 현재 STUB
- [ ] MySQL은 캐스팅 문법 다름(CAST(x AS SIGNED)) → TypeCaster/딕셔너리 cast_hint 확장

### EPAS(EDB)→PostgreSQL (투입 전 필요)
- [ ] oma/plugins/source_epas.py (EPAS 소스 연결 - Oracle호환모드/PG 프로토콜 확인 필요)
- [ ] factory _SOURCE_PLUGINS에 epas 등록
- [ ] java_bridge._source_db_config EPAS JDBC URL 분기
- [ ] dialect_rules epas_to_postgres 실검증 - 현재 STUB (EPAS는 상당수 PG호환)

### 공통
- 프롬프트 구조는 build_system_prompt(source,target)로 이미 멀티 대응
- SOURCE_DB_TYPE/TARGET_DB_TYPE config로 선택 구조는 완성

---

## Plugins (DB 연결) — 연결 중심 최소 구현 완료
- [x] oma/plugins/base.py (SourceDB/TargetDB ABC, 연결 중심)
- [x] oma/plugins/source_oracle.py (oracledb thin, service_name→SID 폴백)
- [x] oma/plugins/target_postgres.py (psycopg2, 스키마=schema|username)
- [x] oma/plugins/factory.py (DB_TYPE 선택 + 시크릿/로컬 자격증명)
- [x] builder 연동 (target 플러그인 주입) + test_plugins.py (13)
- [x] 실 DB e2e 검증: 시크릿→플러그인→builder로 wms 딕셔너리 14,114컬럼 생성
- [ ] oma/plugins/source_edb.py (미구현 스텁)
- [ ] oma/plugins/source_tibero.py (미구현 스텁)
- [ ] oma/plugins/target_mysql.py (미구현 스텁)

---

## 별도 정리 이슈 (백로그)

### TC 생성 - 엣지케이스는 "사람 판단" 방침 (구현 안 함)
- <selectKey>/useGeneratedKeys로 DB가 채우는 keyProperty를 TC 파라미터에서
  제외하는 로직 등은 구현하지 않음. 소수 케이스인데 generator 복잡도/버그위험 큼.
- 방침: 검증 리포트(ORA 오류 등)를 보고 사람이 판단·수정. 도구는 변환·검증·리포트까지.
- 현재 TC 생성 수준: 바인드변수→컬럼(LLM 매핑) + 딕셔너리 샘플값 + 타입/길이 맞춤.
  샘플값 없으면(빈 테이블) 타입기본값("SAMPLE"/1/날짜). 이 정도로 충분.

### 프로젝트 고유값/이름 정리 (Day 20 문서화 시)
- 범용 도구인데 acme/appdb/wms 등 프로젝트 고유 이름이 코드·설정·테스트에 산재
- special_variables.json의 PAGING_ROWNUM 값, OGNL 클래스명(com.example.*) 등도 프로젝트별
- 방침: 프로젝트 고유값은 전부 config/JSON으로 외부화, 코드엔 하드코딩 제거
- Day 20 문서화 단계에서 일괄 점검·정리


### Pre-flight 스캐너  ✅ 구현 완료
- oma/preflight/scanner.py: OGNL/${}변수/미지별칭/파싱오류/프로시저 검출 + 리포트
- 오케스트레이터 통합 시: 변환 전 스캔 → preflight-report.json + 설정 템플릿 출력

### OGNL 정적 메서드  ✅ 테스트용 치환 완료 (실전 방침 확정)
- 테스트: substitute_special_variables.py의 ognl_methods로 != null / == null 치환
- 실전: 고객 OGNL 클래스(com.example.*)를 Validator classpath에 등록, --no-ognl로 치환 끔

### Java Validator 매퍼 로드 실패 44건 (보류 — 딥다이브 안 함)
- LenientConfiguration으로 미지 별칭(camelMap 등)은 HashMap 폴백 → 대부분 해결
- 잔여 44건: resultMap 파싱 관련(HashMap type resultMap에서 생성자 예외 등),
  중복 id 2건 — acme 특유 케이스로 판단, 딥다이브 보류
- 방침: 사전 점검 스캐너로 "이런 이슈가 있다"를 검출하는 것으로 충분(사용자 결정).
  개별 매퍼 로드 실패는 건너뛰고 나머지 매퍼로 검증 진행(부분 검증 허용)
- 실전에서 필요 시 프로젝트별로 대응

### ✅ 특수 바인드 변수 선치환 — 완료 (오케스트레이터 Phase2 통합)
- oma/preprocess/special_variables.py 정식 모듈, Phase2 복사 직후 자동 치환
- PAGING_ROWNUM/sysdate + OGNL, XML 이스케이프 처리

### ✅ 변환 리포트/결과 파일 저장 — 완료 (오케스트레이터 Phase4)
- converted/{mapper}__{sqlId}.xml + .report.json(type_casts/warnings/analysis 등)
- reports/conversion-summary.json, testcases/*.json
- **연관**: type_casts 리포트가 저장되면, TypeCaster 후보정/검증 계층에서
  이 매핑을 재사용 가능 (LLM이 인식한 컬럼 한정)

### TypeCaster 후보정/검증 계층 (선택적, 현재 미연결)
- 현재 실제 변환의 캐스팅은 LLM이 담당. TypeCaster는 독립 결정론적 엔진으로만 존재
- 후보정 용도: LLM type_casts 리포트의 (bind_var→column) 매핑을 받아
  딕셔너리와 cross-check → 잘못된/누락된 캐스팅 교정
- 한계: LLM이 아예 인식 못 한 바인드 변수는 매핑이 없어 후보정 불가
  (SQL 파싱 없이는 매핑 생성 불가 = 하드 룰)

### 문서 정리
- [ ] 02-conversion-workflow.md 의 `oracle_dictionary.json` → `schema_dictionary.json`
      범용 이름으로 통일 (다른 문서와 일관성)
- [x] 멀티 프로젝트 지원: 작업 경로 projects/<APPLICATION_NAME> 구조로 변경
- [x] 전체 문서 경로 현행화 (app/ → projects/)
