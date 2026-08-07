"""
OMA Schema - 3차 파이프라인(DMS full-load 데이터 이전) 실행 함수

  - run_phase3_preflight(cfg) : 리소스/엔드포인트 상태·접속만 확인(조회 전용)
  - run_phase3(cfg)           : preflight → FK 드랍 → full-load → FK 재생성
  - report_phase3_preflight / report_phase3 : 결과 요약 + 종료 코드

파괴적 작업(FK 드랍 / 타겟 truncate) 전에 preflight 로 엔드포인트 준비를
확인하고, 미준비면 중단한다. 소스(대문자) → 타겟(소문자) 정합은 DmsFullLoad
의 소문자 변형 규칙(dms_mappings)이 담당한다.

변경 이력:
2026-08-05 | OMA Team | 초기 생성(pipeline.py 분리, 500 line 대응)
  - 3차 preflight/실행/보고 함수 이관
2026-08-05 | OMA Team | bigint 범위 초과 교정 스텝(1.5) 추가
  - 원인: NUMBER→bigint 변환 컬럼이 소스 실제 값(19자리 초과)으로 적재 시
    "out of range for type bigint" 로 테이블 오류 발생
  - executor 에 'source' endpoint 등록, FK 드랍과 full-load 사이에 BigintWidener
    실행(BIGINT_WIDEN=false 로 비활성 가능), 결과를 반환/보고에 포함
"""

import logging
import os

from config import Config
from db import DBExecutor
from steps.bigint_widen import BigintWidener, BigintWidenError
from steps.dms_full_load import DmsFullLoad, DmsFullLoadError
from steps.fk_manager import ForeignKeyManager, ForeignKeyManagerError

logger = logging.getLogger("oma.schema")

# 3차 리소스 이름 기본값(env 단계 배포 산출물). oma.properties 로 오버라이드 가능.
_DEFAULT_DMS_INSTANCE = "omabox-stack-dms-instance"
_DEFAULT_SOURCE_ENDPOINT = "omabox-stack-source-oracle"
_DEFAULT_TARGET_ENDPOINT = "omabox-stack-target-aurora"

# Limited LOB 모드 최대 크기 기본값(KB). 대형 CLOB truncation(ORA-01406) 방지.
_DEFAULT_LOB_MAX_KB = 1024


def _build_full_load(cfg: Config) -> DmsFullLoad:
    """
    설정으로 DmsFullLoad 를 구성한다(리소스 이름/소문자 변형 등).

    Args:
        cfg: 로드된 설정

    Returns:
        DmsFullLoad 인스턴스
    """
    return DmsFullLoad(
        region=cfg.require("AWS_REGION"),
        instance_name=cfg.get("DMS_REPLICATION_INSTANCE", _DEFAULT_DMS_INSTANCE),
        source_endpoint_name=cfg.get(
            "DMS_SOURCE_ENDPOINT", _DEFAULT_SOURCE_ENDPOINT
        ),
        target_endpoint_name=cfg.get(
            "DMS_TARGET_ENDPOINT", _DEFAULT_TARGET_ENDPOINT
        ),
        poll_interval=cfg.get_int("POLL_INTERVAL", 30),
        lowercase=cfg.get_bool("DMS_LOWERCASE_NAMES", True),
        lob_max_size_kb=cfg.get_int("FULL_LOAD_LOB_MAX_KB", _DEFAULT_LOB_MAX_KB),
        number_scale_zero=cfg.get_bool("DMS_NUMBER_SCALE_ZERO", True),
    )


def run_phase3_preflight(cfg: Config) -> dict:
    """
    3차 사전 점검: 리소스/엔드포인트 상태만 확인(적재·FK 변경 없음).

    실제 full-load 실행 전에 사용자 승인을 받기 위한 근거를 만든다.
    데이터/스키마를 변경하지 않는 안전한 조회 전용 동작이다.

    Args:
        cfg: 로드된 설정

    Returns:
        DmsFullLoad.preflight() 결과 dict

    Raises:
        ConfigError, DmsFullLoadError: 리소스 조회 실패 시
    """
    logger.info("=" * 60)
    logger.info("3차 사전 점검(preflight): 엔드포인트 상태/접속 테스트")
    logger.info("=" * 60)
    return _build_full_load(cfg).preflight()


def report_phase3_preflight(result: dict) -> int:
    """
    3차 사전 점검 결과를 요약 출력한다.

    Args:
        result: run_phase3_preflight 결과 dict

    Returns:
        종료 코드(ready 면 0, 아니면 2)
    """
    inst = result["instance"]
    src = result["source"]
    tgt = result["target"]
    logger.info("=" * 60)
    logger.info("3차 사전 점검 결과")
    logger.info("=" * 60)
    logger.info(
        "  replication instance : %s (%s)", inst["name"], inst["status"]
    )
    logger.info(
        "  source endpoint      : %s [%s] status=%s connection=%s",
        src["name"], src["engine"], src["status"], src["connection"],
    )
    logger.info(
        "  target endpoint      : %s [%s] status=%s connection=%s",
        tgt["name"], tgt["engine"], tgt["status"], tgt["connection"],
    )
    if result["ready"]:
        logger.info("  → 준비 완료. full-load 를 진행할 수 있습니다.")
    else:
        logger.warning("  → 준비 미완료. 위 상태를 해결 후 다시 점검하세요.")
    return 0 if result["ready"] else 2


def run_phase3(cfg: Config) -> dict:
    """
    3차 파이프라인(DMS full-load 데이터 이전)을 실행한다.

    전제: 1·2차로 타겟 스키마의 오브젝트(테이블/제약/시퀀스 등)가 이미 생성됨.
      그리고 run_phase3_preflight 로 엔드포인트 상태를 확인하고 사용자 승인을 받음.

    플로우:
      0. preflight 로 리소스/엔드포인트 준비 확인(미준비면 FK 드랍 전에 중단)
      1. 타겟 FK 캡처 + DROP  (full-load 시 부모/자식 로드 순서로 인한
         참조 무결성 위반 방지)
      1.5 bigint 범위 초과 컬럼 numeric 교정(적재 out-of-range 방지)
      2. DMS full-load replication task 생성·시작·완료 대기(데이터 적재)
      3. 타겟 FK 재생성

    Args:
        cfg: 로드된 설정

    Returns:
        {"fk_drop", "bigint_widen", "full_load", "fk_recreate"} 결과 dict

    Raises:
        ConfigError, ForeignKeyManagerError, DmsFullLoadError,
        BigintWidenError: 단계 실패 시
    """
    region = cfg.require("AWS_REGION")
    source_schema = cfg.require("SOURCE_SCHEMA")
    target_schema = cfg.require("TARGET_SCHEMA")

    # FK 정의 백업 경로(감사/복구용). WORK_DIR 있으면 그 아래, 없으면 미저장.
    work_dir = cfg.get("WORK_DIR")
    backup_path = (
        os.path.join(work_dir, f"fk-backup-{target_schema}.json")
        if work_dir
        else None
    )

    full_load = _build_full_load(cfg)

    # Step 0: preflight 확인 - 미준비면 FK 드랍/적재 전에 중단(파괴적 작업 보호)
    logger.info("=" * 60)
    logger.info("Step 0: preflight(엔드포인트 상태/접속) 확인")
    logger.info("=" * 60)
    pf = full_load.preflight()
    if not pf["ready"]:
        raise DmsFullLoadError(
            "preflight 미준비 - 엔드포인트 상태/접속을 확인하세요: "
            f"instance={pf['instance']['status']} "
            f"source={pf['source']['connection']} "
            f"target={pf['target']['connection']}"
        )

    executor = DBExecutor(region=region)
    # 소스(Oracle): bigint 범위 초과 판별용 최대값 조회에 사용
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

    fk_mgr = ForeignKeyManager(
        executor=executor,
        target_schema=target_schema,
        backup_path=backup_path,
    )
    fks: list = []
    fk_drop: dict = {"dropped": 0, "failed": 0, "errors": []}
    fk_recreate: dict = {"recreated": 0, "failed": 0, "errors": []}
    bigint_widen: dict = {"checked": 0, "widened": 0, "failed": 0}
    load_result: dict = {}

    try:
        # Step 1: 타겟 FK 캡처 + DROP
        logger.info("=" * 60)
        logger.info("Step 1: 타겟 FK 캡처 및 DROP")
        logger.info("=" * 60)
        fks = fk_mgr.capture()
        if fks:
            fk_drop = fk_mgr.drop_all(fks)

        # Step 1.5: bigint 범위 초과 컬럼 numeric 교정
        #   (소스 실제 값이 bigint(19자리) 초과 시 적재 out-of-range 방지)
        if cfg.get_bool("BIGINT_WIDEN", True):
            logger.info("=" * 60)
            logger.info("Step 1.5: bigint 범위 초과 컬럼 numeric 교정")
            logger.info("=" * 60)
            widener = BigintWidener(
                executor=executor,
                source_schema=source_schema,
                target_schema=target_schema,
            )
            bigint_widen = widener.widen_overflowing()

        # Step 2: DMS full-load 데이터 이전
        logger.info("=" * 60)
        logger.info("Step 2: DMS full-load 데이터 이전")
        logger.info("=" * 60)
        load_result = full_load.run(
            source_schema=source_schema,
            timeout=cfg.get_int("FULL_LOAD_TIMEOUT", 0),
        )
    finally:
        # Step 3: FK 재생성 - full-load 성공/실패와 무관하게 항상 원복 시도.
        #   (드랍만 하고 종료되면 타겟 스키마 무결성이 깨진 채 남기 때문)
        if fks:
            logger.info("=" * 60)
            logger.info("Step 3: 타겟 FK 재생성")
            logger.info("=" * 60)
            try:
                fk_recreate = fk_mgr.recreate(fks)
            except ForeignKeyManagerError as e:
                logger.error("FK 재생성 실패: %s", e)
        executor.close()

    return {
        "fk_drop": fk_drop,
        "bigint_widen": bigint_widen,
        "full_load": load_result,
        "fk_recreate": fk_recreate,
    }


def report_phase3(result: dict) -> int:
    """
    3차 파이프라인 결과를 요약 출력한다.

    Args:
        result: run_phase3 결과 dict

    Returns:
        종료 코드(full-load 실패 또는 FK 재생성 실패 시 2, 아니면 0)
    """
    fk_drop = result["fk_drop"]
    bigint_widen = result.get("bigint_widen", {})
    load = result["full_load"]
    fk_re = result["fk_recreate"]
    stats = load.get("table_stats", {})
    logger.info("=" * 60)
    logger.info("3차 파이프라인 완료")
    logger.info("=" * 60)
    logger.info(
        "  FK 드랍     : dropped=%d failed=%d",
        fk_drop["dropped"], fk_drop["failed"],
    )
    logger.info(
        "  bigint 교정 : checked=%d widened=%d failed=%d",
        bigint_widen.get("checked", 0),
        bigint_widen.get("widened", 0),
        bigint_widen.get("failed", 0),
    )
    logger.info(
        "  full-load   : status=%s 테이블 적재=%d 오류=%d (%.0fs)",
        load.get("status"),
        stats.get("loaded", 0),
        stats.get("errored", 0),
        load.get("elapsed_seconds", 0),
    )
    logger.info(
        "  FK 재생성   : recreated=%d failed=%d",
        fk_re["recreated"], fk_re["failed"],
    )
    failed = (
        not load.get("success")
        or stats.get("errored", 0) > 0
        or fk_re["failed"] > 0
    )
    return 2 if failed else 0
