---
name: oma-convert
description: OMA 앱 변환 파이프라인을 대화형으로 실행한다. Oracle/EPAS MyBatis 매퍼를 PostgreSQL/MySQL로 변환·검증한다. 사용자가 "매퍼 변환", "OMA 실행", "앱 변환", "convert mappers", "매퍼 검증"을 요청하거나 변환 파이프라인의 특정 Phase(딕셔너리/분할/변환/병합/검증)를 돌리려 할 때 사용한다.
when_to_use: "예: 'OMA로 매퍼 변환해줘', '사전점검 돌려줘', 'wms 프로젝트 변환 시작', '검증만 다시 실행'"
argument-hint: "[preflight|all|phase이름] (생략 시 상태 확인 후 안내)"
disable-model-invocation: false
---

# OMA 앱 변환 (대화형)

OMA 변환 파이프라인을 단계별로 안내하며 실행한다. 각 단계에서 문제가 발견되면
바로 사용자와 상의해 해결한 뒤 다음으로 넘어간다. 전량 자동 실행이 아니라
**사람이 판단할 지점에서 멈추는** 것이 이 스킬의 핵심이다.

실행 엔진은 `scripts/run_oma.py`(CLI)이며, 이 스킬은 그 위에서 안내·판단을 담당한다.

## 현재 설정

- 설정 파일: `oma.properties`
- 프로젝트: !`grep -E "^APPLICATION_NAME" oma.properties 2>/dev/null || grep -A1 "\[oma\]" oma.properties`
- 소스/타겟 DB: !`grep -E "^SOURCE_DB_TYPE|^TARGET_DB_TYPE" oma.properties`
- 소스 워크스페이스: !`grep -E "^SOURCE_WORKSPACE" oma.properties`
- 체크포인트 진행: !`python3.11 -c "import json,glob; f=glob.glob('projects/*/.checkpoint.json'); print(json.load(open(f[0]))['progress'] if f else '(아직 실행 안 함)')" 2>/dev/null || echo "(체크포인트 없음)"`

## 파이프라인 Phase (순서)

| Phase | 별칭 | 하는 일 |
|-------|------|---------|
| 0 | `--preflight` | 사전점검: OGNL/${}변수/미지별칭/파싱오류 검출 + 조치 가이드 생성 |
| 1 | `dictionary` | 타겟 스키마 딕셔너리 생성 (admin 계정) |
| 2 | `copy` | 소스 매퍼 복사 + 특수변수/OGNL 선치환 |
| 3 | `fragment` | 매퍼를 SQL ID별 조각으로 분할 |
| 4 | `convert` | LLM(Bedrock) 변환 + 리포트/TC 생성 |
| 5 | `merge` | 변환 조각을 원본 구조로 재조립 |
| 6 | `validate` | 소스/타겟 실행 결과 비교 검증 (service 계정) |
| 7 | `copy_target` | 변환 결과를 타겟 출력 디렉토리로 복사 |

## 진행 방식 (반드시 이 순서로 안내)

### 1단계: 사전점검 먼저 (필수)
```
python3.11 scripts/run_oma.py --preflight
```
- 실행 후 `projects/<app>/reports/preflight-guide.md` 와 `preflight-config-stubs.json`
  을 **읽어서 사용자에게 요약**한다.
- **여기서 멈추고 판단**: OGNL/${}변수/미지별칭이 검출되면, 가이드 내용을 근거로
  사용자에게 "이건 이렇게 반영해야 한다"를 설명하고 필요한 설정을 함께 채운다.
  - 특수변수(${}) → `scripts/special_variables.json` 의 variables 채우기
  - OGNL → 실전이면 classpath 등록 안내, 테스트면 ognl_methods 매핑
  - 파싱오류 → 해당 매퍼 수동 수정 안내
- 사용자가 "계속"하면 다음 단계로.

### 2단계: 딕셔너리 (타겟 DB 접속 필요)
```
python3.11 scripts/run_oma.py --phase dictionary
```
- 생성된 컬럼 수를 확인해 사용자에게 보고. 0개면 접속/스키마 설정 문제이니 멈추고 진단.

### 3단계: 변환 파이프라인 (분할→변환→병합)
```
python3.11 scripts/run_oma.py --phase copy,fragment,convert,merge
```
- convert는 실제 Bedrock 호출이라 조각 수 × 수 초~수십 초 걸린다. 대량이면 사용자에게
  예상 시간을 먼저 알린다.
- `reports/conversion-summary.json`으로 success/failed/skipped 보고.
- failed/skipped가 있으면 해당 `converted/*.report.json`의 warning을 읽어 원인 설명.

### 4단계: 검증
```
python3.11 scripts/run_oma.py --phase validate
```
- **Java Validator JAR이 필요**하다. 없으면 먼저 빌드 안내:
  `mvn -f java-validator/pom.xml clean package -DskipTests`
- `reports/validation-summary.json`으로 통과율 보고.
- 실패가 있으면 `validation-details.json`의 note를 유형별로 분류해 설명:
  - execution_error(ORA-/PG 오류) → SQL/스키마/파라미터 문제
  - row_count/value/column_mismatch → 실제 결과 차이 (변환 검토 필요)
  - 대량조회 타임아웃 → 정상(개별 쿼리 타임아웃 작동)

### 5단계: 타겟 복사 (선택)
```
python3.11 scripts/run_oma.py --phase copy_target
```

## 문제 발견 시 (대화형 전환)

- 어느 단계든 오류/의외의 결과가 나오면 **자동으로 다음 단계로 넘어가지 말고** 멈춘다.
- 로그/리포트를 읽어 원인을 진단하고, 사용자에게 선택지를 제시한다.
- 설정 수정이 필요하면 `oma.properties` / `scripts/special_variables.json`을 함께 고친다.
- 재시작은 체크포인트가 지원한다: 이미 완료된 Phase/조각은 자동으로 건너뛴다.
  실패 조각만 다시: `--retry-failed`.

## 인자에 따른 동작

- 인자 없음: 위 "현재 설정"과 체크포인트를 보고 **어느 단계부터 할지 사용자에게 안내**.
- `preflight`: 1단계만 실행하고 가이드 요약.
- `all`: 전 Phase 순차 실행하되, **각 Phase 후 결과를 확인하고 문제 있으면 멈춘다**.
  (사용자가 "끝까지 알아서"라고 명시하지 않는 한 무인 실행하지 않음)
- 특정 phase 이름(dictionary/convert 등): 그 Phase만 실행.

## 참고
- 지원 검증 조합: **Oracle→PostgreSQL** (다른 조합은 `design/19-multisource-target-guide.md`)
- 상세 설계: `design/` 디렉토리, 규칙: `CLAUDE.md`
- 실행 로그는 콘솔에 출력된다. 산출물은 `projects/<APPLICATION_NAME>/` 아래.
