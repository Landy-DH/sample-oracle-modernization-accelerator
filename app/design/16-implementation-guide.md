# OMA 구현 가이드 (Step-by-Step)

## 목적

AI 코딩(Opus 4.8)으로 OMA를 구현하기 위한 단계별 가이드

---

## 📋 전체 구현 순서 (20일)

```
Week 1 (Day 1-5): 기반 모듈
Week 2 (Day 6-10): 변환 모듈
Week 3 (Day 11-15): 검증 모듈
Week 4 (Day 16-20): 통합 및 테스트
```

---

## 🔗 의존성 그래프

```
레벨 0 (의존성 없음):
├─ oma/utils/config.py
└─ oma/utils/exceptions.py

레벨 1 (config에만 의존):
├─ oma/utils/secrets.py (config)
└─ oma/utils/logger.py (config)

레벨 2:
├─ oma/dictionary/builder.py (config, secrets)
├─ oma/dictionary/loader.py (config)
└─ oma/converter/llm_client.py (config)

레벨 3:
├─ oma/fragmenter/splitter.py (config)
├─ oma/converter/sql_analyzer.py (config)
└─ oma/converter/type_caster.py (config, dictionary.loader)

레벨 4:
├─ oma/testcase/generator.py (config, dictionary.loader)
├─ oma/merger/combiner.py (config)
└─ oma/workflow/checkpoint.py (config)

레벨 5:
└─ oma/validation/* (모든 기반 모듈)

레벨 6:
└─ oma/workflow/orchestrator.py (모든 모듈)

레벨 7:
└─ scripts/run_oma.py (orchestrator)
```

**구현 원칙**: 레벨 0부터 순차적으로 구현

---

## Week 1: 기반 모듈 (Day 1-5)

### Day 1: 프로젝트 초기화 및 Config

#### Step 1.1: 프로젝트 구조 생성 (30분)
```bash
mkdir -p oma/utils oma/dictionary oma/fragmenter oma/converter \
         oma/testcase oma/merger oma/validation oma/workflow \
         oma/plugins tests/unit tests/integration scripts

touch oma/__init__.py
touch oma/utils/__init__.py
# ... (모든 __init__.py 생성)
```

#### Step 1.2: requirements.txt (10분)
```bash
cat > requirements.txt << 'EOF'
anthropic>=0.18.0
boto3>=1.34.0
botocore>=1.34.0
psycopg2-binary>=2.9.9
cx-Oracle>=8.3.0
lxml>=5.0.0
pyyaml>=6.0.1
pytest>=7.4.0
pytest-cov>=4.1.0
black>=23.0.0
pylint>=3.0.0
mypy>=1.7.0
EOF

pip install -r requirements.txt
```

#### Step 1.3: oma/utils/exceptions.py (30분)
**참고**: `templates/exceptions.py`

**AI 프롬프트**:
```
templates/exceptions.py를 참고해서 oma/utils/exceptions.py를 구현해줘.

필수:
- OMAError (베이스 예외)
- ConfigError
- ConversionError
- ValidationError
- LLMError
- DatabaseError

완료 후:
- 파일 상단에 변경 이력 작성
```

**테스트**: 없음 (단순 클래스 정의)

**예상 시간**: 30분

---

#### Step 1.4: oma/utils/config.py (1시간)
**참고**: `templates/config.py`

**AI 프롬프트**:
```
templates/config.py를 참고해서 oma/utils/config.py를 구현해줘.

기능:
- oma.properties 로드
- get(key, default) 메서드
- 환경 변수 대체 (${VAR} → 환경 변수 값)
- 타입 변환 (int, bool, list)

완료 후:
- 파일 상단에 변경 이력 작성
- tests/unit/test_config.py 작성
```

**테스트**:
```python
def test_config_load():
    config = Config('oma.properties')
    assert config.get('SOURCE_DB_TYPE') == 'oracle'

def test_config_get_with_default():
    config = Config('oma.properties')
    assert config.get('NONEXISTENT', 'default') == 'default'

def test_config_int_conversion():
    config = Config('oma.properties')
    assert config.get('MAX_WORKERS') == 7
    assert isinstance(config.get('MAX_WORKERS'), int)
```

**예상 시간**: 1시간

---

#### Step 1.5: oma/utils/secrets.py (1.5시간)
**참고**: `templates/secrets.py`

**AI 프롬프트**:
```
templates/secrets.py를 참고해서 oma/utils/secrets.py를 구현해줘.

기능:
- get_secret(secret_name, region) → Dict
- boto3 Secrets Manager 연동
- 캐싱 (같은 시크릿 여러 번 조회하면 캐시에서)

완료 후:
- 파일 상단에 변경 이력 작성
- tests/unit/test_secrets.py 작성 (mock 사용)
```

**테스트**:
```python
from unittest.mock import Mock, patch

@patch('boto3.client')
def test_get_secret(mock_boto_client):
    mock_client = Mock()
    mock_client.get_secret_value.return_value = {
        'SecretString': '{"host": "localhost", "port": 5432}'
    }
    mock_boto_client.return_value = mock_client
    
    secret = get_secret('test-secret', 'us-east-1')
    
    assert secret['host'] == 'localhost'
    assert secret['port'] == 5432
```

**예상 시간**: 1.5시간

---

#### Step 1.6: oma/utils/logger.py (30분)
**참고**: `templates/logger.py`

**AI 프롬프트**:
```
templates/logger.py를 참고해서 oma/utils/logger.py를 구현해줘.

기능:
- setup_logger(name, config) → logger
- 콘솔 + 파일 핸들러
- 로그 레벨 설정 (config에서)

완료 후:
- 파일 상단에 변경 이력 작성
```

**예상 시간**: 30분

**Day 1 완료**: config, secrets, logger

---

### Day 2: Dictionary 모듈

#### Step 2.1: oma/dictionary/builder.py (3시간)
**참고**: `templates/dictionary_builder.py`, `01-migration-principles.md`

**AI 프롬프트**:
```
templates/dictionary_builder.py와 01-migration-principles.md를 참고해서
oma/dictionary/builder.py를 구현해줘.

기능:
- DictionaryBuilder 클래스
- build() → schema_dictionary.json 생성
- extract_metadata() → information_schema 조회
- collect_samples() → 테이블별 샘플 1건
- generate_cast_hints() → 타입별 캐스팅 힌트

의존성:
- oma/utils/config.py
- oma/utils/secrets.py
- psycopg2

완료 후:
- 파일 상단에 변경 이력 작성
- tests/unit/test_dictionary_builder.py 작성
```

**테스트**:
```python
def test_dictionary_builder_build():
    config = MockConfig()
    builder = DictionaryBuilder(config)
    dictionary = builder.build()
    
    # 딕셔너리 구조 확인
    assert 'users.user_id' in dictionary
    assert dictionary['users.user_id']['data_type'] == 'integer'
    assert 'sample_value' in dictionary['users.user_id']
```

**예상 시간**: 3시간 (DB 연동 포함)

---

#### Step 2.2: oma/dictionary/loader.py (1시간)
**참고**: `templates/dictionary_loader.py`

**AI 프롬프트**:
```
templates/dictionary_loader.py를 참고해서 oma/dictionary/loader.py를 구현해줘.

기능:
- DictionaryLoader 클래스
- load(file_path) → Dict
- lookup(table_column) → Dict or None
- 캐싱

완료 후:
- 파일 상단에 변경 이력 작성
- tests/unit/test_dictionary_loader.py 작성
```

**예상 시간**: 1시간

**Day 2 완료**: dictionary

---

### Day 3: Fragmenter 모듈

#### Step 3.1: oma/fragmenter/splitter.py (4시간)
**참고**: `templates/fragmenter_splitter.py`, `02-conversion-workflow.md`

**AI 프롬프트**:
```
templates/fragmenter_splitter.py와 02-conversion-workflow.md를 참고해서
oma/fragmenter/splitter.py를 구현해줘.

기능:
- MapperSplitter 클래스
- split(mapper_file) → List[Fragment]
- lxml.etree로 XML 파싱 (정규식 금지!)
- SQL ID별 분할
- mapping.json 생성 (조각 → 원본 매핑)

완료 후:
- 파일 상단에 변경 이력 작성
- tests/unit/test_fragmenter.py 작성
```

**테스트**:
```python
def test_split_mapper():
    splitter = MapperSplitter(config)
    fragments = splitter.split('UserMapper.xml')
    
    assert len(fragments) > 0
    assert fragments[0].mapper_name == 'UserMapper'
    assert fragments[0].sql_id == 'getUser'
    assert '<select id="getUser"' in fragments[0].content
```

**예상 시간**: 4시간

**Day 3 완료**: fragmenter

---

### Day 4-5: LLM Client 및 분석기

#### Step 4.1: oma/converter/llm_client.py (5시간)
**참고**: `templates/llm_client.py`, `13-error-handling-restart.md`

**AI 프롬프트**:
```
templates/llm_client.py와 13-error-handling-restart.md를 참고해서
oma/converter/llm_client.py를 구현해줘.

기능:
- LLMClient 클래스
- call_llm(prompt, retry_count) → Dict
- Rate limit 준수 (RPM 50)
- Exponential backoff 재시도
- Timeout 처리

의존성:
- boto3 bedrock-runtime
- anthropic SDK

완료 후:
- 파일 상단에 변경 이력 작성
- tests/unit/test_llm_client.py 작성 (mock)
```

**예상 시간**: 5시간

---

#### Step 4.2: oma/converter/sql_analyzer.py (2시간)
**참고**: `templates/sql_analyzer.py`, `14-large-sql-handling.md`

**AI 프롬프트**:
```
templates/sql_analyzer.py와 14-large-sql-handling.md를 참고해서
oma/converter/sql_analyzer.py를 구현해줘.

기능:
- SqlAnalyzer 클래스
- analyze(sql) → {char_count, token_estimate, is_large, complexity}
- classify_complexity(score) → 'simple' | 'moderate' | 'complex' | 'very_complex'
- select_conversion_strategy() → 'standard' | 'chunked' | 'manual_review'

완료 후:
- 파일 상단에 변경 이력 작성
- tests/unit/test_sql_analyzer.py 작성
```

**예상 시간**: 2시간

**Week 1 완료**: 기반 모듈 (config, secrets, dictionary, fragmenter, llm_client, sql_analyzer)

---

## Week 2: 변환 모듈 (Day 6-10)

### Day 6: Type Caster

#### Step 6.1: oma/converter/type_caster.py (4시간)
**참고**: `templates/type_caster.py`, `03-type-casting-strategy.md`

**AI 프롬프트**:
```
templates/type_caster.py와 03-type-casting-strategy.md를 참고해서
oma/converter/type_caster.py를 구현해줘.

기능:
- TypeCaster 클래스
- apply(sql, dictionary) → 변환된 SQL
- #{userId}::INTEGER 같은 캐스팅 적용
- 리터럴 변환 ('123' → 123)
- CHAR(1) TRIM 처리

정규식 사용 금지! (단순 패턴 감지만 허용)

완료 후:
- 파일 상단에 변경 이력 작성
- tests/unit/test_type_caster.py 작성
```

**예상 시간**: 4시간

---

### Day 7: Test Case Generator

#### Step 7.1: oma/testcase/generator.py (5시간)
**참고**: `templates/testcase_generator.py`, `04-test-case-generation.md`

**AI 프롬프트**:
```
templates/testcase_generator.py와 04-test-case-generation.md를 참고해서
oma/testcase/generator.py를 구현해줘.

기능:
- TestCaseGenerator 클래스
- generate(fragment, dictionary) → List[TestCase]
- 브랜치 커버리지 (<if>, <choose>)
- 엣지 케이스 (NULL, 0, -1 등)
- 파일명: {mapper}_{sqlId}_tc{num}.json

완료 후:
- 파일 상단에 변경 이력 작성
- tests/unit/test_testcase_generator.py 작성
```

**예상 시간**: 5시간

---

### Day 8: Converter (통합)

#### Step 8.1: oma/converter/converter.py (5시간)
**참고**: `templates/converter.py`, `05-conversion-prompt.md`

**AI 프롬프트**:
```
templates/converter.py와 05-conversion-prompt.md를 참고해서
oma/converter/converter.py를 구현해줘.

기능:
- Converter 클래스
- convert(fragment, dictionary) → ConversionResult
- LLMClient + SqlAnalyzer + TypeCaster 통합
- 대용량 SQL 처리 (청킹)
- 변환 결과 검증

의존성:
- llm_client
- sql_analyzer
- type_caster
- testcase/generator

완료 후:
- 파일 상단에 변경 이력 작성
- tests/integration/test_converter.py 작성
```

**예상 시간**: 5시간

---

### Day 9: Merger

#### Step 9.1: oma/merger/combiner.py (3시간)
**참고**: `templates/merger_combiner.py`, `02-conversion-workflow.md`

**AI 프롬프트**:
```
templates/merger_combiner.py와 02-conversion-workflow.md를 참고해서
oma/merger/combiner.py를 구현해줘.

기능:
- MapperCombiner 클래스
- merge(fragments, mapping) → 완전한 매퍼 XML
- lxml.etree로 재조립 (정규식 금지!)

완료 후:
- 파일 상단에 변경 이력 작성
- tests/unit/test_merger.py 작성
```

**예상 시간**: 3시간

---

### Day 10: Checkpoint

#### Step 10.1: oma/workflow/checkpoint.py (3시간)
**참고**: `templates/checkpoint.py`, `13-error-handling-restart.md`

**AI 프롬프트**:
```
templates/checkpoint.py와 13-error-handling-restart.md를 참고해서
oma/workflow/checkpoint.py를 구현해줘.

기능:
- CheckpointManager 클래스
- .checkpoint.json 관리
- mark_phase_started/completed()
- mark_fragment_completed/failed()
- is_completed(), get_pending_fragments()

완료 후:
- 파일 상단에 변경 이력 작성
- tests/unit/test_checkpoint.py 작성
```

**예상 시간**: 3시간

**Week 2 완료**: 변환 모듈 (type_caster, testcase_generator, converter, merger, checkpoint)

---

## Week 3: 검증 모듈 (Day 11-15)

### Day 11-12: Java Validator

#### Step 11.1: java-validator/pom.xml (30분)
**참고**: `templates/pom.xml`

#### Step 11.2: ValidationService.java (4시간)
**참고**: `templates/ValidationService.java`, `10-validation-design.md`

**AI 프롬프트**:
```
templates/ValidationService.java와 10-validation-design.md를 참고해서
ValidationService.java를 구현해줘.

기능:
- validateTestCase(TestCase) → ValidationResult
- SqlSessionFactory 초기화
- 소스 DB, 타겟 DB 실행
- JSON 입출력 (stdin/stdout)

완료 후:
- 파일 상단에 변경 이력 작성
```

**예상 시간**: 4시간

---

#### Step 11.3: SqlExtractor.java (3시간)
**참고**: `templates/SqlExtractor.java`, `10-validation-design.md`

**AI 프롬프트**:
```
templates/SqlExtractor.java와 10-validation-design.md를 참고해서
SqlExtractor.java를 구현해줘.

핵심:
- BoundSql boundSql = ms.getBoundSql(parameters);
- 동적 SQL 자동 처리

완료 후:
- 파일 상단에 변경 이력 작성
```

**예상 시간**: 3시간

---

#### Step 11.4: DatabaseExecutor.java (4시간)
**참고**: `templates/DatabaseExecutor.java`, `10-validation-design.md`, `14-large-sql-handling.md`

**AI 프롬프트**:
```
templates/DatabaseExecutor.java를 참고해서 DatabaseExecutor.java를 구현해줘.

기능:
- execute(ExtractedSql) → ExecutionResult
- DML 트랜잭션 롤백
- 프로시저 스킵
- 대용량 결과셋 샘플링 (10,000 행 이상)

완료 후:
- 파일 상단에 변경 이력 작성
```

**예상 시간**: 4시간

---

### Day 13: Python Validation Bridge

#### Step 13.1: oma/validation/java_bridge.py (3시간)
**참고**: `templates/java_bridge.py`, `10-validation-design.md`

**AI 프롬프트**:
```
templates/java_bridge.py와 10-validation-design.md를 참고해서
oma/validation/java_bridge.py를 구현해줘.

기능:
- JavaValidationBridge 클래스
- validate_test_case(tc) → result
- subprocess로 Java JAR 실행
- stdin/stdout JSON 통신
- validate_batch() 병렬 처리

완료 후:
- 파일 상단에 변경 이력 작성
- tests/unit/test_java_bridge.py 작성 (mock)
```

**예상 시간**: 3시간

---

### Day 14: Comparator & Reporter

#### Step 14.1: oma/validation/comparator.py (3시간)
**참고**: `templates/comparator.py`, `10-validation-design.md`

**AI 프롬프트**:
```
templates/comparator.py를 참고해서 oma/validation/comparator.py를 구현해줘.

기능:
- ResultComparator 클래스
- compare(source_result, target_result) → comparison
- 행 수, 컬럼, 값 비교
- 샘플링 결과 비교 (대용량)
- Tolerance 고려 (0.001)

완료 후:
- 파일 상단에 변경 이력 작성
- tests/unit/test_comparator.py 작성
```

**예상 시간**: 3시간

---

#### Step 14.2: oma/validation/reporter.py (4시간)
**참고**: `templates/reporter.py`, `11-validation-report-format.md`

**AI 프롬프트**:
```
templates/reporter.py와 11-validation-report-format.md를 참고해서
oma/validation/reporter.py를 구현해줘.

기능:
- ValidationReporter 클래스
- generate_all_reports(results)
- 콘솔, JSON, CSV, HTML 생성

완료 후:
- 파일 상단에 변경 이력 작성
```

**예상 시간**: 4시간

---

### Day 15: Validation Orchestrator

#### Step 15.1: oma/validation/orchestrator.py (4시간)
**참고**: `templates/validation_orchestrator.py`, `10-validation-design.md`

**AI 프롬프트**:
```
templates/validation_orchestrator.py를 참고해서
oma/validation/orchestrator.py를 구현해줘.

기능:
- ValidationOrchestrator 클래스
- validate_all(work_dir) → results
- TC 로드 → Java 호출 → 비교 → 리포트

의존성:
- java_bridge
- comparator
- reporter

완료 후:
- 파일 상단에 변경 이력 작성
- tests/integration/test_validation.py 작성
```

**예상 시간**: 4시간

**Week 3 완료**: 검증 모듈 (Java + Python)

---

## Week 4: 통합 및 테스트 (Day 16-20)

### Day 16-17: Workflow Orchestrator

#### Step 16.1: oma/workflow/orchestrator.py (8시간)
**참고**: `templates/workflow_orchestrator.py`, `02-conversion-workflow.md`

**AI 프롬프트**:
```
templates/workflow_orchestrator.py와 02-conversion-workflow.md를 참고해서
oma/workflow/orchestrator.py를 구현해줘.

기능:
- WorkflowOrchestrator 클래스
- run(config) → Phase 1-7 실행
- 체크포인트 통합
- 에러 처리 및 재시도

의존성: 모든 모듈

완료 후:
- 파일 상단에 변경 이력 작성
- tests/integration/test_workflow.py 작성
```

**예상 시간**: 8시간

---

### Day 18: Main Script

#### Step 18.1: scripts/run_oma.py (3시간)
**참고**: `templates/run_oma.py`

**AI 프롬프트**:
```
templates/run_oma.py를 참고해서 scripts/run_oma.py를 구현해줘.

기능:
- argparse로 CLI
- --phase 옵션 (dictionary, all 등)
- --retry-failed 옵션
- WorkflowOrchestrator 호출

완료 후:
- 파일 상단에 변경 이력 작성
```

**예상 시간**: 3시간

---

### Day 19: PoC 테스트

#### Step 19.1: 샘플 매퍼 준비 (1시간)
- 간단한 매퍼 10개
- 다양한 케이스 (동적 SQL, JOIN 등)

#### Step 19.2: End-to-End 테스트 (5시간)
```bash
# Phase 1: Dictionary
python scripts/run_oma.py --phase dictionary

# Phase 2-7: 전체 실행
python scripts/run_oma.py --phase all

# 결과 확인
cat reports/validation-summary.json
```

**예상 시간**: 6시간

---

### Day 20: 문서화 및 정리

#### Step 20.1: 각 파일 변경 이력 검토 (2시간)
- 모든 파일 상단 변경 이력 확인
- 누락된 이력 추가

#### Step 20.2: README.md 업데이트 (2시간)
- "빠른 시작" 섹션 추가
- 실제 사용 예시 추가

#### Step 20.3: 최종 테스트 (2시간)
- 전체 테스트 실행
- 커버리지 측정 (80% 목표)

**예상 시간**: 6시간

**Week 4 완료**: 통합 및 테스트

---

## 🎯 AI 프롬프트 템플릿

### 신규 모듈 구현 시
```
[필수 읽기]
1. README.md의 "{모듈명}" 섹션
2. 15-coding-guidelines.md
3. templates/{파일명}.py

[구현]
templates/{파일명}.py를 참고해서 oma/{경로}/{파일명}.py를 구현해줘.

기능:
- {주요 기능 1}
- {주요 기능 2}
- {주요 기능 3}

의존성:
- {의존 모듈 1}
- {의존 모듈 2}

필수 준수:
- 파일 최상단에 변경 이력 작성 (초기 생성 기록)
- 정규식으로 SQL/XML 파싱 금지
- 타입 힌트 필수
- Docstring 필수
- 500 lines 이하

완료 후:
- tests/unit/test_{파일명}.py 작성
- pytest로 테스트 실행
```

### 버그 수정 시
```
[필수 읽기]
1. {파일명} 상단의 변경 이력
2. 15-coding-guidelines.md

[수정]
{파일명}에서 {버그 설명}을 수정해줘.

완료 후:
- 파일 상단 변경 이력 업데이트
  - 원인: {왜 버그 발생했는지}
  - 수정: {무엇을 바꿨는지}
  - 영향: {다른 부분 영향 있는지}
```

---

## 📊 진행 상황 추적

### Checklist

**Week 1: 기반 모듈**
- [ ] Day 1: config, secrets, logger
- [ ] Day 2: dictionary (builder, loader)
- [ ] Day 3: fragmenter
- [ ] Day 4-5: llm_client, sql_analyzer

**Week 2: 변환 모듈**
- [ ] Day 6: type_caster
- [ ] Day 7: testcase_generator
- [ ] Day 8: converter (통합)
- [ ] Day 9: merger
- [ ] Day 10: checkpoint

**Week 3: 검증 모듈**
- [ ] Day 11-12: Java (ValidationService, SqlExtractor, DatabaseExecutor)
- [ ] Day 13: java_bridge
- [ ] Day 14: comparator, reporter
- [ ] Day 15: validation orchestrator

**Week 4: 통합**
- [ ] Day 16-17: workflow orchestrator
- [ ] Day 18: run_oma.py
- [ ] Day 19: PoC 테스트
- [ ] Day 20: 문서화 및 정리

---

## ⚠️ 주의사항

### 1. 순서 절대 지키기
- 의존성 그래프 순서대로 구현
- 예: dictionary_loader 전에 config 필요

### 2. 각 단계별 테스트
- 모듈 완성 후 바로 테스트
- 다음 모듈로 넘어가기 전 검증

### 3. 파일별 변경 이력 필수
- 모든 파일 상단에 작성
- 초기 생성, 버그 수정, 기능 추가 모두 기록

### 4. 정규식/sed 절대 사용 금지
- SQL/XML은 lxml.etree
- 단순 패턴 감지만 허용

### 5. 500 lines 초과 시 분할
- 한 파일이 너무 길면 즉시 분할

---

## 문서 버전
- 버전: 1.0
- 작성일: 2026-07-27
- 목적: Step-by-step 구현 가이드
