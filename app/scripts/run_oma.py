"""
OMA 메인 실행 스크립트 (CLI 진입점)

전체 변환 파이프라인을 명령줄에서 실행한다. config를 로드하고 필요한 협력자
(타겟 플러그인, Converter, ValidationOrchestrator)를 조립해 WorkflowOrchestrator에
주입한 뒤, 지정한 Phase를 실행한다.

사용 예:
  python3.11 scripts/run_oma.py --preflight               # 사전 점검만
  python3.11 scripts/run_oma.py --phase all               # 전체 실행
  python3.11 scripts/run_oma.py --phase dictionary        # 특정 Phase만
  python3.11 scripts/run_oma.py --phase convert,merge     # 여러 Phase
  python3.11 scripts/run_oma.py --config custom.properties

Phase 별칭: preflight/dictionary/copy/fragment/convert/merge/validate/copy_target/all

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - argparse CLI, config 로드, 협력자 지연 조립, --preflight/--phase 실행
  - 실행 협력자는 실제 필요한 Phase에서만 생성 (DB/Bedrock 불필요 Phase는 스킵)
"""

import argparse
import logging
import os
import sys

# 프로젝트 루트를 import 경로에 추가 (scripts/ 에서 실행 대응)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from oma.utils.config import Config  # noqa: E402
from oma.utils.logger import setup_logger  # noqa: E402
from oma.workflow.orchestrator import (  # noqa: E402
    PHASE_CONVERSION,
    PHASE_COPY,
    PHASE_COPY_TARGET,
    PHASE_DICTIONARY,
    PHASE_FRAGMENT,
    PHASE_MERGE,
    PHASE_VALIDATION,
    WorkflowOrchestrator,
)

logger = logging.getLogger("run_oma")

# CLI 별칭 → 정식 Phase 이름
_PHASE_ALIASES = {
    "dictionary": PHASE_DICTIONARY,
    "copy": PHASE_COPY,
    "fragment": PHASE_FRAGMENT,
    "convert": PHASE_CONVERSION,
    "merge": PHASE_MERGE,
    "validate": PHASE_VALIDATION,
    "copy_target": PHASE_COPY_TARGET,
}
_ALL_PHASES = [
    PHASE_DICTIONARY, PHASE_COPY, PHASE_FRAGMENT, PHASE_CONVERSION,
    PHASE_MERGE, PHASE_VALIDATION, PHASE_COPY_TARGET,
]
# 협력자별로 필요한 Phase
_NEEDS_TARGET = {PHASE_DICTIONARY}
_NEEDS_CONVERTER = {PHASE_CONVERSION}
_NEEDS_VALIDATION = {PHASE_VALIDATION}


def parse_phases(phase_arg: str) -> list:
    """
    --phase 인자를 정식 Phase 목록으로 변환한다.

    Args:
        phase_arg: 'all' 또는 콤마 구분 별칭 목록

    Returns:
        정식 Phase 이름 리스트

    Raises:
        ValueError: 알 수 없는 별칭
    """
    if phase_arg == "all":
        return list(_ALL_PHASES)
    phases = []
    for token in phase_arg.split(","):
        token = token.strip()
        if token not in _PHASE_ALIASES:
            raise ValueError(
                f"알 수 없는 phase: {token} (유효: {list(_PHASE_ALIASES)} 또는 all)"
            )
        phases.append(_PHASE_ALIASES[token])
    return phases


def build_orchestrator(config: Config, phases: list) -> WorkflowOrchestrator:
    """
    실행할 Phase에 필요한 협력자만 조립해 오케스트레이터를 만든다.

    DB/Bedrock 연결은 해당 Phase가 포함될 때만 생성한다 (불필요한 연결 회피).

    Args:
        config: Config 객체
        phases: 실행할 Phase 목록

    Returns:
        구성된 WorkflowOrchestrator
    """
    phase_set = set(phases)
    target_plugin = None
    converter = None
    validation = None

    # 시크릿/자격증명은 필요할 때만 조회
    if phase_set & (_NEEDS_TARGET | _NEEDS_VALIDATION):
        target_plugin = _build_target_plugin(config)

    if phase_set & _NEEDS_CONVERTER:
        converter = _build_converter(config)

    if phase_set & _NEEDS_VALIDATION:
        validation = _build_validation(config)

    return WorkflowOrchestrator(
        config,
        target_plugin=target_plugin,
        converter=converter,
        validation_orchestrator=validation,
    )


def _build_target_plugin(config: Config):
    """타겟 DB 플러그인을 생성한다 (Phase1/6용)."""
    from oma.plugins.factory import create_target
    logger.info("타겟 DB 플러그인 생성")
    return create_target(config)


def _build_converter(config: Config):
    """Converter를 생성한다 (Phase4용)."""
    from oma.converter.converter import Converter
    from oma.converter.llm_client import LLMClient
    from oma.converter.sql_analyzer import SqlAnalyzer
    from oma.dictionary.loader import DictionaryLoader

    loader = DictionaryLoader(config.get("SCHEMA_DICT_PATH"))
    logger.info("Converter 생성 (LLM + 딕셔너리)")
    return Converter(
        LLMClient(config), loader, SqlAnalyzer(config),
        source_type=config.get("SOURCE_DB_TYPE", "oracle"),
        target_type=config.get("TARGET_DB_TYPE", "postgres"),
    )


def _build_validation(config: Config):
    """ValidationOrchestrator를 생성한다 (Phase6용)."""
    from oma.plugins.factory import create_source, create_target
    from oma.validation.orchestrator import ValidationOrchestrator
    from oma.utils.secrets import SecretsManager

    manager = SecretsManager(region=config.get("AWS_REGION"))
    use_secrets = config.get_bool("USE_SECRETS_MANAGER", False)
    if use_secrets:
        # 검증은 실제 서비스 환경을 가정 → service 계정으로 실행 (admin 아님)
        source_secret = config.get("SOURCE_SERVICE_SECRET") or config.get("SOURCE_SECRET_NAME")
        target_secret = config.get("TARGET_SERVICE_SECRET") or config.get("TARGET_SECRET_NAME")
        logger.info("검증 계정: source=%s, target=%s (service)", source_secret, target_secret)
        source_creds = manager.get_secret(source_secret)
        target_creds = manager.get_secret(target_secret)
    else:
        # 로컬 config 기반 (개발용) — factory와 동일 키 매핑을 재사용
        source_creds = create_source(config).credentials
        target_creds = create_target(config).credentials

    logger.info("ValidationOrchestrator 생성")
    return ValidationOrchestrator.from_config(config, source_creds, target_creds)


def main(argv=None) -> int:
    """
    CLI 진입점.

    Args:
        argv: 인자 리스트 (테스트용). None이면 sys.argv 사용

    Returns:
        종료 코드 (0 성공)
    """
    parser = argparse.ArgumentParser(
        description="OMA - Oracle Migration Assistant (앱 변환)"
    )
    parser.add_argument(
        "--config", default="oma.properties", help="설정 파일 경로"
    )
    parser.add_argument(
        "--phase", default="all",
        help="실행할 Phase (all 또는 콤마 구분: "
             "dictionary,copy,fragment,convert,merge,validate,copy_target)",
    )
    parser.add_argument(
        "--preflight", action="store_true",
        help="사전 점검 스캔만 실행하고 종료",
    )
    parser.add_argument(
        "--retry-failed", action="store_true",
        help="체크포인트의 실패 조각만 재시도 (Phase4)",
    )
    args = parser.parse_args(argv)

    if not os.path.isfile(args.config):
        print(f"[ERROR] 설정 파일을 찾을 수 없습니다: {args.config}", file=sys.stderr)
        return 1

    config = Config(args.config)
    setup_logger("oma", config)
    setup_logger("run_oma", config)

    logger.info("=" * 50)
    logger.info("OMA 실행 시작 (project=%s)", config.get("APPLICATION_NAME"))
    logger.info("=" * 50)

    # --preflight: 스캔만
    if args.preflight:
        orch = WorkflowOrchestrator(config)
        report = orch.preflight()
        logger.info(
            "Pre-flight 완료: 매퍼 %d, OGNL %d종, ${} %d종, 미지별칭 %d종",
            report["mapper_count"], len(report["ognl_methods"]),
            len(report["dollar_variables"]), len(report["unknown_type_aliases"]),
        )
        return 0

    try:
        phases = parse_phases(args.phase)
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    orch = build_orchestrator(config, phases)

    if args.retry_failed:
        retryable = orch.checkpoint.get_retryable_failures()
        logger.info("재시도 대상 실패 조각: %d개", len(retryable))

    orch.run(phases=phases)
    logger.info("OMA 실행 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
