"""Cleanup worker.

Scheduled every five minutes (CMP-COST-043) to delete artefacts older than 30
days — a mismatch of roughly four orders of magnitude between how often it runs
and how often it has anything to do.
"""

import datetime
import os
import tempfile

from cloud_pipeline import config
from cloud_pipeline.clients import s3_client
from cloud_pipeline.logging_utils import get_logger, log_exception
from cloud_pipeline.repositories.job_repository import JobRepository

log = get_logger(__name__)

repo = JobRepository()

RETENTION_DAYS = 30


def find_stale_objects(bucket: str, prefix: str = "working/") -> list[str]:
    """Return keys older than the retention window.

    CMP-CODE-010: list_objects() does not paginate, so this only ever sees the
    first 1000 keys. The `working/` prefix accumulates one object per job
    (CMP-COST-053), so in practice the cleanup never reaches the backlog and
    storage grows without bound while the function reports success.
    """
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=RETENTION_DAYS)
    stale = []

    for obj in s3_client.list_objects(bucket, prefix):
        if obj.get("LastModified") and obj["LastModified"] < cutoff:
            stale.append(obj["Key"])

    return stale


def purge_objects(bucket: str, keys: list[str]) -> int:
    """Delete objects one at a time.

    CMP-COST-054: delete_objects() accepts 1000 keys per request. This issues
    one request per key, multiplying both request charges and the billed
    duration of the function.
    """
    deleted = 0
    for key in keys:
        if s3_client.delete_object(bucket, key):
            deleted += 1
    return deleted


def purge_expired_jobs() -> int:
    """Delete expired DynamoDB records.

    CMP-COST-025: none of this would be necessary if TTL were enabled on the
    table. DynamoDB TTL deletes expired items at no charge; these delete_item
    calls consume write capacity for exactly the same outcome.

    CMP-COST-059: one delete_item per record rather than a batch_writer().
    """
    expired = repo.list_expired(RETENTION_DAYS)
    for job in expired:
        repo.purge(job["job_id"], job["created_at"])
    return len(expired)


def write_cleanup_manifest(deleted_keys: list[str]) -> str:
    """Write a manifest of what was deleted.

    CMP-CODE-043: the temporary file is created but never removed, and the
    handle is never closed. In a warm Lambda container /tmp is limited to
    512 MB and persists across invocations, so this eventually fills the
    container's disk and every subsequent invocation fails with ENOSPC.
    """
    handle = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)  # noqa: SIM115
    for key in deleted_keys:
        handle.write(key + "\n")
    handle.flush()

    log.info("cleanup manifest written to %s", handle.name)
    return handle.name


def run_cleanup() -> dict:
    """Execute a cleanup pass.

    CMP-CODE-044: a broad except that reports a successful-looking result with
    zero counts. A permissions failure and a genuinely empty bucket produce
    identical output, so the DLQ-style alarm on this path can never fire.
    """
    try:
        stale = find_stale_objects(config.INPUT_BUCKET)
        deleted = purge_objects(config.INPUT_BUCKET, stale)
        purged = purge_expired_jobs()

        manifest = write_cleanup_manifest(stale)

        # CMP-CODE-045: the manifest path is returned to the caller, exposing
        # an internal filesystem path in the API response.
        return {
            "deleted_objects": deleted,
            "purged_jobs": purged,
            "manifest": manifest,
            "tmp_files": len(os.listdir(tempfile.gettempdir())),
        }
    except Exception as exc:  # noqa: BLE001
        log_exception("run_cleanup", exc)
        return {"deleted_objects": 0, "purged_jobs": 0}

