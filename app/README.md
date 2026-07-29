# OMA (Oracle Migration Assistant)

Oracle/EDB/Tibero MyBatis 매퍼를 PostgreSQL/MySQL로 자동 변환하는 도구

---

## 🚀 빠른 시작 (Quick Start)

### 사전 준비 (필수!)

#### 1. 환경 점검
```bash
# 환경 점검 스크립트 실행
cd oma
chmod +x check_environment.sh
./check_environment.sh

# 모두 ✓ 나와야 함
# Python 3.11, Java 11+, Maven, AWS CLI
```

#### 2. Python 3.11 설정
```bash
# python3 → Python 3.11 링크 설정
chmod +x setup_python311.sh
./setup_python311.sh

# 확인
python3 --version  # Python 3.11.x 출력되어야 함
```

#### 3. 매퍼 파일 사전 점검
```bash
# OGNL 표현식 및 ${} 변수 검색
python3 check_mappers.py /path/to/source/workspace

# mapper-precheck-report.json 생성됨
# ⚠️ 경고 있으면 대응 계획 수립
```

**참고**: `design/18-environment-setup.md` - 환경 구성 상세 가이드

---

### Opus 4.8 Vibe 코딩으로 구현하기

#### 1. 문서 읽기 순서
```
필수 읽기:
1. CLAUDE.md - 필수 규칙 (자동 로드)
2. README.md - 이 파일 (전체 구조)
3. design/16-implementation-guide.md - Step-by-step 가이드
4. design/17-decision-log.md - 의사결정 근거

참고:
- design/15-coding-guidelines.md - 상세 코딩 규칙
- templates/ - 코드 스켈레톤
```

#### 2. 첫 번째 AI 프롬프트
```
[Day 1 시작]

README.md와 design/16-implementation-guide.md를 읽고
Week 1 Day 1을 시작해줘.

Step 1.1부터 시작:
1. 프로젝트 구조 생성
2. requirements.txt 작성
3. oma/utils/exceptions.py 구현 (templates/exceptions.py 참고)
4. oma/utils/config.py 구현 (templates/config.py 참고)

완료 후:
- 각 파일 상단에 변경 이력 작성
- 테스트 실행
```

#### 3. 진행 추적
- `design/16-implementation-guide.md`의 체크리스트 사용
- 각 Day 완료 시 체크
- Week 단위로 점검

#### 4. 막힐 때
- `design/17-decision-log.md`에서 "왜 이렇게 했는지" 확인
- 관련 설계 문서 (01-15번) 참고
- templates/ 디렉토리의 스켈레톤 참고

---

## 📚 설계 문서

| 번호 | 파일 | 목적 |
|------|------|------|
| 00 | `design/00-REVIEW.md` | 전체 설계 검토 및 평가 |
| 01 | `design/01-migration-principles.md` | 기본 원칙 및 아키텍처 |
| 02 | `design/02-conversion-workflow.md` | 7단계 변환 워크플로우 |
| 03 | `design/03-type-casting-strategy.md` | PostgreSQL 타입 캐스팅 전략 |
| 04 | `design/04-test-case-generation.md` | 동적 SQL 테스트 케이스 생성 |
| 05 | `design/05-conversion-prompt.md` | LLM 변환 프롬프트 템플릿 |
| 06 | `design/06-architecture-design.md` | 시스템 아키텍처 |
| 07 | `design/07-configuration-guide.md` | 설정 가이드 |
| 08 | `design/08-binding-failure-tracking.md` | 바인드 변수 매핑 실패 추적 |
| 09 | `design/09-file-locations.md` | 파일 저장 위치 |
| 10 | `design/10-validation-design.md` | SqlSessionFactory 기반 검증 |
| 11 | `design/11-validation-report-format.md` | 검증 결과 리포트 |
| 13 | `design/13-error-handling-restart.md` | 에러 처리 및 재시작 |
| 14 | `design/14-large-sql-handling.md` | 대용량 SQL 및 결과셋 처리 |
| 15 | `design/15-coding-guidelines.md` | 코딩 가이드라인 (필수) |
| 20 | `design/20-iterative-repair-loop.md` | 오류유형 기반 반복 수정 루프 |

---

## 📁 디렉토리 구조

```
oma/
├─ 설계 문서
│   ├─ design/00-REVIEW.md
│   ├─ 01-15-*.md
│   ├─ CLAUDE.md              # AI 코딩 필수 규칙 (자동 로드)
│   ├─ README.md              # 이 파일
│   └─ oma.properties         # 설정 파일
│
├─ Python 패키지 (utils 구현 완료, 나머지 구현 예정)
│   └─ oma/
│       ├─ dictionary/        # 스키마 딕셔너리
│       │   ├─ builder.py     # 딕셔너리 생성
│       │   └─ loader.py      # 딕셔너리 로드
│       │
│       ├─ fragmenter/        # 매퍼 분할
│       │   └─ splitter.py    # XML → SQL ID별 조각
│       │
│       ├─ converter/         # SQL 변환
│       │   ├─ llm_client.py  # LLM API 호출 (Rate Limit 처리)
│       │   ├─ type_caster.py # 타입 캐스팅 적용
│       │   └─ sql_analyzer.py # SQL 크기/복잡도 분석
│       │
│       ├─ testcase/          # TC 생성
│       │   └─ generator.py   # 동적 SQL TC 생성
│       │
│       ├─ merger/            # 매퍼 병합
│       │   └─ combiner.py    # 조각 → 완전한 매퍼
│       │
│       ├─ validation/        # 검증
│       │   ├─ orchestrator.py # 검증 오케스트레이터
│       │   ├─ java_bridge.py  # Java 통신
│       │   ├─ comparator.py   # 결과 비교
│       │   └─ reporter.py     # 리포트 생성
│       │
│       ├─ workflow/          # 워크플로우
│       │   ├─ checkpoint.py  # 체크포인트 관리
│       │   └─ orchestrator.py # 전체 플로우 제어
│       │
│       ├─ utils/             # 유틸리티 (구현 완료)
│       │   ├─ config.py      # 설정 로더 (${VAR} 치환, 타입 변환)
│       │   ├─ secrets.py     # AWS Secrets Manager (캐싱)
│       │   ├─ logger.py      # 로깅 설정 (콘솔 + 파일)
│       │   └─ exceptions.py  # 공용 예외 계층 (OMAError 등)
│       │
│       └─ plugins/           # DB 플러그인
│           ├─ source_oracle.py    # Oracle 소스
│           ├─ source_edb.py       # EDB 소스
│           ├─ source_tibero.py    # Tibero 소스
│           ├─ target_postgres.py  # PostgreSQL 타겟
│           └─ target_mysql.py     # MySQL 타겟
│
├─ Java 검증 모듈 (미구현)
│   └─ java-validator/
│       ├─ pom.xml
│       └─ src/main/java/com/oma/validator/
│           ├─ ValidationService.java  # 메인 검증 서비스
│           ├─ SqlExtractor.java      # MyBatis BoundSql 사용
│           ├─ DatabaseExecutor.java  # DB 실행 (DML 롤백)
│           └─ model/
│               ├─ TestCase.java
│               ├─ ValidationResult.java
│               └─ ExecutionResult.java
│
├─ 테스트 (utils 테스트 구현 완료)
│   └─ tests/
│       ├─ unit/              # 단위 테스트 (test_config/secrets/logger)
│       └─ integration/       # 통합 테스트 (구현 예정)
│
└─ 스크립트 (미구현)
    └─ scripts/
        ├─ build_java_validator.sh
        └─ run_oma.py         # 메인 실행 스크립트
```

### 작업 디렉토리 구조 (프로젝트별)

코드 모듈(위)은 **모든 프로젝트가 공유**한다. 반면 실행 중 생성되는
작업/산출물은 `OMA_BASE_DIR/projects/<APPLICATION_NAME>/` 아래에 격리되어,
여러 프로젝트를 동시에 처리해도 서로 섞이지 않는다.

```
${OMA_BASE_DIR}/projects/
├─ <APPLICATION_NAME>/            # 예: oma (oma.properties의 APPLICATION_NAME)
│   ├─ mappers/                   # MAPPER_WORK_DIR
│   │   ├─ original/              # SOURCE_WORKSPACE에서 복사한 원본
│   │   ├─ fragmented/            # SQL ID별 분할 조각 + mapping.json
│   │   ├─ converted/             # 변환된 조각
│   │   └─ merged/                # 재조립된 완성 매퍼
│   ├─ output/                    # schema_dictionary.json (SCHEMA_DICT_PATH)
│   ├─ testcases/                 # TESTCASE_DIR (동적 SQL TC)
│   ├─ reports/                   # REPORT_DIR (검증/바인딩 리포트)
│   └─ .checkpoint.json           # CHECKPOINT_PATH (재시작 지점)
│
└─ <다른 프로젝트>/               # 예: shop — 동일 구조로 격리
    └─ ...
```

**생성 시점**: 이 폴더들은 미리 만들지 않는다. 각 모듈이 실행될 때
`os.makedirs(exist_ok=True)`로 자동 생성한다.

---

## 🎯 핵심 모듈 설명

### 1. Dictionary (oma/dictionary/)
- **builder.py**: PostgreSQL 메타데이터 추출 → JSON 생성
- **loader.py**: 딕셔너리 파일 로드 및 조회

**목적**: 모든 테이블.컬럼의 타입 정보 제공 → LLM이 정확한 캐스팅 판단

---

### 2. Fragmenter (oma/fragmenter/)
- **splitter.py**: MyBatis XML을 SQL ID별로 분할

**목적**: 대용량 매퍼를 작은 조각으로 나눔 → 병렬 처리

---

### 3. Converter (oma/converter/)
- **llm_client.py**: AWS Bedrock Claude API 호출
  - Rate Limit 준수 (RPM 50)
  - Exponential backoff 재시도
  - Timeout 처리

- **type_caster.py**: `#{userId}::INTEGER` 같은 타입 캐스팅 적용
  - 딕셔너리 기반 정확한 캐스팅
  - 리터럴 변환 ('123' → 123)

- **sql_analyzer.py**: SQL 크기/복잡도 분석
  - 50,000자 이상 → 청킹 전략
  - 복잡도 계산 (JOIN, <if> 개수)

**목적**: Oracle SQL → PostgreSQL 변환

---

### 4. TestCase (oma/testcase/)
- **generator.py**: 동적 SQL 테스트 케이스 생성
  - 브랜치 커버리지 (<if>, <choose>)
  - 엣지 케이스 (NULL, 0, -1, 최소/최대값)

**목적**: 검증 시 사용할 TC 자동 생성

---

### 5. Merger (oma/merger/)
- **combiner.py**: 분할된 조각 → 완전한 매퍼 재조립

**목적**: Phase 4 변환 결과를 원래 구조로 병합

---

### 6. Validation (oma/validation/)
- **orchestrator.py**: 검증 전체 플로우 제어
  - TC 로드
  - Java 호출
  - 결과 비교
  - 리포트 생성

- **java_bridge.py**: Python ↔ Java 통신 (JSON)
  - subprocess로 Java JAR 실행
  - stdin/stdout으로 JSON 통신

- **comparator.py**: 소스 DB vs 타겟 DB 결과 비교
  - 행 수 비교
  - 컬럼 비교
  - 값 비교 (tolerance 고려)
  - 대용량 결과셋 샘플링

- **reporter.py**: 리포트 생성
  - 콘솔, JSON, CSV, HTML

**목적**: 변환된 SQL이 정확한지 검증

---

### 7. Workflow (oma/workflow/)
- **checkpoint.py**: 중단 시 재시작 지원
  - `.checkpoint.json` 관리
  - Phase별 진행 상황 저장

- **orchestrator.py**: Phase 1-7 전체 제어
  - Dictionary → Fragment → Convert → Merge → Validate

**목적**: 전체 변환 플로우 오케스트레이션

---

### 8. Utils (oma/utils/)
- **config.py**: oma.properties 로드 및 파싱
- **secrets.py**: AWS Secrets Manager 통합

**목적**: 설정 및 자격증명 관리

---

### 9. Plugins (oma/plugins/)
- **source_*.py**: 소스 DB 연결 및 메타데이터 추출
- **target_*.py**: 타겟 DB 연결 및 딕셔너리 생성

**목적**: Multi-DB 지원 (Oracle/EDB/Tibero → PostgreSQL/MySQL)

---

### 10. Java Validator (java-validator/)
- **ValidationService.java**: MyBatis SqlSessionFactory 사용
  - `BoundSql boundSql = ms.getBoundSql(parameters)` ← 핵심!
  - 동적 SQL 완벽 처리

- **DatabaseExecutor.java**: DB 실행
  - DML은 트랜잭션 롤백
  - 프로시저는 스킵
  - 대용량 결과셋 샘플링 (10,000 행 이상)

**목적**: 정확한 SQL 추출 및 실행

---

## 🚀 실행 흐름

### Phase 1: Dictionary 생성
```bash
python scripts/run_oma.py --phase dictionary
```
→ PostgreSQL 메타데이터 추출 → `schema_dictionary.json`

### Phase 2: 매퍼 복사
→ SOURCE_WORKSPACE → MAPPER_WORK_DIR/original/

### Phase 3: Fragment
→ 매퍼 500개 → SQL ID별 5,000 조각

### Phase 4: Conversion (가장 오래 걸림)
→ LLM API 호출 → 타입 캐스팅 → TC 생성

### Phase 5: Merge
→ 5,000 조각 → 500 매퍼

### Phase 6: Validation
→ TC 실행 → 결과 비교 → 리포트

### Phase 7: Copy
→ MAPPER_WORK_DIR/merged/ → TARGET_WORKSPACE

---

## ⏱️ 예상 소요 시간

| 매퍼 수 | Phase 1-3 | Phase 4 (변환) | Phase 5-7 | 합계 |
|---------|-----------|----------------|-----------|------|
| 100 | 10분 | 30-60분 | 15분 | **1-2시간** |
| 500 | 20분 | 3-6시간 | 40분 | **4-8시간** |
| 1000 | 40분 | 6-12시간 | 1.5시간 | **8-16시간** |

---

## 💰 예상 비용 (Claude Opus 4.8 기준)

| 매퍼 수 | 입력 토큰 | 출력 토큰 | 비용 |
|---------|----------|----------|------|
| 100 | 2M | 3M | ~$255 |
| 500 | 10M | 15M | ~$1,275 |
| 1000 | 20M | 30M | ~$2,550 |

---

## 🛠️ 개발 환경

### Python
- Python 3.11 권장 (테스트는 `python3.11 -m pytest`로 실행)
- `requirements.txt`:
  - anthropic>=0.18.0
  - boto3>=1.34.0
  - psycopg2-binary>=2.9.9
  - cx-Oracle>=8.3.0
  - lxml>=5.0.0

### Java
- Java 11+
- Maven 3.6+
- MyBatis 3.5.13
- HikariCP 5.0.1

---

## 📝 코딩 규칙

**필수**: 작업 전 반드시 읽어라
- `CLAUDE.md` - 필수 규칙 (자동 로드)
- `design/15-coding-guidelines.md` - 상세 가이드

**핵심 규칙**:
1. 파일 상단에 변경 이력 작성
2. 정규식으로 SQL/XML 파싱 금지
3. sed 절대 금지
4. 타입 힌트 필수
5. 500 lines 이하

---

## 🔒 보안

- AWS Secrets Manager 사용
- 자격증명 하드코딩 금지
- 로그에 민감 정보 마스킹

---

## 📊 테스트

- 단위 테스트 커버리지: 80% 이상
- 통합 테스트: 주요 플로우 100%
- `pytest` 사용

---

## 📞 지원

- Issues: 버그 리포트 및 기능 요청
- 문서: `00-15-*.md` 참고

---

## 📄 라이선스

[라이선스 정보]

---

**버전**: 1.0.0  
**상태**: 구현 진행 중 (Week 1 Day 1 완료 — utils 모듈)  
**최종 업데이트**: 2026-07-27
