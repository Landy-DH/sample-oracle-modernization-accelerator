# OMA Schema - 스키마 마이그레이션 파이프라인 (v2)

**시크릿 기반 · 모듈형 · 3단계(DMS SC 1차 → LLM 2차 → full-load 데이터 3차)**

## 개요

작업 플로우:

```
env 에서 oma 환경 배포 → DMS SC 프로젝트 생성 (선행, env 단계)
   ↓
[1차] schema/main.py 가 그 DMS SC 를 이용해 변환 수행
      → 변환 DDL + 액션아이템을 프로젝트 연결 S3 에 산출(DMS 가 zip 업로드)
   ↓
[2차] schema/main.py --phase2
      → 산출물 다운로드 → 변환 DDL 타겟 적용 → 시퀀스 현재값 동기화
      → 미변환/오류 오브젝트 판별 → Bedrock LLM 으로 변환·타겟 생성
      → 스키마(오브젝트) 마이그레이션 완료
   ↓
[3차] schema/main.py --phase3
      → 타겟 FK 캡처·드랍 → DMS full-load replication task 로 오라클 데이터를
        타겟에 적재 → 타겟 FK 재생성 → 데이터 마이그레이션 완료
```

- **자격증명은 코드/설정에 두지 않는다.** AWS Secrets Manager 시크릿 "이름"만 참조.
- `env/oma.properties` 는 사용하지 않는다. schema 단계는 `schema/oma.properties`(시크릿 기반)로 독립 동작.
- DB 접속은 **접속 전용 모듈**(`db/`)로, 소스/타겟 구분 없이 쿼리를 실행한다.
- 1차 범위는 `export-as-script` 까지(S3 산출물만). 타겟 실 DB 반영은 2차에서 수행한다.

## 디렉토리 구조

```
schema/
├── oma.properties          # 시크릿 기반 설정(경로 변수화, Bedrock 포함)
├── config.py               # 설정 로더 + ${VAR} 치환 + 섹션 병합
├── main.py                 # 오케스트레이터 (1차: 기본 / 2차: --phase2 / 3차: --phase3)
├── db/                     # 모듈형 DB 접속 계층
│   ├── secrets.py          #   Secrets Manager 조회(캐싱)
│   ├── connection.py       #   시크릿 → 커넥션(oracle=oracledb, postgres=psycopg2)
│   └── executor.py         #   DBExecutor: register/query/execute/executescript
├── llm/
│   └── bedrock_client.py   # BedrockClient: RPM제한+지수백오프 invoke_model
├── steps/
│   ├── dms_sc_convert.py   # [1차] DMS SC 변환(ext→import→convert→export→assess)
│   ├── s3_export.py        # [1차] 산출물 S3 위치 확인(재압축 아님)
│   ├── artifact_fetch.py   # [2차] S3 산출물 다운로드(DDL zip 해제 + 통계 + aid)
│   ├── ddl_apply.py        # [2차] 변환 DDL 타겟 적용($$ 인식, exists=skip)
│   ├── sequence_sync.py    # [2차] 소스 시퀀스 현재값 → 타겟 setval 동기화
│   ├── triage.py           # [2차] 변환대상 판별(countErrorNodes>0 또는 CRITICAL)
│   ├── llm_convert.py      # [2차] dbms_metadata 추출 → LLM 변환 → 타겟 적용
│   ├── fk_manager.py       # [3차] 타겟 FK 캡처/드랍/재생성(pg_get_constraintdef)
│   └── dms_full_load.py    # [3차] DMS full-load replication task 생성·시작·폴링
├── bak/                    # 이전 버전 백업(5단계 파이프라인)
└── README.md
```

## 설정 (`schema/oma.properties`)

- `[COMMON]` + 프로젝트 섹션(`[b2b]` 등) 병합. 프로젝트 섹션이 오버라이드.
- 경로는 `${OMA_BASE_DIR}` 등 변수로 치환 → 향후 env/schema/app 통합 시 기준 경로만 조정.
- 주요 키: `SOURCE_SECRET_NAME` / `TARGET_SECRET_NAME`, `SOURCE_SCHEMA` / `TARGET_SCHEMA`,
  `DMS_MIGRATION_PROJECT_ARN`, `DMS_SC_S3_BUCKET`, `WORK_DIR`(2차 작업 디렉토리),
  `CONVERT_TIMEOUT`(0=적응형), `CONVERT_NUMBER_TO_BIGINT`,
  Bedrock/LLM(`BEDROCK_MODEL_ID`, `BEDROCK_REGION`, `LLM_RPM_LIMIT`,
  `LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES`, `LLM_RETRY_BASE_DELAY`, `LLM_MAX_OUTPUT_TOKENS`).
  S3 prefix 는 프로젝트명으로 자동 해석(설정 불필요).

## 사용법

```bash
cd /home/ec2-user/workspace/oma/schema

# 설정만 로드/검증(실행 안 함) — 통합 점검용
python3.11 main.py --check
python3.11 main.py --app b2b --phase2 --check

# 1차 변환 실행 (DMS SC → S3 산출)
python3.11 main.py --app b2b

# 2차 변환 실행 (다운로드 → 적용 → 시퀀스 → 판별 → LLM 변환)
python3.11 main.py --app b2b --phase2

# 3차 데이터 이전 실행 (FK 드랍 → DMS full-load → FK 재생성)
python3.11 main.py --app b2b --phase3
```

> `python3.11` 에만 boto3/psycopg2/oracledb 가 설치되어 있다(시스템 python3=3.9 는 없음).

## 산출물 규약(1차)

- 변환 DDL: `s3://<bucket>/<프로젝트명>/dms-sc-<schema_lower>.zip` (단일 `.sql`)
- 액션아이템(JSON): `s3://<bucket>/<프로젝트명>/action-items/`
  - `<req-id>/Schemas.<SCHEMA>` : 오브젝트 트리 통계(변환대상 판별 근거)
  - `*-aid` : 코드 → severity 사전

## 2차 판별 기준

LLM 재생성 대상 = 오브젝트 통계에서 **`countErrorNodes > 0`** 또는
**CRITICAL severity 액션아이템 코드 보유**. 프로시저는 껍데기만 생성되고
로직이 미구현될 수 있어 "존재 유무" 비교로는 잡히지 않으므로 통계 기반으로 판별한다.

## 시퀀스 동기화

Oracle `ALL_SEQUENCES.LAST_NUMBER`(캐시 반영 "다음 할당 경계")를 읽어
타겟에 `setval('<schema>.<seq>', last_number, false)` — 다음 `nextval` 이
`last_number` 를 반환하도록 맞춰 소스 현재값 이후로 충돌 없이 이어간다.
DDL 적용(시퀀스 생성) 이후 실행 전제.

## 3차 데이터 이전 (full-load)

1·2차로 **오브젝트**가 생성된 뒤, 오라클의 **데이터**를 타겟으로 옮긴다.
DMS Schema Conversion(메타데이터)과 별개인 **replication task**(full-load)를 쓴다.

```
[FK 드랍]  타겟 스키마의 모든 FK 를 pg_get_constraintdef() 로 정의째 캡처 후 DROP
   ↓       (full-load 는 테이블을 병렬 적재 → 자식이 부모보다 먼저 들어오면
   ↓        FK 참조 무결성 위반으로 로딩 실패하므로 선드랍 필수)
[full-load] replication task 생성(MigrationType=full-load,
   ↓        TargetTablePrepMode=TRUNCATE_BEFORE_LOAD) → 시작 → 완료 폴링
[FK 재생성] 캡처한 정의로 ADD CONSTRAINT (성공/실패와 무관하게 항상 원복 시도)
```

- **리소스는 이름으로 자동 조회**(env 단계 배포 산출물). 기본값:
  - replication instance : `omabox-stack-dms-instance`
  - source endpoint      : `omabox-stack-source-oracle`
  - target endpoint      : `omabox-stack-target-aurora`
  - 필요 시 `DMS_REPLICATION_INSTANCE` / `DMS_SOURCE_ENDPOINT` /
    `DMS_TARGET_ENDPOINT` 로 오버라이드. `FULL_LOAD_TIMEOUT`(0=무제한).
- FK 정의는 `WORK_DIR/fk-backup-<schema>.json` 에 백업(감사/복구용).
- 재실행 안전: `TRUNCATE_BEFORE_LOAD` 로 적재 전 대상 행만 비우고(스키마/제약 유지),
  기존 task 는 재사용하며 `reload-target` 로 다시 적재한다.
