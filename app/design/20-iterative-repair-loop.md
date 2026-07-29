# 오류유형 기반 반복 수정 루프 (Iterative Repair Loop)

## 개요

변환(Phase4)·검증(Phase6)이 끝난 뒤, **검증 실패를 오류 유형별로 자동 분류**하고
각 유형을 작업 단위로 삼아 **LLM 대화형으로 조각(fragment)을 수정 → 재머지 → 재검증
→ 재분석**을 반복한다. 오류가 사라질 때까지 수렴시키는 것이 목표다.

기존 파이프라인(00~19)은 "한 번 변환한다"에 초점이 있었다면, 이 문서는
"변환 후 남은 실패를 유형 단위로 좁혀가며 없앤다"는 **후처리 수렴 루프**를 정의한다.

핵심 아이디어:
- **오류 유형이 곧 작업 단위**다. 유형별로 어느 매퍼의 어느 sql_id가 문제인지
  영향 조각 리스트를 미리 계산해 둔다.
- 유형에 **번호**를 부여한다. 사용자가 "N번 유형 수정하자"라고 하면, 그 유형의
  성격과 영향 조각이 이미 준비되어 있으므로 즉시 대화형 수정에 진입한다.
- 수정은 **조각 파일(`converted/*.xml`)에서** 한다 (매퍼 전체가 아니라 조각 단위).
- 한 유형을 처리하면 **재머지 → 동일 테스트(검증) → 오류유형 재분석**을 돌려
  개선을 즉시 확인한다. 이를 **에러가 0이 될 때까지 반복**한다.

---

## 1. 루프 구조

```
┌─────────────────────────────────────────────────────────────┐
│  [convert] → [merge] → [validate]                            │
│                            │                                  │
│                            ▼                                  │
│                   [analyze]  검증 결과를 성공/실패로 나누고    │
│                              실패를 오류 유형별로 분류·번호부여  │
│                            │                                  │
│                            ▼                                  │
│              ┌── 실패 유형 목록 제시 (번호 + 성격 + 영향 조각 수) │
│              │                                                │
│      사용자: "N번 유형 수정하자"                                │
│              │                                                │
│              ▼                                                │
│      [repair]  유형 N의 영향 조각들을 LLM 대화형으로 수정        │
│               (converted/*.xml 덮어쓰기)                       │
│              │                                                │
│              ▼                                                │
│      [merge] → [validate] → [analyze]  (재수렴 확인)          │
│              │                                                │
│              └── 실패 남으면 다음 유형 선택 → 반복             │
│                  실패 0 → 완료                                 │
└─────────────────────────────────────────────────────────────┘
```

단계 요약:
1. **analyze**: `validation-details.json`을 읽어 실패를 오류 유형으로 분류하고,
   유형별 영향 조각(`(mapper, sql_id, statement_type)`) 리스트와 대표 에러 메시지를
   `repair-plan.json`으로 저장한다. 유형에는 안정적인 번호를 매긴다.
2. **제시**: 유형 번호·성격·건수·대표 에러·영향 매퍼를 사람이 읽는 형태로 보고한다.
3. **repair (유형 단위)**: 사용자가 고른 유형 번호의 영향 조각 각각에 대해
   `원본 조각 + 현재 변환 조각 + 검증 에러`를 LLM에 주고 수정본을 받아
   `converted/`에 덮어쓴다. 대화형으로 진행(샘플 먼저 보여주고 확정 후 일괄 적용 가능).
4. **재검증**: merge → validate → analyze를 다시 돌려 해당 유형이 줄었는지 확인한다.
5. **반복**: 남은 유형에 대해 2~4를 반복. 모든 실패가 사라지면 종료.

---

## 2. 오류 유형 분류 (analyze)

### 2.1 분류 기준

검증 실패 TC(`status == failed`)를 다음 축으로 분류한다. `note` 필드(소스/타겟
실행 에러 또는 MyBatis 로딩 에러)를 근거로 하되, **정규식으로 SQL을 파싱하지 않고**
에러 메시지의 키워드만 감지한다(HARD RULE 준수).

| 그룹 | 카테고리 예 | 성격 | 기본 조치 |
|------|-------------|------|-----------|
| A | 미변환 함수 (`to_char(numeric)`, `nvl`, `to_date` 1인자) | 변환결함 | 재변환(repair) |
| B | 타겟 전용 에러 (operator/컬럼/별칭) | 변환결함 의심 | 재변환(repair) |
| C | OGNL 파라미터 null/게터누락 | 테스트데이터 | TC 파라미터 보정 |
| D | 값 길이/날짜 범위 초과 | 테스트데이터 | TC 데이터 보정 |
| E | 비실행 조각(resultMap/sql)에 TC 생성 | TC생성 이슈 | TC 필터링 |
| F | source·target 동일 에러 | 오탐 | 조치 불필요(원본 문제) |

> **오탐(F) 자동 격리**: `note`가 `source: ... | target: ...` **양면 형태**이고 양쪽
> 에러가 동일하면 원본 소스도 실패하는 케이스 → 변환 무관, repair 제외.
> 단 `note`는 세 형태가 있다: ① 양면(`source:...| target:...`), ② target 단면
> (`target: ERROR ...`), ③ source 단면(`source: ERROR ...`). F(오탐) 판정은 **①에서
> 양쪽이 동일할 때만** 적용한다. ②는 타겟만 실패 = repair 후보(A/B), ③은 소스만 실패
> = 원본 문제(별도 표기). 즉 `source:|target:` 패턴만으로 F를 단정하지 말고 양쪽 에러
> 동일성까지 비교한다.

### 2.2 유형 번호 부여

반복 루프에서 매 iteration마다 재분석하면 건수가 바뀌므로, **건수 내림차순 번호는
루프 도중 번호가 뒤바뀌어** "N번 유형 수정하자" UX가 깨진다. 따라서:

- 번호는 **카테고리(그룹키) 기반의 안정 ID**로 부여한다. 예: 카테고리 목록을 고정
  순서(A→B→C→D→E→F, 그 안에서 카테고리 문자열 사전순)로 나열하고 그 순서대로
  번호를 매긴다. 같은 카테고리는 실행이 바뀌어도 **항상 같은 번호**를 갖는다.
- 어떤 iteration에서 특정 카테고리의 실패가 0이 되면 그 번호는 목록에서 사라지되,
  **남은 카테고리의 번호는 그대로 유지**한다(재정렬로 번호가 밀리지 않게).
- 보고 시 번호 옆에 건수를 함께 표시한다. 사용자는 "영향 큰 것부터"를 건수로 판단하고,
  번호는 카테고리를 가리키는 안정 식별자로 쓴다.
- 오탐(F)은 번호를 부여하되 "조치 불필요"로 표기한다.

> 구현 노트: repair-plan.json의 `no`는 카테고리→번호 매핑 테이블에서 가져오며, 이
> 매핑은 코드 상수(카테고리 순서)로 고정한다. 건수에 따라 재계산하지 않는다.

### 2.3 repair-plan.json (분석 산출물)

```json
{
  "run_id": "20260728_...",
  "generated_from": "reports/validation-details.json",
  "summary": {"total": 507, "passed": 299, "failed": 208},
  "types": [
    {
      "no": 1,
      "group": "A_미변환_Oracle함수",
      "category": "target_fn_missing",
      "nature": "변환결함",
      "action": "repair",
      "count": 21,
      "representative_error": "function to_char(numeric) does not exist",
      "fragments": [
        {"mapper": "NoticeMapper", "sql_id": "retrieveNoticeList",
         "statement_type": "select", "frag_id": "NoticeMapper__select__retrieveNoticeList",
         "tc_ids": ["NoticeMapper_retrieveNoticeList_tc001"],
         "error": "target: ERROR: function to_char(numeric) does not exist ..."}
      ]
    }
  ]
}
```

`frag_id`는 오케스트레이터의 `_fragment_id(mapper, sql_id, statement_type)`와 동일
규칙(`{mapper}__{type}__{sql_id}`)으로 만들어 `converted/` 파일명과 1:1 매칭한다.

**(mapper, sql_id) 얻기 — tc_id 역파싱 금지.** tc_id는 `{mapper}_{sql_id}_tcNNN`로
언더스코어 조인이라 mapper/sql_id에 `_`가 있으면 역파싱이 애매하다. 대신 실패 tc_id로
**테스트케이스 JSON(`testcases/{tc_id}.json`)을 열어 `mapper`·`sql_id` 필드를 직접
읽는다**(키 이름은 `mapper`, `sql_id`). 이 필드는 TC 생성 시 항상 채워진다.

**statement_type 결정 — 실행가능 타입 우선.** statement_type은 TC JSON에 없으므로
`fragmented/mapping.json`에서 `(mapper, sql_id)`로 조회한다. 단 이 키는 유일하지 않다:
`MainOrderMapper.retrieveMainOrderList`처럼 `resultMap`과 `select`가 같은 id를 공유하는
경우 두 statement_type이 나온다(← `_fragment_id`가 해결하려던 바로 그 충돌). 검증 TC는
**실행 가능한 statement**에 대한 것이므로, 후보가 여럿이면 실행가능 타입
(`select`/`insert`/`update`/`delete`)을 우선 선택한다. 실행가능 후보가 없으면
(resultMap/sql만 있는 경우 = 그룹 E, 비실행 조각에 TC 오생성) repair 대상이 아니라
TC 필터링 대상으로 분류한다.

---

## 3. 조각 수정 (repair)

### 3.1 대상 파일

수정은 **조각 파일에서** 한다:
- 대상: `projects/<app>/mappers/converted/<frag_id>.xml`
- 참조: `projects/<app>/mappers/original/<source_file>`(원본 조각 문맥),
  `fragmented/<frag_id>.xml`(선치환된 소스 조각)
- 리포트: `converted/<frag_id>.report.json` (수정 이력/사유 갱신)

매퍼 전체가 아닌 조각을 고치는 이유: 병합(Phase5)이 `(statement_type, id)` 키로
조각을 원본 구조에 끼워넣으므로, 조각만 바꾸면 나머지는 그대로 재조립된다.

> **제약 (merge는 원본 스켈레톤 주도)**: `MapperCombiner`는 **원본 매퍼**를 뼈대로
> `list(root)`를 순회하며 각 요소를 매칭되는 변환 조각으로 교체한다. 따라서 repair는
> **원본에 이미 존재하는 statement의 조각을 편집**할 때만 유효하다. converted/에
> 원본에 없는 새 statement 조각을 추가해도 병합에서 매칭되지 않아 `unused_fragments`로
> 버려진다(combiner.py). 즉 repair로 statement를 신설/삭제할 수는 없고, 기존 조각의
> 내용을 고치는 용도다(현재 repair 목적에 부합).

### 3.2 LLM 수정 프롬프트 (repair 전용)

기존 변환 프롬프트(05, `prompts.py`)와 별개로 **에러 수정 전용 프롬프트**를 쓴다.
입력 3종을 준다:
1. **원본 조각**(소스 방언) — 의미의 기준
2. **현재 변환 조각**(고쳐야 할 대상)
3. **검증 에러 메시지**(무엇이 왜 실패했는지)

지시 골자:
- "이 검증 에러를 해소하도록 현재 변환 조각을 **최소 수정**하라. MyBatis 동적 태그와
  XML 구조, 이미 올바른 부분은 보존하라."
- 유형별 힌트를 함께 준다(예: `to_char(숫자)` → `숫자::text` 또는
  `to_char(숫자, 'FM...')`; `nvl` → `coalesce`; `to_date(x)` 1인자 → 포맷 명시).
- 출력은 변환 조각 XML 전문 + 변경 요약(JSON).
- **함수 매핑을 코드에 하드코딩하지 않는다.** 유형별 힌트는 데이터(설정/플랜)로 주고,
  실제 재작성은 모델이 문맥을 보고 판단한다(기존 설계 철학 유지).

### 3.3 대화형 진행

- 유형의 영향 조각이 많으면, 먼저 **대표 1~2개를 수정해 사용자에게 diff를 제시**하고
  방향 확정 후 나머지를 **동일 지침으로 일괄** 적용한다.
- 조각별 수정 전 현재 변환본을 `.bak`으로 백업하고, report.json에 "repair" 이력을 남긴다.

> **report.json 스키마 확장**: 현재 `converted/<frag_id>.report.json`은 8개 필드
> (`status, strategy, type_casts, syntax_changes, warnings, param_mappings,
> manual_review_required, analysis`)만 저장한다(orchestrator `_save_conversion`).
> repair는 여기에 `repair_history`(리스트: `{when, error, fix_summary, backup}`)를
> **추가**한다. 또한 repair는 조각 XML만 교체하고 **TC(test_cases)는 재생성하지 않는다**
> (기존 `_save_conversion`은 result.test_cases를 다시 쓰므로, repair는 그 경로를 쓰지
> 않고 조각 XML + report.json만 갱신하는 전용 저장 함수를 사용한다).

---

## 4. 재검증·재분석 (수렴)

한 유형을 처리한 뒤:
```
python3.11 scripts/run_oma.py --config oma.properties --phase merge,validate
python3.11 scripts/analyze_failures.py --config oma.properties   # repair-plan 갱신
```
- merge는 `converted/`의 최신 조각으로 다시 조립한다.
- validate는 동일 TC로 재실행해 **해당 유형이 줄었는지** 즉시 확인한다.
- analyze는 실패를 다시 분류해 유형 목록/번호를 갱신한다.
- 실패가 남으면 다음 유형을 선택해 반복, **0이 되면 종료**한다.

> 검증은 조각 단위 부분 실행이 아니라 전체 TC 재실행이 기본이다(연쇄 영향 확인).
> 필요 시 특정 매퍼/유형 TC만 부분 검증하는 옵션은 향후 확장.

---

## 5. 산출물 / 파일 위치

| 파일 | 내용 |
|------|------|
| `reports/failure-analysis.json` | 그룹/카테고리/매퍼 집계 (사람용 요약) |
| `reports/failure-analysis.csv` | 실패 전체 목록 (조각·유형·에러) |
| `reports/repair-plan.json` | 유형 번호 + 영향 조각 리스트 (repair 입력) |
| `reports/failure-report.md` | 유형별 보고서 (번호·성격·조치·상위 매퍼) |
| `converted/<frag_id>.xml` | 수정 대상/결과 조각 |
| `converted/<frag_id>.report.json` | 조각별 변환/수정 이력 |

---

## 6. 도구 (정규 프로세스)

| 스크립트 | 역할 |
|----------|------|
| `scripts/analyze_failures.py` | validate 결과 → 오류유형 분류 → repair-plan.json/보고서 생성 |
| `scripts/repair_type.py` | 유형 번호를 받아 영향 조각을 LLM으로 수정(대화/일괄) |
| `scripts/reset_failed_fragments.py` | (기존) 실패 조각만 체크포인트에서 리셋해 재변환 |

**실행 방식**: 현재 오케스트레이터(`WorkflowOrchestrator.run`)에는 phase 종료 후
콜백/훅이 없고, analyze/repair는 phase가 아니다(`_ALL_PHASES`/`_PHASE_ALIASES`에 없음).
따라서 auto-run은 기존 배관 재사용이 아니라 신규 배선이 필요하다. 1차 구현은
**validate 뒤 별도 명령으로 명시 실행**한다:
```
python3.11 scripts/run_oma.py --config oma.properties --phase merge,validate
python3.11 scripts/analyze_failures.py --config oma.properties
```
향후 편의를 위해 `run_oma.py`에 `--analyze`(validate 후 자동 분석) 옵션을 추가하는
것을 확장 과제로 둔다(별도 phase 또는 validate 후처리 훅).

---

## 7. HARD RULE 준수

- SQL/XML 파싱은 lxml 사용, 에러 메시지 분류는 **키워드 감지만**(정규식으로 SQL
  구조 파싱 금지). sed 금지 — 조각 수정은 Python/LLM으로만.
- 함수 매핑 하드코딩 금지 — 유형 힌트는 설정/플랜 데이터로, 재작성은 모델 판단.
- 조각 파일 수정 시 변경 이력(report.json)과 백업(.bak)을 남긴다.

---

## 변경 이력

2026-07-28 | OMA Team | 초기 작성
  - 오류유형 기반 반복 수정 루프 설계: analyze→(유형선택)→repair→merge→validate
    →analyze 수렴 구조, repair-plan.json 계약, repair 전용 프롬프트, 정규 도구 정의
