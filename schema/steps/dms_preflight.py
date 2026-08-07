"""
DMS 리소스 조회 + 엔드포인트 사전 점검 (3차 full-load 보조)

이름 기반 ARN 조회와, 적재 전 엔드포인트 상태/접속 테스트를 담당한다.
데이터/스키마를 변경하지 않는 조회·테스트 전용 동작이라, 사용자 승인을 받기
위한 근거(엔드포인트가 살아있는지)를 만든다.

boto3 예외를 여기서 흡수하지 않고, 호출자(DmsFullLoad)가 DmsPreflightError 로
받도록 얇게 감싼다.

변경 이력:
2026-08-05 | OMA Team | 초기 생성(dms_full_load 에서 분리, 500 line 대응)
  - resolve_instance_arn / resolve_endpoint_arn / instance_info
  - endpoint_test / run_connection_test / preflight
2026-08-05 | OMA Team | ensure_number_scale_zero 추가(정수 NUMBER 소수점 대응)
  - 소스 Oracle endpoint NumberDataTypeScale=0 보정(dms_full_load 에서 이관)
"""

import logging
import time
from typing import Any, Dict

logger = logging.getLogger(__name__)

# 접속 테스트 결과 폴링 최대 횟수
_TEST_POLL_MAX = 20


class DmsPreflightError(Exception):
    """DMS 리소스 조회/사전 점검 오류."""


def resolve_instance_arn(dms: Any, instance_name: str) -> str:
    """
    replication instance 이름으로 ARN을 조회한다.

    Args:
        dms: dms 클라이언트
        instance_name: replication instance 식별자(이름)

    Returns:
        replication instance ARN

    Raises:
        DmsPreflightError: 인스턴스를 찾지 못할 때
    """
    try:
        resp = dms.describe_replication_instances(
            Filters=[
                {"Name": "replication-instance-id", "Values": [instance_name]}
            ]
        )
        instances = resp.get("ReplicationInstances", [])
        if not instances:
            raise DmsPreflightError(f"replication instance 없음: {instance_name}")
        return instances[0]["ReplicationInstanceArn"]
    except (KeyError, IndexError) as e:
        raise DmsPreflightError(f"replication instance 조회 실패: {e}") from e


def resolve_endpoint_arn(dms: Any, name: str, role: str) -> str:
    """
    endpoint 이름으로 ARN을 조회한다.

    Args:
        dms: dms 클라이언트
        name: endpoint 식별자(이름)
        role: 'source' | 'target' (로깅/검증용)

    Returns:
        endpoint ARN

    Raises:
        DmsPreflightError: endpoint를 찾지 못할 때
    """
    try:
        resp = dms.describe_endpoints(
            Filters=[{"Name": "endpoint-id", "Values": [name]}]
        )
        endpoints = resp.get("Endpoints", [])
        if not endpoints:
            raise DmsPreflightError(f"{role} endpoint 없음: {name}")
        return endpoints[0]["EndpointArn"]
    except (KeyError, IndexError) as e:
        raise DmsPreflightError(f"{role} endpoint 조회 실패: {e}") from e


def ensure_number_scale_zero(dms: Any, source_arn: str) -> None:
    """
    소스 Oracle endpoint 의 NumberDatatypeScale 를 0 으로 보정한다.

    DMS 기본값은 NUMBER 를 소수 스케일로 언로드해 정수도 '3.0000000000'
    형태가 되어, bigint 로 변환된 타겟 컬럼 적재 시 거부된다. 스케일 0 이면
    정수로 언로드된다. 이미 0 이면 modify 를 건너뛴다(불필요한 재시작 방지).

    주의: 스키마의 모든 NUMBER 가 정수(scale=0)일 때 안전하다. 실수(scale>0)
    컬럼이 있으면 소수부가 잘리므로 호출 전에 확인해야 한다.

    Args:
        dms: dms 클라이언트
        source_arn: 소스 endpoint ARN

    Raises:
        DmsPreflightError: endpoint 조회/수정 실패 시
    """
    try:
        resp = dms.describe_endpoints(
            Filters=[{"Name": "endpoint-arn", "Values": [source_arn]}]
        )
        ep = resp["Endpoints"][0]
    except (KeyError, IndexError) as e:
        raise DmsPreflightError(f"소스 endpoint 조회 실패: {e}") from e

    # DMS API 파라미터명은 'NumberDatatypeScale'(Datatype 소문자 t) 이다.
    current = ep.get("OracleSettings", {}).get("NumberDatatypeScale")
    if current == 0:
        logger.info("소스 endpoint NumberDatatypeScale 이미 0 - 유지")
        return
    try:
        dms.modify_endpoint(
            EndpointArn=source_arn,
            OracleSettings={"NumberDatatypeScale": 0},
        )
    except Exception as e:  # noqa: BLE001 - boto ClientError 포괄
        raise DmsPreflightError(
            f"소스 endpoint NumberDatatypeScale 수정 실패: {e}"
        ) from e
    logger.info(
        "소스 endpoint NumberDatatypeScale=0 적용(정수 NUMBER 소수점 제거)"
    )


def instance_info(dms: Any, instance_name: str) -> Dict[str, str]:
    """
    replication instance 이름/상태/ARN 을 조회한다.

    Args:
        dms: dms 클라이언트
        instance_name: replication instance 식별자(이름)

    Returns:
        {"name", "status", "arn"}

    Raises:
        DmsPreflightError: 인스턴스를 찾지 못할 때
    """
    resp = dms.describe_replication_instances(
        Filters=[{"Name": "replication-instance-id", "Values": [instance_name]}]
    )
    instances = resp.get("ReplicationInstances", [])
    if not instances:
        raise DmsPreflightError(f"replication instance 없음: {instance_name}")
    inst = instances[0]
    return {
        "name": inst.get("ReplicationInstanceIdentifier", ""),
        "status": inst.get("ReplicationInstanceStatus", "unknown"),
        "arn": inst["ReplicationInstanceArn"],
    }


def run_connection_test(
    dms: Any,
    endpoint_arn: str,
    instance_arn: str,
    role: str,
    poll_interval: int,
) -> str:
    """
    endpoint test-connection 을 수행하고 최종 상태를 반환한다.

    기존 성공 커넥션이 있으면 재사용하고, 없으면 test_connection 을 시작한 뒤
    결과를 폴링한다.

    Args:
        dms: dms 클라이언트
        endpoint_arn: 대상 endpoint ARN
        instance_arn: replication instance ARN
        role: 'source' | 'target'(로깅용)
        poll_interval: 결과 폴링 주기(초)

    Returns:
        'successful' | 'failed' | 'testing'
    """
    # 기존 성공 커넥션 재사용
    existing = dms.describe_connections(
        Filters=[{"Name": "endpoint-arn", "Values": [endpoint_arn]}]
    ).get("Connections", [])
    for c in existing:
        if (
            c.get("ReplicationInstanceArn") == instance_arn
            and c.get("Status") == "successful"
        ):
            return "successful"

    try:
        dms.test_connection(
            ReplicationInstanceArn=instance_arn, EndpointArn=endpoint_arn
        )
    except Exception as e:  # noqa: BLE001 - 이미 테스트 중이면 폴링으로 진행
        logger.warning("%s test_connection 시작 경고: %s", role, e)

    for _ in range(_TEST_POLL_MAX):
        time.sleep(poll_interval)
        conns = dms.describe_connections(
            Filters=[{"Name": "endpoint-arn", "Values": [endpoint_arn]}]
        ).get("Connections", [])
        match = [
            c for c in conns
            if c.get("ReplicationInstanceArn") == instance_arn
        ]
        if match:
            status = match[0].get("Status", "")
            if status in ("successful", "failed"):
                if status == "failed":
                    logger.warning(
                        "%s 접속 실패: %s",
                        role,
                        match[0].get("LastFailureMessage", ""),
                    )
                return status
    return "testing"


def endpoint_test(
    dms: Any, name: str, role: str, instance_arn: str, poll_interval: int
) -> Dict[str, str]:
    """
    endpoint 상태를 조회하고 test-connection 을 수행/확인한다.

    Args:
        dms: dms 클라이언트
        name: endpoint 식별자(이름)
        role: 'source' | 'target'
        instance_arn: 테스트에 사용할 replication instance ARN
        poll_interval: 결과 폴링 주기(초)

    Returns:
        {"name", "arn", "engine", "status", "connection"}

    Raises:
        DmsPreflightError: endpoint 를 찾지 못할 때
    """
    resp = dms.describe_endpoints(
        Filters=[{"Name": "endpoint-id", "Values": [name]}]
    )
    endpoints = resp.get("Endpoints", [])
    if not endpoints:
        raise DmsPreflightError(f"{role} endpoint 없음: {name}")
    ep = endpoints[0]
    arn = ep["EndpointArn"]
    conn = run_connection_test(dms, arn, instance_arn, role, poll_interval)
    return {
        "name": ep.get("EndpointIdentifier", ""),
        "arn": arn,
        "engine": ep.get("EngineName", ""),
        "status": ep.get("Status", "unknown"),
        "connection": conn,
    }


def preflight(
    dms: Any,
    instance_name: str,
    source_name: str,
    target_name: str,
    poll_interval: int,
) -> Dict[str, Any]:
    """
    적재 전 사전 점검: 리소스 ARN 조회 + 엔드포인트 상태/접속 테스트.

    Args:
        dms: dms 클라이언트
        instance_name: replication instance 이름
        source_name: 소스 endpoint 이름
        target_name: 타겟 endpoint 이름
        poll_interval: 접속 테스트 폴링 주기(초)

    Returns:
        {"instance", "source", "target", "ready"} - ready 는 인스턴스
        available + 양 엔드포인트 test-connection successful 여부

    Raises:
        DmsPreflightError: 리소스 조회 실패 시
    """
    instance = instance_info(dms, instance_name)
    source = endpoint_test(
        dms, source_name, "source", instance["arn"], poll_interval
    )
    target = endpoint_test(
        dms, target_name, "target", instance["arn"], poll_interval
    )
    ready = (
        instance["status"] == "available"
        and source["connection"] == "successful"
        and target["connection"] == "successful"
    )
    logger.info(
        "preflight: instance=%s source=%s target=%s → ready=%s",
        instance["status"],
        source["connection"],
        target["connection"],
        ready,
    )
    return {
        "instance": instance,
        "source": source,
        "target": target,
        "ready": ready,
    }
