"""
DMS Full Load 데이터 마이그레이션 스텝 (3차)

1차(DMS SC)로 타겟 스키마(오브젝트)를 생성하고 2차(LLM)로 미변환 오브젝트까지
반영한 뒤, 소스 Oracle 의 실제 "데이터"를 타겟 PostgreSQL(Aurora)로 이전한다.

DMS Schema Conversion(메타데이터 변환)과는 별개인 DMS "replication task"를
사용한다. env 단계에서 이미 배포된 리소스를 이름으로 조회해 사용한다:
  - replication instance : 태스크가 실행되는 복제 인스턴스
  - source endpoint      : Oracle 소스 접속점
  - target endpoint      : PostgreSQL(Aurora) 타겟 접속점

흐름:
  0. (사전) preflight(): 리소스 ARN 조회 + 엔드포인트 상태/접속 테스트
  1. 리소스 ARN 조회(이름 → describe → ARN)
  2. table-mappings(선택 규칙 + 소문자 변형) 구성
  3. create-replication-task (MigrationType=full-load)
  4. start-replication-task
  5. 완료(Stopped/full-load 완료)까지 폴링

설계:
  - 리소스는 이름으로 자동 해석(설정에 ARN 직접 관리 불필요, 이름만 오버라이드 가능).
  - full-load 단독(1회성 이전). CDC 미사용.
  - 타겟 준비 모드 TRUNCATE_BEFORE_LOAD(재실행 안전, 스키마/제약 유지).
  - 소스(대문자) → 타겟(소문자) 오브젝트명 정합을 위해 schema/table/column
    소문자 변형 규칙을 기본 적용(dms_mappings).
  - 실제 적재 전에 preflight() 로 엔드포인트 상태를 확인하고 사용자 승인을 받는다.
  - boto3 dms 클라이언트는 지연 생성.

변경 이력:
2026-08-05 | OMA Team | 초기 생성
  - DmsFullLoad.run(): 리소스 조회 → task 생성 → 시작 → 완료 폴링
  - full-load 단독, TRUNCATE_BEFORE_LOAD, 이름 기반 리소스 자동 해석
2026-08-05 | OMA Team | preflight + 소문자 변형 규칙 추가
  - preflight(): 엔드포인트 상태 describe + test-connection(적재 전 확인용)
  - table-mappings/task-settings 를 dms_mappings 모듈로 분리(소문자 변형 포함)
2026-08-05 | OMA Team | task_id 정규화(버그 수정)
  - 원인: task_id 에 언더스코어(_) 포함 시 DMS InvalidParameterValueException
    (예: oma-fullload-mbr_b2b_mgr). DMS 식별자는 letters/digits/hyphen 만 허용.
  - _normalize_task_id(): '_'·불허 문자 → 하이픈, 연속/끝 하이픈 정리, 첫 글자 letter 보장
2026-08-05 | OMA Team | describe_replication_tasks 없음 처리(버그 수정)
  - 원인: task 미존재 시 DMS 가 빈 리스트가 아닌 ResourceNotFoundFault 를 던져
    신규 실행(첫 full-load)에서 실패. describe 호출 4곳이 동일 패턴.
  - _describe_tasks(): ResourceNotFoundFault 만 흡수해 빈 리스트 반환, 4곳 공용화
2026-08-05 | OMA Team | NUMBER 소수점 + LOB truncation 대응(적재 오류 수정)
  - 원인1: 정수 NUMBER 가 '3.0000000000' 로 언로드되어 bigint 타겟이 거부
    → _ensure_number_scale_zero(): 소스 endpoint NumberDataTypeScale=0 보정
  - 원인2: 기본 LobMaxSize=32KB 가 대형 CLOB 을 잘라 ORA-01406
    → lob_max_size_kb 파라미터(기본 1024KB)로 task_settings 에 전달
"""

import logging
import time
from typing import Any, Dict, Optional

from steps import dms_mappings, dms_preflight

logger = logging.getLogger(__name__)

# 완료로 간주하는 task 상태
_DONE_OK = ("stopped", "completed")
# 진행 중으로 간주하는 상태
_RUNNING = ("creating", "ready", "starting", "running", "stopping", "modifying")
# 실패로 간주하는 상태
_FAILED = ("failed", "failed-move")

# full-load 완료를 나타내는 stop 사유(FreshStart 이후 정상 종료)
_FULLLOAD_DONE_REASONS = (
    "FULL_LOAD_ONLY_FINISHED",
    "Stop Reason FULL_LOAD_ONLY_FINISHED",
)


class DmsFullLoadError(Exception):
    """DMS full-load 마이그레이션 오류."""


def _describe_tasks(dms: Any, name: str, values: list) -> list:
    """
    replication task 를 조회하되, 없을 때 예외 대신 빈 리스트를 반환한다.

    DMS describe_replication_tasks 는 매칭 task 가 없으면 빈 리스트가 아니라
    ResourceNotFoundFault 를 던진다. 신규 실행(task 미존재) 흐름을 위해 흡수한다.

    Args:
        dms: dms 클라이언트
        name: 필터명(예: 'replication-task-id' | 'replication-task-arn')
        values: 필터 값 리스트

    Returns:
        ReplicationTasks 리스트(없으면 빈 리스트)
    """
    try:
        resp = dms.describe_replication_tasks(
            Filters=[{"Name": name, "Values": values}]
        )
        return resp.get("ReplicationTasks", [])
    except Exception as e:  # noqa: BLE001 - ResourceNotFoundFault 만 흡수
        if type(e).__name__ == "ResourceNotFoundFault" or (
            getattr(e, "response", {}).get("Error", {}).get("Code")
            == "ResourceNotFoundFault"
        ):
            return []
        raise


def _normalize_task_id(raw: str) -> str:
    """
    문자열을 DMS replication task 식별자 규칙에 맞게 정규화한다.

    DMS 규칙: 첫 글자는 letter, ASCII letters/digits/hyphen 만 허용,
    끝 하이픈·연속 하이픈 불가. (예: 언더스코어 '_' → 하이픈 '-')

    Args:
        raw: 원본 식별자 후보(예: oma-fullload-mbr_b2b_mgr)

    Returns:
        DMS 규칙에 맞는 task 식별자(예: oma-fullload-mbr-b2b-mgr)
    """
    # 허용 외 문자(언더스코어/점 등)를 하이픈으로 치환 - 파싱이 아닌 단순 정규화
    chars = [c if (c.isascii() and (c.isalnum() or c == "-")) else "-" for c in raw]
    result = "".join(chars)
    # 연속 하이픈 축약
    while "--" in result:
        result = result.replace("--", "-")
    # 앞뒤 하이픈 제거
    result = result.strip("-")
    # 첫 글자는 letter 이어야 함
    if not result or not result[0].isalpha():
        result = f"oma-{result}" if result else "oma-fullload"
    return result


class DmsFullLoad:
    """
    DMS replication task(full-load) 실행기.

    Attributes:
        region: AWS region
        instance_name: replication instance 식별자(이름)
        source_endpoint_name: 소스 endpoint 식별자(이름)
        target_endpoint_name: 타겟 endpoint 식별자(이름)
        poll_interval: 상태 폴링 주기(초)
        lowercase: 오브젝트명 소문자 변형 규칙 적용 여부
    """

    def __init__(
        self,
        region: str,
        instance_name: str,
        source_endpoint_name: str,
        target_endpoint_name: str,
        poll_interval: int = 30,
        lowercase: bool = True,
        lob_max_size_kb: int = 1024,
        number_scale_zero: bool = True,
        dms_client: Optional[Any] = None,
    ) -> None:
        """
        Args:
            region: AWS region
            instance_name: replication instance 이름(예: omabox-stack-dms-instance)
            source_endpoint_name: 소스 endpoint 이름
            target_endpoint_name: 타겟 endpoint 이름
            poll_interval: 상태 폴링 주기(초)
            lowercase: schema/table/column 소문자 변형 규칙 적용 여부
                (소스 대문자 → 타겟 소문자 정합; 기본 True)
            lob_max_size_kb: Limited LOB 모드 최대 크기(KB). 소스 CLOB 실제
                최대 길이보다 크게 잡아야 truncation(ORA-01406)을 막는다.
            number_scale_zero: True 면 소스 Oracle endpoint 에
                NumberDataTypeScale=0 을 적용해 정수 NUMBER 를 소수점 없이
                언로드(bigint 적재 시 '3.0000000000' 거부 방지). 스키마의 모든
                NUMBER 가 정수(scale=0)일 때 안전.
            dms_client: 주입할 boto3 dms 클라이언트(선택, 테스트용)
        """
        self.region = region
        self.instance_name = instance_name
        self.source_endpoint_name = source_endpoint_name
        self.target_endpoint_name = target_endpoint_name
        self.poll_interval = poll_interval
        self.lowercase = lowercase
        self.lob_max_size_kb = lob_max_size_kb
        self.number_scale_zero = number_scale_zero
        self._dms = dms_client

    def _client(self) -> Any:
        """
        boto3 dms 클라이언트를 지연 생성/반환한다.

        Returns:
            dms 클라이언트

        Raises:
            DmsFullLoadError: boto3 임포트 실패 시
        """
        if self._dms is not None:
            return self._dms
        try:
            import boto3
        except ImportError as e:
            raise DmsFullLoadError(f"boto3 임포트 실패: {e}") from e
        self._dms = boto3.client("dms", region_name=self.region)
        return self._dms

    def preflight(self) -> Dict[str, Any]:
        """
        적재 전 사전 점검: 리소스 ARN 조회 + 엔드포인트 상태/접속 테스트.

        실제 full-load 를 실행하지 않고, 리소스가 준비되었는지와 소스/타겟
        엔드포인트 접속이 되는지만 확인한다(사용자 승인 판단 근거).
        실제 로직은 dms_preflight 모듈에 위임한다.

        Returns:
            {"instance", "source", "target", "ready"} dict

        Raises:
            DmsFullLoadError: 리소스 조회 실패 시
        """
        dms = self._client()
        try:
            return dms_preflight.preflight(
                dms,
                instance_name=self.instance_name,
                source_name=self.source_endpoint_name,
                target_name=self.target_endpoint_name,
                poll_interval=self.poll_interval,
            )
        except dms_preflight.DmsPreflightError as e:
            raise DmsFullLoadError(str(e)) from e

    def _wait_for_task(
        self,
        dms: Any,
        task_arn: str,
        start_time: float,
        timeout: int,
    ) -> Dict[str, Any]:
        """
        replication task를 완료/실패/타임아웃까지 폴링한다.

        Args:
            dms: dms 클라이언트
            task_arn: replication task ARN
            start_time: 시작 시각(time.time())
            timeout: 최대 대기 초(0 이하면 무제한)

        Returns:
            마지막 task 상태 dict(Status, StopReason, ReplicationTaskStats 포함)

        Raises:
            DmsFullLoadError: 실패 상태로 종료 시
        """
        status = "starting"
        last: Dict[str, Any] = {}
        while status in _RUNNING:
            if timeout > 0 and (time.time() - start_time) >= timeout:
                logger.warning("full-load 타임아웃(%ds 초과)", timeout)
                break
            time.sleep(self.poll_interval)
            tasks = _describe_tasks(dms, "replication-task-arn", [task_arn])
            if not tasks:
                continue
            last = tasks[0]
            status = last.get("Status", "unknown")
            stats = last.get("ReplicationTaskStats", {})
            logger.info(
                "full-load 상태: %s (테이블 완료=%s/%s, %.0fs 경과)",
                status,
                stats.get("TablesLoaded", "?"),
                stats.get("TablesLoaded", 0) + stats.get("TablesLoading", 0)
                + stats.get("TablesQueued", 0),
                time.time() - start_time,
            )
            if status in _FAILED:
                reason = last.get("LastFailureMessage", last.get("StopReason", ""))
                raise DmsFullLoadError(f"full-load 실패({status}): {reason}")
        return last

    def run(
        self,
        source_schema: str,
        timeout: int = 0,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        full-load 데이터 마이그레이션을 실행한다.

        Args:
            source_schema: 소스 Oracle 스키마(대문자)
            timeout: 최대 대기 초(0=무제한)
            task_id: 생성할 replication task 식별자(없으면 스키마 기반 자동)

        Returns:
            {"task_arn", "status", "stop_reason", "tables_loaded",
             "table_stats", "elapsed_seconds"}

        Raises:
            DmsFullLoadError: 리소스 조회/태스크 생성/시작/적재 실패 시
        """
        dms = self._client()
        start_time = time.time()

        if not task_id:
            task_id = f"oma-fullload-{source_schema.lower()}"
        # DMS 식별자 규칙(letters/digits/hyphen) 정규화 - 언더스코어 등 치환
        task_id = _normalize_task_id(task_id)

        logger.info("DMS full-load 시작: 스키마 %s (task=%s)", source_schema, task_id)

        try:
            instance_arn = dms_preflight.resolve_instance_arn(
                dms, self.instance_name
            )
            source_arn = dms_preflight.resolve_endpoint_arn(
                dms, self.source_endpoint_name, "source"
            )
            target_arn = dms_preflight.resolve_endpoint_arn(
                dms, self.target_endpoint_name, "target"
            )
        except dms_preflight.DmsPreflightError as e:
            raise DmsFullLoadError(str(e)) from e
        logger.info("  instance : %s", instance_arn)
        logger.info("  source   : %s", source_arn)
        logger.info("  target   : %s", target_arn)

        # 소스 endpoint 에 NumberDataTypeScale=0 보정(정수 NUMBER 소수점 제거)
        if self.number_scale_zero:
            try:
                dms_preflight.ensure_number_scale_zero(dms, source_arn)
            except dms_preflight.DmsPreflightError as e:
                raise DmsFullLoadError(str(e)) from e

        table_mappings = dms_mappings.table_mappings(
            source_schema.upper(), lowercase=self.lowercase
        )
        task_settings = dms_mappings.task_settings(
            lob_max_size_kb=self.lob_max_size_kb
        )

        # 태스크 생성(이미 있으면 재사용)
        task_arn = self._create_or_get_task(
            dms,
            task_id=task_id,
            source_arn=source_arn,
            target_arn=target_arn,
            instance_arn=instance_arn,
            table_mappings=table_mappings,
            task_settings=task_settings,
        )

        # 시작(생성 직후 상태가 될 때까지 대기 후 start)
        self._start_task(dms, task_arn)

        last = self._wait_for_task(dms, task_arn, start_time, timeout)
        status = last.get("Status", "unknown")
        stop_reason = last.get("StopReason", "")
        stats = last.get("ReplicationTaskStats", {})

        # 정상 완료 판정: stopped + full-load 완료 사유, 또는 completed
        ok = status == "completed" or (
            status == "stopped"
            and any(r in str(stop_reason) for r in _FULLLOAD_DONE_REASONS)
        )
        if not ok and status in _DONE_OK:
            logger.warning(
                "full-load 종료 상태 확인 필요: status=%s stop_reason=%s",
                status,
                stop_reason,
            )

        elapsed = round(time.time() - start_time, 1)
        result = {
            "task_arn": task_arn,
            "status": status,
            "stop_reason": stop_reason,
            "success": ok,
            "tables_loaded": stats.get("TablesLoaded", 0),
            "table_stats": {
                "loaded": stats.get("TablesLoaded", 0),
                "loading": stats.get("TablesLoading", 0),
                "queued": stats.get("TablesQueued", 0),
                "errored": stats.get("TablesErrored", 0),
            },
            "elapsed_seconds": elapsed,
        }
        logger.info(
            "DMS full-load 완료: %.0fs (status=%s, 테이블 적재=%d, 오류=%d)",
            elapsed,
            status,
            stats.get("TablesLoaded", 0),
            stats.get("TablesErrored", 0),
        )
        return result

    def _create_or_get_task(
        self,
        dms: Any,
        task_id: str,
        source_arn: str,
        target_arn: str,
        instance_arn: str,
        table_mappings: str,
        task_settings: str,
    ) -> str:
        """
        replication task를 생성하거나 기존 것을 조회해 ARN을 반환한다.

        Args:
            dms: dms 클라이언트
            task_id: task 식별자
            source_arn: 소스 endpoint ARN
            target_arn: 타겟 endpoint ARN
            instance_arn: replication instance ARN
            table_mappings: TableMappings JSON
            task_settings: ReplicationTaskSettings JSON

        Returns:
            replication task ARN

        Raises:
            DmsFullLoadError: 생성 실패 시
        """
        # 기존 task 조회(없으면 ResourceNotFoundFault → 빈 리스트로 흡수)
        existing = _describe_tasks(dms, "replication-task-id", [task_id])
        if existing:
            task_arn = existing[0]["ReplicationTaskArn"]
            logger.info("기존 replication task 재사용: %s", task_id)
            self._wait_ready_for_start(dms, task_arn)
            return task_arn

        try:
            resp = dms.create_replication_task(
                ReplicationTaskIdentifier=task_id,
                SourceEndpointArn=source_arn,
                TargetEndpointArn=target_arn,
                ReplicationInstanceArn=instance_arn,
                MigrationType="full-load",
                TableMappings=table_mappings,
                ReplicationTaskSettings=task_settings,
            )
            task_arn = resp["ReplicationTask"]["ReplicationTaskArn"]
        except Exception as e:  # noqa: BLE001 - boto ClientError 등 포괄
            raise DmsFullLoadError(f"replication task 생성 실패: {e}") from e
        logger.info("replication task 생성: %s", task_id)
        self._wait_ready_for_start(dms, task_arn)
        return task_arn

    def _wait_ready_for_start(self, dms: Any, task_arn: str) -> None:
        """
        task가 시작 가능한 상태(ready/stopped)가 될 때까지 대기한다.

        Args:
            dms: dms 클라이언트
            task_arn: replication task ARN
        """
        for _ in range(40):
            tasks = _describe_tasks(dms, "replication-task-arn", [task_arn])
            if tasks:
                st = tasks[0].get("Status", "")
                if st in ("ready", "stopped", "failed"):
                    return
            time.sleep(self.poll_interval)

    def _start_task(self, dms: Any, task_arn: str) -> None:
        """
        replication task를 시작한다(신규는 start-replication, 재실행은 reload).

        Args:
            dms: dms 클라이언트
            task_arn: replication task ARN

        Raises:
            DmsFullLoadError: 시작 실패 시
        """
        # 현재 상태에 따라 시작 타입 결정
        tasks = _describe_tasks(dms, "replication-task-arn", [task_arn])
        status = tasks[0].get("Status", "") if tasks else ""
        # 한 번이라도 실행된 적 있으면 reload-target, 아니면 start-replication
        start_type = (
            "reload-target" if status == "stopped" else "start-replication"
        )
        try:
            dms.start_replication_task(
                ReplicationTaskArn=task_arn,
                StartReplicationTaskType=start_type,
            )
        except Exception as e:  # noqa: BLE001
            raise DmsFullLoadError(
                f"replication task 시작 실패(type={start_type}): {e}"
            ) from e
        logger.info("replication task 시작(type=%s)", start_type)
