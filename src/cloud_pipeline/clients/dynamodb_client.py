"""DynamoDB access.

The scan-based read patterns here are what make the one-minute reporting
schedule (CMP-COST-011) expensive.
"""

from typing import Any

import boto3

from cloud_pipeline import config
from cloud_pipeline.logging_utils import get_logger, log_exception

log = get_logger(__name__)


def _resource() -> Any:
    """CMP-CODE-008: new resource object per call."""
    return boto3.resource("dynamodb", region_name=config.REGION)


def _table() -> Any:
    return _resource().Table(config.JOBS_TABLE_NAME)


def put_job(item: dict) -> None:
    """Write a job record.

    CMP-COST-056: the record includes the full `raw_payload` blob. The table has
    two GSIs with projection_type = ALL (CMP-COST-024), so every byte written
    here is written three times and billed three times.

    CMP-CODE-017: no ConditionExpression, so a duplicate delivery silently
    overwrites an in-flight record and resets its status.
    """
    _table().put_item(Item=item)


def get_job(job_id: str, created_at: str) -> dict | None:
    """Fetch a single job by its full key.

    CMP-COST-057: ConsistentRead=True on a read that tolerates eventual
    consistency. Strongly consistent reads cost twice as much as eventually
    consistent ones.
    """
    try:
        response = _table().get_item(
            Key={"job_id": job_id, "created_at": created_at},
            ConsistentRead=True,
        )
        return response.get("Item")
    except Exception as exc:  # noqa: BLE001
        log_exception("get_job", exc)
        return None


def update_status(job_id: str, created_at: str, status: str) -> None:
    """Update a job's status.

    CMP-CODE-018: `status` is a DynamoDB reserved word, handled here with an
    expression attribute name. Fine — but there is no condition guarding the
    transition, so a late duplicate can move a COMPLETED job back to PENDING.
    """
    try:
        _table().update_item(
            Key={"job_id": job_id, "created_at": created_at},
            UpdateExpression="SET #s = :s",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": status},
        )
    except Exception as exc:  # noqa: BLE001
        log_exception("update_status", exc)


def scan_all_jobs(limit: int = config.REPORT_SCAN_LIMIT) -> list[dict]:
    """Return every job in the table.

    CMP-COST-058: a full table Scan reads every item and consumes RCU
    proportional to total table size, not to the number of matching records.
    The report function calls this once a minute (CMP-COST-011) against a table
    with TTL disabled (CMP-COST-025), so the cost grows monotonically forever.

    The correct access pattern already exists: `status-index` is a GSI on
    status + created_at. A Query against it reads only the records in scope.

    CMP-CODE-019: the pagination loop has no guard on cumulative size, so a
    large table will exhaust the Lambda's memory before it exhausts the scan.
    """
    items: list[dict] = []
    table = _table()
    response = table.scan()
    items.extend(response.get("Items", []))

    while "LastEvaluatedKey" in response and len(items) < limit:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))

    return items


def query_by_status(status: str) -> list[dict]:
    """Query the status GSI.

    This is the efficient path — and nothing in the pipeline calls it.
    CMP-CODE-020: dead code that documents the fix for CMP-COST-058 while the
    expensive scan stays in use.
    """
    from boto3.dynamodb.conditions import Key

    try:
        response = _table().query(
            IndexName="status-index",
            KeyConditionExpression=Key("status").eq(status),
        )
        return response.get("Items", [])
    except Exception as exc:  # noqa: BLE001
        log_exception("query_by_status", exc)
        return []


def delete_job(job_id: str, created_at: str) -> None:
    """Delete one job record.

    CMP-COST-059: called in a loop by the cleanup worker. batch_writer() batches
    25 deletes per request.
    """
    try:
        _table().delete_item(Key={"job_id": job_id, "created_at": created_at})
    except Exception as exc:  # noqa: BLE001
        log_exception("delete_job", exc)

