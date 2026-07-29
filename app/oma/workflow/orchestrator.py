"""
워크플로우 오케스트레이터 모듈

전체 변환 파이프라인(Phase 1-7 + 사전점검)을 제어한다. 각 Phase를 순서대로
실행하고 체크포인트로 진행 상황을 저장해 중단 시 재시작을 지원한다.

Phase 구성:
  0. preflight    - 사전 점검 스캔 (OGNL/${}변수/미지별칭 리포트)
  1. dictionary   - 타겟 스키마 딕셔너리 생성
  2. copy_mappers - 소스 매퍼 복사 + 특수변수/OGNL 선치환
  3. fragment     - 매퍼를 SQL ID별 조각으로 분할
  4. conversion   - LLM 변환 + 조각별 리포트 저장 + TC 생성
  5. merge        - 변환 조각을 원본 구조로 재조립
  6. validation   - 소스/타겟 실행 결과 검증 (Java)
  7. copy_target  - 변환 결과를 타겟 워크스페이스로 복사

의존성은 주입 가능해 테스트가 용이하다. 각 Phase는 독립 메서드로 분리하고,
개별 항목 실패는 건너뛰며 진행한다 (전체 중단 방지).

변경 이력:
2026-07-27 | OMA Team | 초기 생성
  - WorkflowOrchestrator: run(phases)/개별 phase 메서드, 체크포인트 연동
  - 변환 리포트 저장(converted/*.xml, *.report.json, conversion-summary.json)
  - 특수변수 치환/preflight/딕셔너리/분할/변환/병합/검증 통합

2026-07-28 | OMA Team | 버그 수정: 조각 파일명 충돌
  - 원인: 조각 식별자가 `{mapper}__{sql_id}` 라 statement_type이 빠져,
    <resultMap>과 <select>가 같은 id를 공유하는 MyBatis 표준 패턴에서
    두 조각이 같은 파일명으로 충돌 → 하나가 덮어써짐. 병합 시 resultMap
    소실 + select 중복 → MyBatis "Could not find result map" 로딩 실패로
    검증 전체(507건)가 연쇄 실패(예: MainOrderMapper).
  - 수정: 조각 식별자에 statement_type을 포함하는 _fragment_id 헬퍼 도입,
    저장(206)/체크포인트키(231)/원본로드(313)/변환로드(336) 4곳 통일.

2026-07-28 | OMA Team | Phase4 변환 병렬화 (MAX_WORKERS)
  - 원인: phase_conversion이 순차 for-loop라 507조각 LLM 변환에 과도한
    시간 소요. MAX_WORKERS 설정은 있으나 어디서도 참조되지 않는 dead config.
  - 수정: ThreadPoolExecutor(max_workers=MAX_WORKERS)로 converter.convert
    (LLM 호출)만 워커에서 병렬 실행. 체크포인트 기록/파일 저장/summary 집계는
    as_completed로 메인 스레드에서 순차 처리(CheckpointManager는 thread-safe
    아님). RPM은 LLMClient._rate_lock이 직렬 보장. 단일워커/소량은 기존 경로.
"""

import json
import logging
import os
import shutil
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from oma.converter.converter import Converter
from oma.dictionary.builder import DictionaryBuilder
from oma.fragmenter.splitter import Fragment, MapperSplitter
from oma.merger.combiner import MapperCombiner
from oma.preflight.guide import PreflightGuide
from oma.preflight.scanner import MapperScanner
from oma.preprocess.special_variables import SpecialVariableSubstitutor
from oma.utils.config import Config
from oma.workflow.checkpoint import CheckpointManager

logger = logging.getLogger(__name__)

# Phase 이름 (체크포인트 PHASES와 일치)
PHASE_DICTIONARY = "phase1_dictionary"
PHASE_COPY = "phase2_copy_mappers"
PHASE_FRAGMENT = "phase3_fragment"
PHASE_CONVERSION = "phase4_conversion"
PHASE_MERGE = "phase5_merge"
PHASE_VALIDATION = "phase6_validation"
PHASE_COPY_TARGET = "phase7_copy_target"


class WorkflowOrchestrator:
    """
    전체 변환 워크플로우 오케스트레이터

    Attributes:
        config: Config 객체
        checkpoint: CheckpointManager
        work_dir: PROJECT_WORK_DIR
    """

    def __init__(
        self,
        config: Config,
        checkpoint: Optional[CheckpointManager] = None,
        target_plugin: Optional[Any] = None,
        converter: Optional[Converter] = None,
        validation_orchestrator: Optional[Any] = None,
    ) -> None:
        """
        초기화 (핵심 협력자 주입 가능)

        Args:
            config: Config 객체
            checkpoint: 체크포인트 관리자 (없으면 CHECKPOINT_PATH로 생성)
            target_plugin: 타겟 DB 플러그인 (Phase1 딕셔너리용)
            converter: Converter (Phase4용)
            validation_orchestrator: ValidationOrchestrator (Phase6용)
        """
        self.config = config
        self.work_dir = config.get("PROJECT_WORK_DIR")
        self.mapper_work = config.get("MAPPER_WORK_DIR")
        self.checkpoint = checkpoint or CheckpointManager(
            config.get("CHECKPOINT_PATH", os.path.join(self.work_dir, ".checkpoint.json"))
        )
        self._target_plugin = target_plugin
        self._converter = converter
        self._validation = validation_orchestrator
        self._splitter = MapperSplitter(config)
        self._combiner = MapperCombiner()

    # ------------------------------------------------------------------ 제어

    def run(self, phases: Optional[List[str]] = None) -> None:
        """
        지정 Phase들을 순서대로 실행한다 (이미 완료된 Phase는 건너뜀).

        Args:
            phases: 실행할 Phase 목록 (없으면 전체)
        """
        phase_map = {
            PHASE_DICTIONARY: self.phase_dictionary,
            PHASE_COPY: self.phase_copy_mappers,
            PHASE_FRAGMENT: self.phase_fragment,
            PHASE_CONVERSION: self.phase_conversion,
            PHASE_MERGE: self.phase_merge,
            PHASE_VALIDATION: self.phase_validation,
            PHASE_COPY_TARGET: self.phase_copy_target,
        }
        targets = phases or list(phase_map.keys())

        for phase in targets:
            if self.checkpoint.is_completed(phase):
                logger.info("Phase 완료됨, 건너뜀: %s", phase)
                continue
            logger.info("=== Phase 시작: %s ===", phase)
            self.checkpoint.mark_phase_started(phase)
            phase_map[phase]()
            self.checkpoint.mark_phase_completed(phase)
            logger.info("=== Phase 완료: %s ===", phase)

    def preflight(self) -> Dict[str, Any]:
        """
        사전 점검 스캔을 실행하고 리포트를 저장한다 (Phase 아님, 선택적 선행).

        Returns:
            preflight 리포트 dict
        """
        source_ws = self.config.get("SOURCE_WORKSPACE")
        exclude = frozenset(self.config.get_list("MAPPER_EXCLUDE_DIRS", default=[]))
        scanner = MapperScanner(exclude_dirs=exclude)
        report = scanner.scan_dir(source_ws)
        report_dict = MapperScanner.to_dict(report)

        report_dir = self.config.get("REPORT_DIR")
        os.makedirs(report_dir, exist_ok=True)
        # 1) 원시 검출 결과
        self._write_json(os.path.join(report_dir, "preflight-report.json"), report_dict)
        # 2) 값 채울 설정 스텁 (special_variables.json 형식 호환)
        self._write_json(
            os.path.join(report_dir, "preflight-config-stubs.json"),
            PreflightGuide.build_config_stubs(report),
        )
        # 3) 사람이 읽는 조치 가이드 (어디에 무엇을 반영할지)
        guide_path = os.path.join(report_dir, "preflight-guide.md")
        with open(guide_path, "w", encoding="utf-8") as f:
            f.write(PreflightGuide.build_markdown_guide(report))

        logger.info(
            "Pre-flight: 매퍼 %d, OGNL %d종, ${} %d종, 미지별칭 %d종, 파싱오류 %d "
            "→ 가이드: %s",
            report.mapper_count, len(report.ognl_methods),
            len(report.dollar_variables), len(report.unknown_type_aliases),
            len(report.parse_errors), guide_path,
        )
        return report_dict

    # ---------------------------------------------------------------- Phases

    def phase_dictionary(self) -> None:
        """Phase 1: 타겟 스키마 딕셔너리 생성."""
        builder = DictionaryBuilder(self.config, target=self._target_plugin)
        builder.build()

    def phase_copy_mappers(self) -> None:
        """
        Phase 2: 소스 매퍼를 original로 복사하고 특수변수/OGNL 선치환한다.
        """
        source_ws = self.config.get("SOURCE_WORKSPACE")
        original_dir = os.path.join(self.mapper_work, "original")

        # 매퍼 파일만 골라 복사 (구조 유지, 제외 디렉토리 반영)
        mapper_files = self._splitter.find_mapper_files(source_ws)
        os.makedirs(original_dir, exist_ok=True)
        for src in mapper_files:
            rel = os.path.relpath(src, source_ws)
            dst = os.path.join(original_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        logger.info("매퍼 복사: %d개 → %s", len(mapper_files), original_dir)

        # 특수변수/OGNL 선치환 (oracle 기준; 실전은 config로 제어)
        substitutor = SpecialVariableSubstitutor(
            dialect=self.config.get("SOURCE_DB_TYPE", "oracle"),
            enable_ognl=self.config.get_bool("SUBSTITUTE_OGNL", True),
        )
        substitutor.substitute_directory(original_dir)

    def phase_fragment(self) -> None:
        """Phase 3: original 매퍼를 조각으로 분할하고 mapping.json 저장."""
        original_dir = os.path.join(self.mapper_work, "original")
        fragmented_dir = os.path.join(self.mapper_work, "fragmented")
        os.makedirs(fragmented_dir, exist_ok=True)

        # 상대경로(source_file) 기준을 original_dir로 맞춰야 병합 단계에서 경로가 일치
        self._splitter.source_workspace = original_dir
        results = self._splitter.split_workspace(original_dir)
        mapping = MapperSplitter.build_mapping(results)
        self._write_json(os.path.join(fragmented_dir, "mapping.json"), mapping)

        for result in results.values():
            for frag in result.fragments:
                fname = f"{self._fragment_id(frag.mapper_name, frag.sql_id, frag.statement_type)}.xml"
                with open(os.path.join(fragmented_dir, fname), "w", encoding="utf-8") as f:
                    f.write(frag.content)
        logger.info("분할: 매퍼 %d → 조각 %d",
                    mapping["mapper_count"], mapping["fragment_count"])

    def phase_conversion(self) -> None:
        """
        Phase 4: 조각을 LLM 변환하고 변환 조각/리포트/TC를 저장한다.

        MAX_WORKERS 개의 워커 스레드로 LLM 변환을 병렬 실행한다. 느린 부분
        (converter.convert = LLM 호출)만 스레드에서 수행하고, 체크포인트 기록·
        파일 저장·summary 집계는 메인 스레드에서 완료 순서대로 처리한다
        (CheckpointManager는 thread-safe하지 않으므로). RPM 제한은 LLMClient가
        락으로 직렬 강제한다.

        체크포인트로 완료 조각을 건너뛰어 재시작을 지원한다.
        """
        if self._converter is None:
            raise ValueError("Converter가 주입되지 않았습니다 (Phase4 필요)")

        fragmented_dir = os.path.join(self.mapper_work, "fragmented")
        converted_dir = os.path.join(self.mapper_work, "converted")
        testcase_dir = self.config.get("TESTCASE_DIR")
        os.makedirs(converted_dir, exist_ok=True)
        os.makedirs(testcase_dir, exist_ok=True)

        fragments = self._load_fragments(fragmented_dir)
        summary = {"success": 0, "failed": 0, "skipped": 0}

        # 완료 조각은 미리 제외 (재시작 지원)
        pending = [
            (self._fragment_id(f.mapper_name, f.sql_id, f.statement_type), f)
            for f in fragments
        ]
        pending = [
            (fid, f) for fid, f in pending
            if not self.checkpoint.is_fragment_completed(fid)
        ]

        max_workers = max(1, self.config.get_int("MAX_WORKERS", 1))
        logger.info(
            "변환 시작: 대상 %d개, 워커 %d개", len(pending), max_workers
        )

        if max_workers == 1 or len(pending) <= 1:
            # 단일 워커 경로 (테스트/소량)
            for frag_id, frag in pending:
                self._convert_and_record(
                    frag_id, frag, converted_dir, testcase_dir, summary
                )
        else:
            # LLM 호출만 병렬, 결과 반영은 메인 스레드에서 순차 처리
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {
                    executor.submit(self._converter.convert, frag): (frag_id, frag)
                    for frag_id, frag in pending
                }
                for future in as_completed(future_map):
                    frag_id, frag = future_map[future]
                    self._record_conversion(
                        frag_id, future, converted_dir, testcase_dir, summary
                    )

        self._write_json(
            os.path.join(self.config.get("REPORT_DIR"), "conversion-summary.json"),
            summary,
        )
        logger.info("변환 완료: %s", summary)

    def _convert_and_record(
        self, frag_id: str, frag: Fragment, converted_dir: str,
        testcase_dir: str, summary: Dict[str, int],
    ) -> None:
        """단일 조각을 변환하고 결과를 반영한다 (단일 워커 경로)."""
        try:
            result = self._converter.convert(frag)
            self._save_conversion(converted_dir, testcase_dir, frag_id, result)
            summary[result.status] = summary.get(result.status, 0) + 1
            self.checkpoint.mark_fragment_completed(frag_id)
        except Exception as e:  # 개별 실패는 기록 후 계속
            logger.error("변환 실패: %s - %s", frag_id, e)
            self.checkpoint.mark_fragment_failed(frag_id, str(e), retry_count=0)
            summary["failed"] += 1

    def _record_conversion(
        self, frag_id: str, future: "Future", converted_dir: str,
        testcase_dir: str, summary: Dict[str, int],
    ) -> None:
        """완료된 변환 future의 결과를 메인 스레드에서 반영한다."""
        try:
            result = future.result()
            self._save_conversion(converted_dir, testcase_dir, frag_id, result)
            summary[result.status] = summary.get(result.status, 0) + 1
            self.checkpoint.mark_fragment_completed(frag_id)
        except Exception as e:  # 개별 실패는 기록 후 계속
            logger.error("변환 실패: %s - %s", frag_id, e)
            self.checkpoint.mark_fragment_failed(frag_id, str(e), retry_count=0)
            summary["failed"] += 1

    def phase_merge(self) -> None:
        """Phase 5: 변환된 조각을 원본 매퍼 구조로 재조립한다."""
        original_dir = os.path.join(self.mapper_work, "original")
        converted_dir = os.path.join(self.mapper_work, "converted")
        merged_dir = os.path.join(self.mapper_work, "merged")
        os.makedirs(merged_dir, exist_ok=True)

        # mapping.json으로 매퍼별 조각을 모아 병합
        mapping = self._read_json(
            os.path.join(self.mapper_work, "fragmented", "mapping.json")
        )
        merged_count = 0
        for source_file, info in mapping.get("mappers", {}).items():
            frags = self._load_converted_fragments(
                converted_dir, info["mapper_name"], info["fragments"]
            )
            if not frags:
                continue
            original_path = os.path.join(original_dir, source_file)
            output_path = os.path.join(merged_dir, source_file)
            try:
                self._combiner.merge_to_file(original_path, frags, output_path)
                merged_count += 1
            except Exception as e:
                logger.error("병합 실패: %s - %s", source_file, e)
        logger.info("병합 완료: %d개 매퍼", merged_count)

    def phase_validation(self) -> None:
        """Phase 6: 검증 오케스트레이터로 소스/타겟 결과를 비교 검증한다."""
        if self._validation is None:
            logger.warning("ValidationOrchestrator 미주입 - Phase6 건너뜀")
            return
        self._validation.validate_all(self.config.get("TESTCASE_DIR"))

    def phase_copy_target(self) -> None:
        """Phase 7: 병합된 매퍼를 타겟 워크스페이스로 복사한다."""
        merged_dir = os.path.join(self.mapper_work, "merged")
        target_ws = self.config.get("TARGET_WORKSPACE")
        if not target_ws:
            logger.warning("TARGET_WORKSPACE 미설정 - Phase7 건너뜀")
            return
        os.makedirs(target_ws, exist_ok=True)
        copied = 0
        for dirpath, _dirs, files in os.walk(merged_dir):
            for fname in files:
                if not fname.endswith(".xml"):
                    continue
                src = os.path.join(dirpath, fname)
                rel = os.path.relpath(src, merged_dir)
                dst = os.path.join(target_ws, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                copied += 1
        logger.info("타겟 복사: %d개 → %s", copied, target_ws)

    # ------------------------------------------------------------- 내부 헬퍼

    def _load_fragments(self, fragmented_dir: str) -> List[Fragment]:
        """fragmented 디렉토리에서 조각 XML을 Fragment로 로드한다."""
        mapping = self._read_json(os.path.join(fragmented_dir, "mapping.json"))
        fragments: List[Fragment] = []
        for source_file, info in mapping.get("mappers", {}).items():
            for fmeta in info["fragments"]:
                fname = f"{self._fragment_id(info['mapper_name'], fmeta['sql_id'], fmeta['statement_type'])}.xml"
                path = os.path.join(fragmented_dir, fname)
                if not os.path.isfile(path):
                    continue
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                fragments.append(Fragment(
                    mapper_name=info["mapper_name"],
                    namespace=info.get("namespace"),
                    sql_id=fmeta["sql_id"],
                    statement_type=fmeta["statement_type"],
                    content=content,
                    source_file=source_file,
                    has_id=fmeta.get("has_id", True),
                ))
        return fragments

    def _load_converted_fragments(
        self, converted_dir: str, mapper_name: str, fragments_meta: List[Dict[str, Any]]
    ) -> List[Fragment]:
        """converted 디렉토리에서 변환된 조각을 Fragment로 로드한다."""
        result: List[Fragment] = []
        for fmeta in fragments_meta:
            fname = f"{self._fragment_id(mapper_name, fmeta['sql_id'], fmeta['statement_type'])}.xml"
            path = os.path.join(converted_dir, fname)
            if not os.path.isfile(path):
                continue
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            result.append(Fragment(
                mapper_name=mapper_name, namespace=None,
                sql_id=fmeta["sql_id"], statement_type=fmeta["statement_type"],
                content=content, source_file="", has_id=fmeta.get("has_id", True),
            ))
        return result

    def _save_conversion(
        self, converted_dir: str, testcase_dir: str, frag_id: str, result: Any
    ) -> None:
        """변환 결과(조각 XML + 리포트 + TC)를 저장한다."""
        # 변환된 조각 XML
        with open(os.path.join(converted_dir, f"{frag_id}.xml"), "w", encoding="utf-8") as f:
            f.write(result.converted_sql)
        # 조각별 리포트
        report = {
            "status": result.status,
            "strategy": result.strategy,
            "type_casts": result.type_casts,
            "syntax_changes": result.syntax_changes,
            "warnings": result.warnings,
            "param_mappings": result.param_mappings,
            "manual_review_required": result.manual_review_required,
            "analysis": result.analysis,
        }
        self._write_json(
            os.path.join(converted_dir, f"{frag_id}.report.json"), report
        )
        # 테스트 케이스
        for tc in result.test_cases:
            tc_id = tc.get("test_case_id", frag_id)
            self._write_json(os.path.join(testcase_dir, f"{tc_id}.json"), tc)

    @staticmethod
    def _fragment_id(mapper_name: str, sql_id: str, statement_type: str) -> str:
        """
        조각 고유 식별자를 만든다 (파일명/체크포인트 키 공통).

        <resultMap>과 <select>처럼 statement_type이 다른데 id(sql_id)가 같은
        MyBatis 표준 패턴에서 조각 파일명이 충돌하지 않도록 statement_type을
        포함한다. 예: MainOrderMapper__resultMap__retrieveMainOrderList

        Args:
            mapper_name: 매퍼 이름
            sql_id: statement id (또는 합성 id)
            statement_type: 태그명 (select/insert/.../resultMap/sql 등)

        Returns:
            충돌 없는 조각 식별자 문자열
        """
        return f"{mapper_name}__{statement_type}__{sql_id}"

    @staticmethod
    def _write_json(path: str, data: Any) -> None:
        """JSON 파일로 저장한다 (디렉토리 자동 생성)."""
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    @staticmethod
    def _read_json(path: str) -> Dict[str, Any]:
        """JSON 파일을 로드한다."""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
