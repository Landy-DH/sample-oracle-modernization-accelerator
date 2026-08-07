#!/usr/bin/env python3
"""
OMA Schema - 변환/이전 파이프라인 CLI(엔트리포인트)

작업 플로우:
  env 에서 oma 환경 배포 → DMS SC 프로젝트 생성 (선행, env 단계)
  → [1차] DMS SC 변환 + S3 산출 + apply changes(타겟 반영)
  → [2차] 산출물 다운로드 → 시퀀스 동기화 → 판별 → LLM 변환
  → [3차] FK 드랍 → DMS full-load 데이터 이전 → FK 재생성

이 파일은 인자 파싱/분기/보고만 담당하고, 실제 단계 로직은 pipeline.py 에 있다.
env/oma.properties는 사용하지 않는다(모두 시크릿 기반).
자격증명은 Secrets Manager 시크릿 "이름"으로만 참조한다.

변경 이력:
2026-08-05 | OMA Team | 전면 재작성(v2)
  - 시크릿 기반, 모듈형 DB 접속, DMS SC 1차 변환 + S3 압축 업로드로 재설계
  - 기존 5단계 파이프라인(제약 drop/full load 등)은 schema/bak 로 백업
2026-08-05 | OMA Team | 2차 파이프라인 추가(--phase2)
  - fetch → ddl_apply → sequence_sync → triage → llm_convert 오케스트레이션
2026-08-05 | OMA Team | 3차 파이프라인 추가(--phase3, DMS full-load 데이터 이전)
  - FK 캡처/드랍 → full-load replication task → FK 재생성 오케스트레이션
  - full-load 는 자식 테이블 선적재 시 FK 위반으로 실패하므로 FK 선드랍 필요
2026-08-05 | OMA Team | main.py 분리(500 line 초과) + 3차 preflight
  - 파이프라인 실행 함수를 pipeline.py 로 이관, main 은 CLI 만 담당
  - --phase3-preflight: 적재 전 엔드포인트 상태/접속 확인(사용자 승인용)
"""

import argparse
import logging
import os
import sys

# schema 디렉토리를 import 경로에 추가(config/db/steps/pipeline 접근)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pipeline  # noqa: E402
import pipeline_phase3  # noqa: E402
from config import Config, ConfigError  # noqa: E402
from steps.artifact_fetch import ArtifactFetchError  # noqa: E402
from steps.dms_full_load import DmsFullLoadError  # noqa: E402
from steps.dms_sc_convert import DmsScError  # noqa: E402
from steps.fk_manager import ForeignKeyManagerError  # noqa: E402
from steps.s3_export import S3ExportError  # noqa: E402
from steps.sequence_sync import SequenceSyncError  # noqa: E402
from steps.triage import TriageError  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("oma.schema")


def build_config(config_file, application_name) -> Config:
    """
    설정을 로드한다.

    Args:
        config_file: oma.properties 경로(None이면 기본)
        application_name: 프로젝트 섹션(None이면 파일 값)

    Returns:
        Config 인스턴스

    Raises:
        ConfigError: 로드 실패 시
    """
    cfg = Config(config_file=config_file, application_name=application_name)
    logger.info("프로젝트: %s", cfg.application_name)
    return cfg


def _parse_args() -> argparse.Namespace:
    """CLI 인자를 파싱한다."""
    parser = argparse.ArgumentParser(
        description="OMA Schema 변환/이전 파이프라인(1차 DMS SC / 2차 LLM / 3차 full-load)"
    )
    parser.add_argument(
        "--config", default=None, help="oma.properties 경로(기본: schema/oma.properties)"
    )
    parser.add_argument(
        "--app", default=None, help="프로젝트 섹션명(기본: properties의 APPLICATION_NAME)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="설정만 로드/검증하고 실행하지 않음(통합 점검용)",
    )
    parser.add_argument(
        "--phase2",
        action="store_true",
        help="2차 파이프라인(산출물 다운로드→시퀀스→판별→LLM 변환) 실행",
    )
    parser.add_argument(
        "--apply-changes",
        action="store_true",
        help="이미 변환된 모델을 타겟 DB에 반영(export-to-target 단독 실행)",
    )
    parser.add_argument(
        "--phase3-preflight",
        action="store_true",
        help="3차 사전 점검(엔드포인트 상태/접속 테스트)만 실행 - 적재/FK 변경 없음",
    )
    parser.add_argument(
        "--phase3",
        action="store_true",
        help="3차 파이프라인(preflight→FK 드랍→DMS full-load→FK 재생성) 실행",
    )
    return parser.parse_args()


def _phase_label(args: argparse.Namespace) -> str:
    """인자에 따른 파이프라인 라벨을 반환한다."""
    if args.apply_changes:
        return "apply changes(타겟 반영)"
    if args.phase3_preflight:
        return "3차 사전 점검(preflight)"
    if args.phase3:
        return "3차 full-load 데이터 이전"
    if args.phase2:
        return "2차 LLM 변환"
    return "1차 변환"


def _run_check(cfg: Config, args: argparse.Namespace) -> int:
    """설정 검증 모드(--check): 주요 키를 출력하고 종료한다."""
    logger.info("설정 검증 모드(--check): 실행하지 않고 종료")
    keys = [
        "AWS_REGION",
        "SOURCE_SCHEMA",
        "TARGET_SCHEMA",
        "SOURCE_SECRET_NAME",
        "TARGET_SECRET_NAME",
        "DMS_MIGRATION_PROJECT_ARN",
        "DMS_SC_S3_BUCKET",
    ]
    if args.phase2:
        keys += ["WORK_DIR", "BEDROCK_MODEL_ID", "BEDROCK_REGION"]
    if args.phase3 or args.phase3_preflight:
        keys += [
            "TARGET_DB_TYPE",
            "DMS_REPLICATION_INSTANCE",
            "DMS_SOURCE_ENDPOINT",
            "DMS_TARGET_ENDPOINT",
            "DMS_LOWERCASE_NAMES",
            "FULL_LOAD_TIMEOUT",
        ]
    for key in keys:
        logger.info("  %s = %s", key, cfg.get(key))
    return 0


def _run_apply_changes(cfg: Config) -> int:
    """apply changes(타겟 반영) 단독 실행."""
    try:
        apply_result = pipeline.run_apply_changes(cfg)
    except (ConfigError, DmsScError) as e:
        logger.error("apply changes 실패: %s", e)
        return 1
    logger.info("=" * 60)
    logger.info("apply changes 완료")
    logger.info("=" * 60)
    logger.info("  status  : %s", apply_result["apply_status"])
    logger.info("  schema  : %s", apply_result["target_schema"])
    logger.info("  elapsed : %ss", apply_result["elapsed_seconds"])
    return 0


def _run_phase1(cfg: Config) -> int:
    """1차 변환 파이프라인 실행 + 보고."""
    try:
        result = pipeline.run_pipeline(cfg)
    except (ConfigError, DmsScError, S3ExportError) as e:
        logger.error("파이프라인 실패: %s", e)
        return 1

    s3 = result["s3_export"]
    ddl_zip = s3.get("ddl_zip") or {}
    logger.info("=" * 60)
    logger.info("1차 목표 완료")
    logger.info("=" * 60)
    logger.info("  DMS SC elapsed : %ss", result["dms_sc"].get("elapsed_seconds"))
    logger.info("  산출물 prefix  : s3://%s/%s", s3.get("bucket"), s3.get("prefix"))
    logger.info("  변환 DDL(zip)  : %s", ddl_zip.get("s3_uri", "없음"))
    logger.info(
        "  action-items   : %d개, 전체 객체 %d개",
        len(s3.get("action_items", [])),
        s3.get("object_count", 0),
    )
    return 0


def _dispatch(cfg: Config, args: argparse.Namespace) -> int:
    """인자에 따라 해당 파이프라인을 실행하고 종료 코드를 반환한다."""
    if args.apply_changes:
        return _run_apply_changes(cfg)

    if args.phase3_preflight:
        try:
            result = pipeline_phase3.run_phase3_preflight(cfg)
        except (ConfigError, DmsFullLoadError) as e:
            logger.error("3차 사전 점검 실패: %s", e)
            return 1
        return pipeline_phase3.report_phase3_preflight(result)

    if args.phase2:
        try:
            result = pipeline.run_phase2(cfg)
        except (
            ConfigError,
            ArtifactFetchError,
            SequenceSyncError,
            TriageError,
        ) as e:
            logger.error("2차 파이프라인 실패: %s", e)
            return 1
        return pipeline.report_phase2(result)

    if args.phase3:
        try:
            result = pipeline_phase3.run_phase3(cfg)
        except (ConfigError, ForeignKeyManagerError, DmsFullLoadError) as e:
            logger.error("3차 파이프라인 실패: %s", e)
            return 1
        return pipeline_phase3.report_phase3(result)

    return _run_phase1(cfg)


def main() -> int:
    """
    엔트리포인트.

    Returns:
        프로세스 종료 코드(0=성공)
    """
    args = _parse_args()

    logger.info("=" * 60)
    logger.info("OMA Schema - %s 파이프라인", _phase_label(args))
    logger.info("=" * 60)

    try:
        cfg = build_config(args.config, args.app)
    except ConfigError as e:
        logger.error("설정 로드 실패: %s", e)
        return 1

    if args.check:
        return _run_check(cfg, args)

    return _dispatch(cfg, args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.info("사용자에 의해 중단됨")
        sys.exit(130)
    except Exception:  # noqa: BLE001
        logger.exception("예상치 못한 오류로 종료")
        sys.exit(1)
