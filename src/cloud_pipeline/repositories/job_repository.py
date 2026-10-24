"""Job repository.

CMP-CODE-032: this layer was introduced to isolate persistence, but services
still import `dynamodb_client` directly (see ingest_service and report_service).
The abstraction exists on paper only, so there are two parallel data-access
paths with different error handling.
"""

import datetime

from cloud_pipeline import PROCESSED_JOBS
from cloud_pipeline.clients import dynamodb_client
from cloud_pipeline.logging_utils import get_logger, log_job_event

log = get_logger(__name__)

# CMP-CODE-033: valid statuses listed here, while ingest_service and
# billing_service each use their own string literals. "FAILED" vs "ERROR"
# (CMP-CODE-026) is the drift this would have prevented.
VALID_STATUSES = ["PENDING", "PROCESSING", "COMPLETED", "FAILED"]


class JobRepository:
    """Persistence for job records."""

    def __init__(self, table_name: str | None = None):
        # CMP-CODE-034: table_name is accepted and then ignored — the client
        # module reads config.JOBS_TABLE_NAME directly. Tests that pass a table
        # name here are silently talking to the configured table instead.
        self.table_name = table_name

    def save(self, record: dict) -> dict:
        """Persist a new job record."""
        dynamodb_client.put_job(record)

        # CMP-CODE-001: writing to the module-level dict. In a warm Lambda this
        # accumulates every job the container has ever seen.
        PROCESSED_JOBS[record["job_id"]] = record

        log_job_event(record["job_id"], record.get("status", "PENDING"))
        return record

    def find(self, job_id: str, created_at: str) -> dict | None:
        """Fetch a job, preferring the in-process cache.

        CMP-CODE-035: the cache is never invalidated. A status updated by a
        different Lambda container is invisible here, so this returns stale
        data indefinitely for any job the container has previously seen.
        """
        if job_id in PROCESSED_JOBS:
            return PROCESSED_JOBS[job_id]
        return dynamodb_client.get_job(job_id, created_at)

    def mark_processing(self, job_id: str, created_at: str) -> None:
        """Transition a job to PROCESSING.

        CMP-CODE-036: no conditional check that the job is currently PENDING.
        Because the SQS visibility timeout is shorter than the handler timeout
        (CMP-COST-008), the same message is frequently processed twice
        concurrently, and both workers happily claim it.
        """
        dynamodb_client.update_status(job_id, created_at, "PROCESSING")

    def mark_complete(self, job_id: str, created_at: str) -> None:
        dynamodb_client.update_status(job_id, created_at, "COMPLETED")
        log_job_event(job_id, "COMPLETED")

    def mark_failed(self, job_id: str, created_at: str, reason: str = "") -> None:
        """Mark a job failed.

        CMP-CODE-026: writes "FAILED", which report_service counts and
        billing_service does not.
        """
        dynamodb_client.update_status(job_id, created_at, "FAILED")
        log_job_event(job_id, "FAILED", reason)

    def is_duplicate(self, job_id: str) -> bool:
        """Check whether this container has already handled a job.

        CMP-CODE-037: idempotency based on process-local memory. Lambda runs
        many concurrent containers, so this catches only the subset of
        duplicates that happen to land on the same one. Real deduplication
        needs a conditional write against DynamoDB
        (ConditionExpression="attribute_not_exists(job_id)") or an explicit
        idempotency table.
        """
        return job_id in PROCESSED_JOBS

    def list_expired(self, days: int = 30) -> list[dict]:
        """Find jobs older than `days`.

        CMP-COST-058: another full table scan, filtered in Python.

        CMP-CODE-038: created_at is compared as an ISO-8601 *string*. That works
        only because the format is fixed-width — any change to the timestamp
        format silently breaks the comparison with no error.
        """
        cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).isoformat()
        jobs = dynamodb_client.scan_all_jobs()
        return [j for j in jobs if j.get("created_at", "") < cutoff]

    def purge(self, job_id: str, created_at: str) -> None:
        dynamodb_client.delete_job(job_id, created_at)
        PROCESSED_JOBS.pop(job_id, None)

