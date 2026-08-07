"""
DMS Schema Conversion 1차 변환 스텝

DMS SC 엔진으로 Oracle 스키마를 PostgreSQL DDL로 규칙 기반 변환하고,
변환 결과 스크립트를 프로젝트에 연결된 S3로 export 한다.

1차 목표 범위(사용자 정의):
  - S3 산출물 생성(export-as-script) + 평가 리포트
  - 마지막에 apply changes(export-to-target)로 변환 DDL을 타겟 DB에 반영한다.
    (정리용 DROP 포함 전체 스크립트를 DMS 엔진이 직접 반영 → 오브젝트 생성)

DMS SC 흐름:
  0. start-extension-pack-association     (최초 1회, 이미 있으면 skip)
  1. start-metadata-model-import          (Origin=SOURCE, Oracle 메타 로드)
  2. start-metadata-model-conversion      (Oracle → PostgreSQL 변환)
  3. start-metadata-model-export-as-script(Origin=TARGET → S3 스크립트)
  4. start-metadata-model-assessment      (평가 리포트)
  5. start-metadata-model-export-to-target(apply changes, 타겟 DB 반영)

full-path selection rule("explicit")을 사용해 콘솔 초기화 없이 API로
스키마 단위 변환을 수행한다.

설계:
  - 프로젝트 ARN은 config에서 주입(자동 생성하지 않음).
  - Oracle 객체 수는 주입된 DBExecutor(source)로 조회 → 적응형 타임아웃.
  - boto3 dms 클라이언트는 지연 생성.

변경 이력:
2026-08-05 | OMA Team | 초기 생성
  - DmsScConverter.run(): ext→import→convert→export(script)→assess
  - export-to-target 미수행(S3 산출물만), 프로젝트 ARN 주입형
2026-08-05 | OMA Team | apply changes 추가
  - run(apply_to_target=True): assess 후 export-to-target 로 타겟 DB 반영
  - 오브젝트 생성을 DMS 엔진이 담당(2차 ddl_apply 는 LLM 구문 전용)
"""

import json
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 완료로 간주하는 상태 값
_DONE_OK = ("SUCCESSFUL", "SUCCESS", "COMPLETED")
# 진행 중으로 간주하는 상태 값
_RUNNING = ("RUNNING", "IN_PROGRESS", "CREATING")


class DmsScError(Exception):
    """DMS SC 변환 오류."""


class DmsScConverter:
    """
    DMS SC 1차 변환 실행기.

    Attributes:
        project_arn: DMS 마이그레이션 프로젝트 ARN
        region: AWS region
        s3_bucket: 프로젝트 연결 S3 버킷
    """

    def __init__(
        self,
        project_arn: str,
        region: str,
        s3_bucket: str,
        poll_interval: int = 15,
        convert_number_to_bigint: bool = True,
        dms_client: Optional[Any] = None,
    ) -> None:
        """
        Args:
            project_arn: DMS 마이그레이션 프로젝트 ARN
            region: AWS region
            s3_bucket: 산출물 S3 버킷
            poll_interval: 상태 폴링 주기(초)
            convert_number_to_bigint: Oracle NUMBER → BIGINT 설정 적용 여부
            dms_client: 주입할 boto3 dms 클라이언트(선택, 테스트용)
        """
        self.project_arn = project_arn
        self.region = region
        self.s3_bucket = s3_bucket
        self.poll_interval = poll_interval
        self.convert_number_to_bigint = convert_number_to_bigint
        self._dms = dms_client

    def _client(self) -> Any:
        """
        boto3 dms 클라이언트를 지연 생성/반환한다.

        Returns:
            dms 클라이언트

        Raises:
            DmsScError: boto3 임포트 실패 시
        """
        if self._dms is not None:
            return self._dms
        try:
            import boto3
        except ImportError as e:
            raise DmsScError(f"boto3 임포트 실패: {e}") from e
        self._dms = boto3.client("dms", region_name=self.region)
        return self._dms

    def _wait_for(
        self,
        describe_fn: Any,
        req_id: str,
        label: str,
        start_time: float,
        timeout: int,
    ) -> str:
        """
        DMS describe API를 완료/타임아웃까지 폴링한다.

        Args:
            describe_fn: 상태 조회 함수(dms.describe_*)
            req_id: 요청 식별자
            label: 로깅 라벨
            start_time: 시작 시각(time.time())
            timeout: 최대 대기 초(0 이하면 무제한)

        Returns:
            마지막 상태 문자열
        """
        status = "RUNNING"
        while status in _RUNNING:
            if timeout > 0 and (time.time() - start_time) >= timeout:
                logger.warning("%s 타임아웃(%ds 초과)", label, timeout)
                break
            time.sleep(self.poll_interval)
            desc = describe_fn(
                MigrationProjectIdentifier=self.project_arn,
                Filters=[{"Name": "request-id", "Values": [req_id]}],
            )
            reqs = desc.get("Requests", [])
            if reqs:
                status = reqs[0].get("Status", "UNKNOWN")
                logger.info(
                    "%s 상태: %s (%.0fs 경과)",
                    label,
                    status,
                    time.time() - start_time,
                )
        return status

    def _apply_bigint_setting(self, dms: Any) -> None:
        """
        ConvertNumberToBigint=true를 변환 설정에 적용한다.

        Args:
            dms: dms 클라이언트
        """
        try:
            resp = dms.describe_conversion_configuration(
                MigrationProjectIdentifier=self.project_arn
            )
            config = json.loads(resp["ConversionConfiguration"])
            modified = False
            for key in config:
                section = config[key]
                if isinstance(section, dict) and "ConvertNumberToBigint" in section:
                    if not section["ConvertNumberToBigint"]:
                        section["ConvertNumberToBigint"] = True
                        modified = True
            if modified:
                dms.modify_conversion_configuration(
                    MigrationProjectIdentifier=self.project_arn,
                    ConversionConfiguration=json.dumps(config),
                )
                logger.info("ConvertNumberToBigint=true 적용")
            else:
                logger.info("ConvertNumberToBigint 이미 활성화됨")
        except Exception as e:  # noqa: BLE001 - 설정 실패는 치명적이지 않음
            logger.warning("BIGINT 변환 설정 적용 실패(무시): %s", e)

    def _resolve_servers(self, dms: Any) -> Dict[str, str]:
        """
        프로젝트의 소스/타겟 데이터 프로바이더 서버명을 조회한다.

        Args:
            dms: dms 클라이언트

        Returns:
            {"source": <server>, "target": <server>}

        Raises:
            DmsScError: 프로젝트/프로바이더 조회 실패 시
        """
        try:
            proj_desc = dms.describe_migration_projects(
                Filters=[
                    {
                        "Name": "migration-project-identifier",
                        "Values": [self.project_arn],
                    }
                ]
            )
            proj = proj_desc["MigrationProjects"][0]
            src_dp_arn = proj["SourceDataProviderDescriptors"][0]["DataProviderArn"]
            tgt_dp_arn = proj["TargetDataProviderDescriptors"][0]["DataProviderArn"]

            src_dp = dms.describe_data_providers(
                Filters=[{"Name": "data-provider-arn", "Values": [src_dp_arn]}]
            )["DataProviders"][0]
            tgt_dp = dms.describe_data_providers(
                Filters=[{"Name": "data-provider-arn", "Values": [tgt_dp_arn]}]
            )["DataProviders"][0]

            source_server = src_dp["Settings"]["OracleSettings"]["ServerName"]
            target_server = tgt_dp["Settings"]["PostgreSqlSettings"]["ServerName"]
            return {"source": source_server, "target": target_server}
        except (KeyError, IndexError) as e:
            raise DmsScError(f"데이터 프로바이더 서버명 조회 실패: {e}") from e

    @staticmethod
    def _selection_rule(server: str, schema: str) -> str:
        """
        full-path explicit selection rule(JSON 문자열)을 만든다.

        Args:
            server: 데이터 프로바이더 ServerName
            schema: 스키마명(소스=대문자, 타겟=소문자로 호출자가 전달)

        Returns:
            SelectionRules JSON 문자열
        """
        return json.dumps(
            {
                "rules": [
                    {
                        "rule-id": "1",
                        "rule-name": "1",
                        "rule-action": "explicit",
                        "rule-type": "selection",
                        "object-locator": {
                            "full-path": f'Servers."{server}".Schemas.{schema}'
                        },
                    }
                ]
            }
        )

    def _estimate_timeout(
        self,
        source_schema: str,
        object_count_fn: Optional[Any],
    ) -> int:
        """
        객체 수 기반 적응형 타임아웃을 계산한다: max(600, 300 + n*2).

        Args:
            source_schema: Oracle 스키마명
            object_count_fn: 객체 수를 반환하는 콜러블(없으면 기본 500 가정)

        Returns:
            타임아웃(초)
        """
        obj_count = 500
        if object_count_fn is not None:
            try:
                obj_count = int(object_count_fn(source_schema))
            except Exception as e:  # noqa: BLE001
                logger.warning("객체 수 조회 실패(기본 500 사용): %s", e)
        timeout = max(600, 300 + obj_count * 2)
        logger.info("적응형 타임아웃: %ds (객체 %d개 기준)", timeout, obj_count)
        return timeout

    def _export_to_target(
        self,
        dms: Any,
        target_rules: str,
        start_time: float,
        timeout: int,
    ) -> str:
        """
        export-to-target(apply changes)를 실행하고 완료까지 대기한다.

        Args:
            dms: dms 클라이언트
            target_rules: 타겟 selection rule(JSON 문자열)
            start_time: 시작 시각(time.time())
            timeout: 최대 대기 초(0 이하면 무제한)

        Returns:
            최종 상태 문자열

        Raises:
            DmsScError: 반영 실패 시
        """
        apply_resp = dms.start_metadata_model_export_to_target(
            MigrationProjectIdentifier=self.project_arn,
            SelectionRules=target_rules,
            OverwriteExtensionPack=False,
        )
        apply_status = self._wait_for(
            dms.describe_metadata_model_exports_to_target,
            apply_resp.get("RequestIdentifier", ""),
            "ExportToTarget",
            start_time,
            timeout,
        )
        if apply_status not in _DONE_OK:
            raise DmsScError(f"apply changes(export-to-target) 실패: {apply_status}")
        logger.info("apply changes 완료(타겟 DB 반영)")
        return apply_status

    def apply_changes(
        self,
        target_schema: str,
        timeout: int = 1800,
    ) -> Dict[str, Any]:
        """
        이미 변환된 모델을 타겟 DB에 반영한다(apply changes 단독 실행).

        1차 변환(import→convert→export)이 이미 수행된 프로젝트에서,
        export-to-target 만 단독으로 호출해 타겟 DB에 오브젝트를 생성한다.

        Args:
            target_schema: PostgreSQL 타겟 스키마(소문자)
            timeout: 최대 대기 초(기본 1800)

        Returns:
            {"apply_status", "target_schema", "elapsed_seconds"}

        Raises:
            DmsScError: 반영 실패 시
        """
        dms = self._client()
        start_time = time.time()
        servers = self._resolve_servers(dms)
        target_rules = self._selection_rule(servers["target"], target_schema.lower())
        logger.info("apply changes 시작(타겟 DB 반영): %s", target_schema.lower())
        logger.info("target rules: %s", target_rules)
        apply_status = self._export_to_target(dms, target_rules, start_time, timeout)
        elapsed = round(time.time() - start_time, 1)
        return {
            "apply_status": apply_status,
            "target_schema": target_schema.lower(),
            "elapsed_seconds": elapsed,
        }

    def run(
        self,
        source_schema: str,
        target_schema: str,
        file_name: str,
        timeout: int = 0,
        object_count_fn: Optional[Any] = None,
        apply_to_target: bool = True,
    ) -> Dict[str, Any]:
        """
        DMS SC 1차 변환을 실행한다(export-as-script + 평가, 옵션: 타겟 반영).

        Args:
            source_schema: Oracle 소스 스키마(대문자)
            target_schema: PostgreSQL 타겟 스키마(소문자)
            file_name: export 스크립트 파일 접두(예: dms-sc-<schema>)
            timeout: 최대 대기 초(0=적응형)
            object_count_fn: 객체 수 콜러블(적응형 타임아웃용, 선택)
            apply_to_target: True 면 마지막에 export-to-target(apply changes)로
                변환 DDL을 타겟 DB에 반영(오브젝트 생성)

        Returns:
            단계별 상태와 S3 위치를 담은 결과 dict

        Raises:
            DmsScError: 단계 실패 시
        """
        dms = self._client()
        start_time = time.time()

        if timeout <= 0:
            timeout = self._estimate_timeout(source_schema, object_count_fn)

        logger.info("DMS SC 변환 시작: %s → %s", source_schema, target_schema)
        logger.info("프로젝트 ARN: %s", self.project_arn)

        servers = self._resolve_servers(dms)
        source_rules = self._selection_rule(servers["source"], source_schema.upper())
        target_rules = self._selection_rule(servers["target"], target_schema.lower())
        logger.info("source rules: %s", source_rules)
        logger.info("target rules: %s", target_rules)

        if self.convert_number_to_bigint:
            self._apply_bigint_setting(dms)

        # Step 0: extension pack (없을 때만)
        ext_desc = dms.describe_extension_pack_associations(
            MigrationProjectIdentifier=self.project_arn
        )
        if not ext_desc.get("Requests"):
            logger.info("Step 0/4: extension pack 설치...")
            ext_resp = dms.start_extension_pack_association(
                MigrationProjectIdentifier=self.project_arn
            )
            ext_status = self._wait_for(
                dms.describe_extension_pack_associations,
                ext_resp.get("RequestIdentifier", ""),
                "ExtensionPack",
                start_time,
                timeout,
            )
            if ext_status not in _DONE_OK:
                raise DmsScError(f"extension pack 설치 실패: {ext_status}")
            logger.info("extension pack 설치 완료")
        else:
            logger.info("extension pack 이미 설치됨, skip")

        # Step 1: import (Oracle 메타)
        logger.info("Step 1/4: 메타데이터 import (SOURCE)...")
        import_resp = dms.start_metadata_model_import(
            MigrationProjectIdentifier=self.project_arn,
            SelectionRules=source_rules,
            Origin="SOURCE",
            Refresh=True,
        )
        import_status = self._wait_for(
            dms.describe_metadata_model_imports,
            import_resp.get("RequestIdentifier", ""),
            "Import",
            start_time,
            timeout,
        )
        if import_status not in _DONE_OK:
            raise DmsScError(f"메타데이터 import 실패: {import_status}")
        logger.info("import 완료")

        # Step 2: conversion
        logger.info("Step 2/4: 변환 (Oracle → PostgreSQL)...")
        convert_resp = dms.start_metadata_model_conversion(
            MigrationProjectIdentifier=self.project_arn,
            SelectionRules=source_rules,
        )
        convert_status = self._wait_for(
            dms.describe_metadata_model_conversions,
            convert_resp.get("RequestIdentifier", ""),
            "Conversion",
            start_time,
            timeout,
        )
        if convert_status not in _DONE_OK:
            raise DmsScError(f"변환 실패: {convert_status}")
        logger.info("변환 완료")

        # Step 3: export as script → S3 (export-to-target은 수행하지 않음)
        logger.info("Step 3/4: DDL 스크립트 S3 export (TARGET)...")
        export_resp = dms.start_metadata_model_export_as_script(
            MigrationProjectIdentifier=self.project_arn,
            SelectionRules=target_rules,
            Origin="TARGET",
            FileName=file_name,
        )
        request_id = export_resp.get("RequestIdentifier", "")
        export_status = self._wait_for(
            dms.describe_metadata_model_exports_as_script,
            request_id,
            "Export",
            start_time,
            timeout,
        )
        if export_status not in _DONE_OK:
            raise DmsScError(f"스크립트 export 실패: {export_status}")
        logger.info("스크립트 export 완료")

        # Step 4: assessment (리포트)
        logger.info("Step 4/4: 평가 리포트 생성...")
        assess_resp = dms.start_metadata_model_assessment(
            MigrationProjectIdentifier=self.project_arn,
            SelectionRules=source_rules,
        )
        assess_status = self._wait_for(
            dms.describe_metadata_model_assessments,
            assess_resp.get("RequestIdentifier", ""),
            "Assessment",
            start_time,
            timeout,
        )

        # Step 5: apply changes (export-to-target) → 타겟 DB 반영
        apply_status = "SKIPPED"
        if apply_to_target:
            logger.info("Step 5/5: apply changes (export-to-target, 타겟 DB 반영)...")
            apply_status = self._export_to_target(
                dms, target_rules, start_time, timeout
            )

        elapsed = round(time.time() - start_time, 1)
        result = {
            "success": export_status in _DONE_OK,
            "import_status": import_status,
            "convert_status": convert_status,
            "export_status": export_status,
            "assessment_status": assess_status,
            "apply_status": apply_status,
            "request_id": request_id,
            "s3_bucket": self.s3_bucket,
            "file_name": file_name,
            "source_schema": source_schema.upper(),
            "target_schema": target_schema.lower(),
            "elapsed_seconds": elapsed,
            "timeout_used": timeout,
        }
        logger.info(
            "DMS SC 1차 변환 완료: %.0fs (import→convert→export→assess→apply=%s)",
            elapsed,
            apply_status,
        )
        return result
