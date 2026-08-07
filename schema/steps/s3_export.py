"""
DMS SC 산출물 위치 확인 스텝 (1차 마무리)

DMS Schema Conversion 은 변환 DDL 과 평가(action-items) 리포트를
프로젝트에 연결된 S3 에 이미 산출물로 업로드한다. 따라서 별도의 재압축은
불필요하며, 본 스텝은 그 산출물의 S3 위치를 확인·수집하여 반환한다.

산출물 컨벤션(실측):
  s3://<bucket>/<project-name>/
    ├── dms-sc-<schema>.zip                 # 변환된 PostgreSQL DDL(zip 내 .sql)
    ├── action-items/                       # 평가/액션아이템 리포트(JSON)
    │   ├── ORACLE_TO_AURORA_POSTGRESQL-aid
    │   ├── ORACLE-ot
    │   └── <request-id>/Schemas.<SCHEMA>
    ├── s-<id>/ , t-<id>/ ...               # 소스/타겟 메타 트리 노드
    └── ...

prefix 는 config 의 ARN 이 아니라 "프로젝트 이름" 이므로,
describe_migration_projects 로 이름을 조회해 사용한다.

이 산출물들은 2차(LLM 변환) 단계에서 다운로드하여:
  - action-items 에서 미변환 오브젝트 목록을 추출하고
  - DDL 을 참조해 타겟에 맞게 LLM 변환 후 타겟 DB 에 생성한다.

변경 이력:
2026-08-05 | OMA Team | 초기 생성(재압축 방식)
2026-08-05 | OMA Team | 재작성 - DMS 산출물 위치 확인 방식으로 변경
  - 재압축 제거(DMS 가 이미 산출물 업로드). ARN→프로젝트명으로 prefix 해석.
  - locate_artifacts(): DDL zip / action-items / 전체 객체 목록 반환
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class S3ExportError(Exception):
    """S3 산출물 확인 오류."""


class S3Exporter:
    """
    DMS SC 산출물 위치 확인기.

    Attributes:
        bucket: 산출물 S3 버킷
        region: AWS region
        project_arn: DMS 마이그레이션 프로젝트 ARN(프로젝트명 해석용)
    """

    def __init__(
        self,
        bucket: str,
        region: str,
        project_arn: str,
        s3_client: Optional[Any] = None,
        dms_client: Optional[Any] = None,
    ) -> None:
        """
        Args:
            bucket: S3 버킷명
            region: AWS region
            project_arn: DMS 프로젝트 ARN
            s3_client: 주입할 boto3 s3 클라이언트(선택, 테스트용)
            dms_client: 주입할 boto3 dms 클라이언트(선택, 테스트용)
        """
        self.bucket = bucket
        self.region = region
        self.project_arn = project_arn
        self._s3 = s3_client
        self._dms = dms_client

    def _s3_client(self) -> Any:
        """
        boto3 s3 클라이언트를 지연 생성/반환한다.

        Returns:
            s3 클라이언트

        Raises:
            S3ExportError: boto3 임포트 실패 시
        """
        if self._s3 is not None:
            return self._s3
        try:
            import boto3
        except ImportError as e:
            raise S3ExportError(f"boto3 임포트 실패: {e}") from e
        self._s3 = boto3.client("s3", region_name=self.region)
        return self._s3

    def _dms_client(self) -> Any:
        """
        boto3 dms 클라이언트를 지연 생성/반환한다.

        Returns:
            dms 클라이언트

        Raises:
            S3ExportError: boto3 임포트 실패 시
        """
        if self._dms is not None:
            return self._dms
        try:
            import boto3
        except ImportError as e:
            raise S3ExportError(f"boto3 임포트 실패: {e}") from e
        self._dms = boto3.client("dms", region_name=self.region)
        return self._dms

    def _resolve_project_name(self) -> str:
        """
        ARN 으로 프로젝트 이름을 조회한다(S3 prefix 로 사용).

        Returns:
            MigrationProjectName

        Raises:
            S3ExportError: 조회 실패 시
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
            raise S3ExportError(f"프로젝트 이름 조회 실패: {e}") from e

    def locate_artifacts(
        self, schema: str, file_name: str
    ) -> Dict[str, Any]:
        """
        DMS SC 산출물(변환 DDL zip, action-items 리포트)의 S3 위치를 확인한다.

        Args:
            schema: 스키마명(로깅용)
            file_name: DMS export 파일 접두(dms-sc-<schema>) → DDL zip 이름 근거

        Returns:
            {
              "success": True,
              "bucket", "prefix",
              "ddl_zip": {"key","size","s3_uri"} | None,
              "action_items": [{"key","size","s3_uri"}, ...],
              "object_count": <프로젝트 prefix 내 전체 객체 수>,
            }

        Raises:
            S3ExportError: prefix 하위에 산출물이 없을 때
        """
        s3 = self._s3_client()
        project_name = self._resolve_project_name()
        prefix = f"{project_name}/"
        logger.info("산출물 prefix: s3://%s/%s", self.bucket, prefix)

        ddl_zip: Optional[Dict[str, Any]] = None
        action_items: List[Dict[str, Any]] = []
        object_count = 0

        ddl_zip_key = f"{prefix}{file_name}.zip"
        action_items_prefix = f"{prefix}action-items/"

        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith("/"):
                    continue
                object_count += 1
                entry = {
                    "key": key,
                    "size": obj["Size"],
                    "s3_uri": f"s3://{self.bucket}/{key}",
                }
                if key == ddl_zip_key:
                    ddl_zip = entry
                elif key.startswith(action_items_prefix):
                    action_items.append(entry)

        if object_count == 0:
            raise S3ExportError(
                f"프로젝트 prefix 하위에 산출물이 없습니다 "
                f"(bucket={self.bucket}, prefix={prefix})"
            )
        if ddl_zip is None:
            logger.warning(
                "DDL zip(%s)을 찾지 못했습니다. export-as-script 결과를 확인하세요.",
                ddl_zip_key,
            )

        result = {
            "success": True,
            "bucket": self.bucket,
            "prefix": prefix,
            "ddl_zip": ddl_zip,
            "action_items": action_items,
            "object_count": object_count,
        }
        logger.info(
            "산출물 확인 완료: DDL zip=%s, action-items %d개, 전체 객체 %d개",
            ddl_zip["s3_uri"] if ddl_zip else "없음",
            len(action_items),
            object_count,
        )
        return result
