"""
DMS SC 산출물 다운로드 스텝 (2차 시작)

프로젝트 연결 S3 에서 DMS SC 산출물을 로컬 작업 디렉토리로 내려받는다.
  - 변환 DDL zip(dms-sc-<schema>.zip) → 압축 해제하여 .sql 확보
  - 스키마 노드 통계 파일(action-items/<req-id>/Schemas.<SCHEMA>) → 변환대상 판별용
  - action-items 사전 파일(*-aid) → severity 조회용

S3 위치는 S3Exporter.locate_artifacts 결과를 재사용하지 않고, 여기서도
프로젝트명 prefix 를 조회해 독립적으로 수집한다(2차 단독 실행 가능).

변경 이력:
2026-08-05 | OMA Team | 초기 생성
  - fetch(): DDL zip 다운로드+해제, Schemas 통계/aid 사전 다운로드
"""

import io
import logging
import os
import zipfile
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ArtifactFetchError(Exception):
    """산출물 다운로드 오류."""


class ArtifactFetcher:
    """
    DMS SC 산출물 다운로드기.

    Attributes:
        bucket: 산출물 S3 버킷
        region: AWS region
        project_arn: DMS 프로젝트 ARN(프로젝트명 해석용)
        work_dir: 로컬 작업 디렉토리
    """

    def __init__(
        self,
        bucket: str,
        region: str,
        project_arn: str,
        work_dir: str,
        s3_client: Optional[Any] = None,
        dms_client: Optional[Any] = None,
    ) -> None:
        """
        Args:
            bucket: S3 버킷명
            region: AWS region
            project_arn: DMS 프로젝트 ARN
            work_dir: 산출물을 내려받을 로컬 디렉토리
            s3_client: 주입할 boto3 s3 클라이언트(선택)
            dms_client: 주입할 boto3 dms 클라이언트(선택)
        """
        self.bucket = bucket
        self.region = region
        self.project_arn = project_arn
        self.work_dir = work_dir
        self._s3 = s3_client
        self._dms = dms_client

    def _s3_client(self) -> Any:
        """boto3 s3 클라이언트를 지연 생성/반환한다."""
        if self._s3 is not None:
            return self._s3
        try:
            import boto3
        except ImportError as e:
            raise ArtifactFetchError(f"boto3 임포트 실패: {e}") from e
        self._s3 = boto3.client("s3", region_name=self.region)
        return self._s3

    def _dms_client(self) -> Any:
        """boto3 dms 클라이언트를 지연 생성/반환한다."""
        if self._dms is not None:
            return self._dms
        try:
            import boto3
        except ImportError as e:
            raise ArtifactFetchError(f"boto3 임포트 실패: {e}") from e
        self._dms = boto3.client("dms", region_name=self.region)
        return self._dms

    def _project_name(self) -> str:
        """
        ARN 으로 프로젝트 이름을 조회한다(S3 prefix).

        Returns:
            MigrationProjectName

        Raises:
            ArtifactFetchError: 조회 실패 시
        """
        dms = self._dms_client()
        try:
            resp = dms.describe_migration_projects(
                Filters=[
                    {
                        "Name": "migration-project-identifier",
                        "Values": [self.project_arn],
                    }
                ]
            )
            return resp["MigrationProjects"][0]["MigrationProjectName"]
        except (KeyError, IndexError) as e:
            raise ArtifactFetchError(f"프로젝트 이름 조회 실패: {e}") from e

    def _download_bytes(self, s3: Any, key: str) -> bytes:
        """
        S3 객체를 메모리로 다운로드한다.

        Args:
            s3: s3 클라이언트
            key: 객체 키

        Returns:
            객체 바이트

        Raises:
            ArtifactFetchError: 다운로드 실패 시
        """
        try:
            resp = s3.get_object(Bucket=self.bucket, Key=key)
            return resp["Body"].read()
        except Exception as e:  # noqa: BLE001
            raise ArtifactFetchError(f"다운로드 실패({key}): {e}") from e

    def fetch(self, schema: str, file_name: str) -> Dict[str, Any]:
        """
        산출물을 다운로드하고 DDL zip 을 해제한다.

        Args:
            schema: 스키마명(대문자 Oracle 스키마)
            file_name: DMS export 파일 접두(dms-sc-<schema_lower>)

        Returns:
            {
              "prefix", "work_dir",
              "ddl_sql_path": <해제된 .sql 로컬 경로>,
              "schema_stats_key": <Schemas.<SCHEMA> S3 키> | None,
              "schema_stats_path": <로컬 경로> | None,
              "aid_key"/"aid_path": <severity 사전> | None,
            }

        Raises:
            ArtifactFetchError: DDL zip 을 찾지 못하거나 다운로드 실패 시
        """
        s3 = self._s3_client()
        project = self._project_name()
        prefix = f"{project}/"
        os.makedirs(self.work_dir, exist_ok=True)

        ddl_zip_key = f"{prefix}{file_name}.zip"
        schema_upper = schema.upper()

        # prefix 스캔: Schemas.<SCHEMA> 통계 파일, *-aid 사전 위치 탐색
        schema_stats_key: Optional[str] = None
        aid_key: Optional[str] = None
        found_ddl = False
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key == ddl_zip_key:
                    found_ddl = True
                elif key.startswith(f"{prefix}action-items/"):
                    base = key.rsplit("/", 1)[-1]
                    if base == f"Schemas.{schema_upper}":
                        schema_stats_key = key
                    elif base.endswith("-aid"):
                        aid_key = key

        if not found_ddl:
            raise ArtifactFetchError(f"DDL zip 을 찾지 못했습니다: {ddl_zip_key}")

        # DDL zip 다운로드 + 해제
        zip_bytes = self._download_bytes(s3, ddl_zip_key)
        ddl_sql_path: Optional[str] = None
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            sql_names = [n for n in zf.namelist() if n.lower().endswith(".sql")]
            if not sql_names:
                raise ArtifactFetchError(f"zip 내 .sql 이 없습니다: {ddl_zip_key}")
            for name in sql_names:
                local = os.path.join(self.work_dir, os.path.basename(name))
                with open(local, "wb") as f:
                    f.write(zf.read(name))
                # 단일 .sql 가정: 첫 파일을 대표 경로로
                if ddl_sql_path is None:
                    ddl_sql_path = local
        logger.info("DDL 해제 완료: %s", ddl_sql_path)

        result: Dict[str, Any] = {
            "prefix": prefix,
            "work_dir": self.work_dir,
            "ddl_sql_path": ddl_sql_path,
            "schema_stats_key": schema_stats_key,
            "schema_stats_path": None,
            "aid_key": aid_key,
            "aid_path": None,
        }

        # 통계/사전 파일 다운로드(있으면)
        if schema_stats_key:
            data = self._download_bytes(s3, schema_stats_key)
            path = os.path.join(self.work_dir, f"Schemas.{schema_upper}.json")
            with open(path, "wb") as f:
                f.write(data)
            result["schema_stats_path"] = path
            logger.info("스키마 통계 다운로드: %s", path)
        else:
            logger.warning("Schemas.%s 통계 파일을 찾지 못했습니다", schema_upper)

        if aid_key:
            data = self._download_bytes(s3, aid_key)
            path = os.path.join(self.work_dir, "action-items-aid.json")
            with open(path, "wb") as f:
                f.write(data)
            result["aid_path"] = path
            logger.info("action-items 사전 다운로드: %s", path)
        else:
            logger.warning("action-items 사전(*-aid)을 찾지 못했습니다")

        return result
