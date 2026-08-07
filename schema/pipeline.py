"""
OMA Schema - 파이프라인 실행 함수 모음

main.py(CLI) 에서 분리한 1·2차 + apply-changes 오케스트레이션 로직.
  - run_pipeline(cfg)  : 1차(DMS SC → S3 산출)
  - run_apply_changes(cfg) : apply changes(export-to-target 단독)
  - run_phase2(cfg)    : 2차(산출물 다운로드 → 시퀀스 → 판별 → LLM 변환)
  - report_phase2 : 결과 요약 + 종료 코드 산출

3차(full-load 데이터 이전)는 pipeline_phase3.py 를 참조.
자격증명은 Secrets Manager 시크릿 "이름"으로만 참조한다.

변경 이력:
2026-08-05 | OMA Team | 초기 생성(main.py 분리)
  - main.py 가 500 line 을 초과하여 파이프라인 실행 함수를 이 모듈로 이관
  - 1/2/3차 + apply-changes 실행 함수와 리포트 함수 이동
2026-08-05 | OMA Team | 3차 함수를 pipeline_phase3.py 로 재분리(500 line 대응)
"""

import logging

from config import Config
from db import DBExecutor
from llm.bedrock_client import BedrockClient
from steps.artifact_fetch import ArtifactFetcher
from steps.dms_sc_convert import DmsScConverter, DmsScError
from steps.llm_convert import LlmConverter
from steps.s3_export import S3Exporter
from steps.sequence_sync import SequenceSync
from steps.triage import Triage

logger = logging.getLogger("oma.schema")

# Oracle 객체 수 조회 SQL(적응형 타임아웃용)
_OBJECT_COUNT_SQL = (
    "SELECT COUNT(*) AS CNT FROM ALL_OBJECTS WHERE OWNER = :owner "
    "AND OBJECT_TYPE IN ("
    "'TABLE','INDEX','SEQUENCE','FUNCTION','PROCEDURE',"
    "'PACKAGE','PACKAGE BODY','VIEW','TRIGGER','TYPE','TYPE BODY',"
    "'SYNONYM','MATERIALIZED VIEW','JOB')"
)


def _make_object_count_fn(executor: DBExecutor):
    """
    소스(Oracle) 객체 수를 반환하는 콜러블을 만든다.

    Args:
        executor: 'source' endpoint가 등록된 DBExecutor

    Returns:
        (schema: str) -> int 콜러블
    """

    def _count(schema: str) -> int:
        """ALL_OBJECTS 기준 스키마 객체 수를 조회한다."""
        rows = executor.query("source", _OBJECT_COUNT_SQL, [schema.upper()])
        if rows:
            # 컬럼명이 대문자 CNT로 반환됨(oracledb)
            first = rows[0]
            return int(next(iter(first.values())))
        return 0

    return _count


def run_pipeline(cfg: Config) -> dict:
    """
    1차 변환 파이프라인을 실행한다.

    Args:
        cfg: 로드된 설정

    Returns:
        결과 dict(dms 결과 + s3 업로드 결과)

    Raises:
        ConfigError, DmsScError, S3ExportError: 각 단계 실패 시
    """
    region = cfg.require("AWS_REGION")
    source_schema = cfg.require("SOURCE_SCHEMA")
    target_schema = cfg.require("TARGET_SCHEMA")
    project_arn = cfg.require("DMS_MIGRATION_PROJECT_ARN")
    s3_bucket = cfg.require("DMS_SC_S3_BUCKET")
    file_name = f"dms-sc-{source_schema.lower()}"

    # 접속 전용 모듈(소스/타겟 endpoint 등록)
    executor = DBExecutor(region=region)
    executor.register(
        "source",
        cfg.require("SOURCE_DB_TYPE"),
        cfg.require("SOURCE_SECRET_NAME"),
    )
    executor.register(
        "target",
        cfg.require("TARGET_DB_TYPE"),
        cfg.require("TARGET_SECRET_NAME"),
    )

    try:
        # Step A: DMS SC 1차 변환(S3 산출물 생성)
        logger.info("=" * 60)
        logger.info("Step A: DMS SC 1차 변환")
        logger.info("=" * 60)
        converter = DmsScConverter(
            project_arn=project_arn,
            region=region,
            s3_bucket=s3_bucket,
            poll_interval=cfg.get_int("POLL_INTERVAL", 15),
            convert_number_to_bigint=cfg.get_bool("CONVERT_NUMBER_TO_BIGINT", True),
        )
        dms_result = converter.run(
            source_schema=source_schema,
            target_schema=target_schema,
            file_name=file_name,
            timeout=cfg.get_int("CONVERT_TIMEOUT", 0),
            object_count_fn=_make_object_count_fn(executor),
        )
        if not dms_result.get("success"):
            raise DmsScError(f"DMS SC 변환 실패: {dms_result}")

        # Step B: DMS SC 산출물(변환 DDL zip, action-items) S3 위치 확인
        #   DMS 가 이미 산출물을 S3 에 업로드하므로 재압축하지 않고 위치만 확인.
        #   2차(LLM 변환)에서 이 산출물을 다운로드해 미변환 오브젝트를 변환한다.
        logger.info("=" * 60)
        logger.info("Step B: DMS SC 산출물 S3 위치 확인")
        logger.info("=" * 60)
        exporter = S3Exporter(
            bucket=s3_bucket,
            region=region,
            project_arn=project_arn,
        )
        s3_result = exporter.locate_artifacts(
            schema=source_schema,
            file_name=file_name,
        )
    finally:
        executor.close()

    return {"dms_sc": dms_result, "s3_export": s3_result}


def run_apply_changes(cfg: Config) -> dict:
    """
    apply changes(export-to-target)만 단독 실행한다.

    Args:
        cfg: 로드된 설정

    Returns:
        apply_changes 결과 dict

    Raises:
        ConfigError, DmsScError: 실패 시
    """
    region = cfg.require("AWS_REGION")
    converter = DmsScConverter(
        project_arn=cfg.require("DMS_MIGRATION_PROJECT_ARN"),
        region=region,
        s3_bucket=cfg.require("DMS_SC_S3_BUCKET"),
        poll_interval=cfg.get_int("POLL_INTERVAL", 15),
    )
    return converter.apply_changes(
        target_schema=cfg.require("TARGET_SCHEMA"),
        timeout=cfg.get_int("CONVERT_TIMEOUT", 0) or 1800,
    )


def run_phase2(cfg: Config) -> dict:
    """
    2차 파이프라인(LLM 변환)을 실행한다.

    전제: 1차 파이프라인이 apply changes(export-to-target)로 변환 DDL을 이미
      타겟 DB에 반영(오브젝트 생성 완료)한 상태.

    플로우: 산출물 다운로드(fetch, 통계·사전) → 시퀀스 현재값 동기화
      (sequence_sync) → 변환대상 판별(triage) → 미변환 오브젝트 LLM
      변환·적용(llm_convert)

    Args:
        cfg: 로드된 설정

    Returns:
        각 단계 결과 dict

    Raises:
        ConfigError, ArtifactFetchError, SequenceSyncError, TriageError: 단계 실패 시
    """
    region = cfg.require("AWS_REGION")
    source_schema = cfg.require("SOURCE_SCHEMA")
    target_schema = cfg.require("TARGET_SCHEMA")
    project_arn = cfg.require("DMS_MIGRATION_PROJECT_ARN")
    s3_bucket = cfg.require("DMS_SC_S3_BUCKET")
    work_dir = cfg.require("WORK_DIR")
    file_name = f"dms-sc-{source_schema.lower()}"

    executor = DBExecutor(region=region)
    executor.register(
        "source",
        cfg.require("SOURCE_DB_TYPE"),
        cfg.require("SOURCE_SECRET_NAME"),
    )
    executor.register(
        "target",
        cfg.require("TARGET_DB_TYPE"),
        cfg.require("TARGET_SECRET_NAME"),
    )

    try:
        # Step 1: 산출물 다운로드(통계 + severity 사전; 판별 근거)
        #   전체 변환 DDL 반영은 1차 apply changes 가 담당하므로 여기선 미적용.
        logger.info("=" * 60)
        logger.info("Step 1: DMS SC 산출물 다운로드")
        logger.info("=" * 60)
        fetcher = ArtifactFetcher(
            bucket=s3_bucket,
            region=region,
            project_arn=project_arn,
            work_dir=work_dir,
        )
        fetched = fetcher.fetch(schema=source_schema, file_name=file_name)

        # Step 2: 시퀀스 현재값 동기화(소스 → 타겟)
        logger.info("=" * 60)
        logger.info("Step 2: 시퀀스 현재값 동기화")
        logger.info("=" * 60)
        seq_sync = SequenceSync(
            executor=executor,
            source_schema=source_schema,
            target_schema=target_schema,
        )
        seq_result = seq_sync.sync()

        # Step 3: 변환대상 판별(countErrorNodes>0 또는 CRITICAL)
        logger.info("=" * 60)
        logger.info("Step 3: 변환대상 판별")
        logger.info("=" * 60)
        triage = Triage(critical_only=True, code_types_only=True)
        targets = triage.select_targets(
            schema_stats_path=fetched["schema_stats_path"],
            aid_path=fetched["aid_path"],
        )

        # Step 4: 미변환 오브젝트 LLM 변환·적용
        logger.info("=" * 60)
        logger.info("Step 4: LLM 변환·적용 (%d개 대상)", len(targets))
        logger.info("=" * 60)
        llm_client = BedrockClient.from_config(cfg)
        converter = LlmConverter(
            executor=executor,
            llm=llm_client,
            source_schema=source_schema,
            target_schema=target_schema,
        )
        convert_result = converter.convert_targets(targets)
    finally:
        executor.close()

    return {
        "fetch": fetched,
        "sequence_sync": seq_result,
        "triage": {"target_count": len(targets), "targets": targets},
        "llm_convert": convert_result,
    }


def report_phase2(result: dict) -> int:
    """
    2차 파이프라인 결과를 요약 출력한다.

    Args:
        result: run_phase2 결과 dict

    Returns:
        종료 코드(변환 실패가 있으면 2, 아니면 0)
    """
    seq = result["sequence_sync"]
    conv = result["llm_convert"]
    logger.info("=" * 60)
    logger.info("2차 파이프라인 완료")
    logger.info("=" * 60)
    logger.info(
        "  시퀀스 동기화: synced=%d missing=%d failed=%d",
        seq["synced"], seq["missing_in_target"], seq["failed"],
    )
    logger.info("  변환대상    : %d개", result["triage"]["target_count"])
    logger.info(
        "  LLM 변환    : converted=%d/%d failed=%d",
        conv["converted"], conv["total"], conv["failed"],
    )
    for r in conv["results"]:
        if r["status"] != "CONVERTED":
            logger.warning(
                "    실패: %s %s (%s)",
                r["object_type"], r["object_name"], r["status"],
            )
    return 2 if conv["failed"] > 0 else 0


