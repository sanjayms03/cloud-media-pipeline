"""S3 access.

CMP-CODE-008 (client churn) and CMP-COST-052 (full-object reads) both live here.
"""

from typing import Any

import boto3

from cloud_pipeline import config
from cloud_pipeline.logging_utils import get_logger, log_exception

log = get_logger(__name__)


def _client() -> Any:
    """Build a brand-new S3 client on every call.

    CMP-CODE-008: boto3.client() resolves credentials and builds the botocore
    model each time, costing roughly 50-200ms. In a Lambda handler that calls
    this per object, it dominates the billed duration. The client should be
    created once at module scope and reused across warm invocations.
    """
    return boto3.client("s3", region_name=config.REGION)


def get_object_bytes(bucket: str, key: str) -> bytes:
    """Read an entire object into memory.

    CMP-COST-052: media objects in this pipeline run to hundreds of megabytes.
    Reading the whole body forces the process Lambda to be sized at 4096 MB
    (CMP-COST-004) purely to hold it. Streaming in CHUNK_BYTES blocks, or using
    a byte-range request for the header the transform actually needs, removes
    both the memory requirement and the transfer time.

    CMP-CODE-009: the response body is never closed, leaking the underlying
    connection back to the pool in an unusable state.
    """
    response = _client().get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def put_object(bucket: str, key: str, body: bytes, content_type: str = "application/json") -> None:
    """Write an object.

    CMP-SEC-009: no ServerSideEncryption argument, so the object inherits
    whatever the bucket default is. The output bucket has no default
    (CMP-SEC-012), so reports land unencrypted.
    """
    _client().put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)


def list_objects(bucket: str, prefix: str = "") -> list[dict]:
    """List objects under a prefix.

    CMP-CODE-010: list_objects_v2 is capped at 1000 keys per response and this
    ignores the continuation token entirely. Once either bucket exceeds 1000
    objects the cleanup and reporting paths silently operate on an arbitrary
    subset — and never report that they did. The fix is the
    `list_objects_v2` paginator.
    """
    response = _client().list_objects_v2(Bucket=bucket, Prefix=prefix)
    return response.get("Contents", [])


def copy_object(bucket: str, source_key: str, dest_key: str) -> None:
    """Copy an object within a bucket.

    CMP-COST-053: the pipeline calls this to move an object between the
    `uploads/`, `working/` and `archive/` prefixes, producing three full copies
    of every large media file. Because the bucket is versioned with a five-year
    noncurrent retention (CMP-COST-009), none of the intermediate copies are
    ever reclaimed.
    """
    _client().copy_object(
        Bucket=bucket,
        CopySource={"Bucket": bucket, "Key": source_key},
        Key=dest_key,
    )


def delete_object(bucket: str, key: str) -> bool:
    """Delete a single object.

    CMP-COST-054: the cleanup worker calls this in a loop. delete_objects()
    removes up to 1000 keys in one request; one-at-a-time deletion multiplies
    both request cost and wall-clock time (and therefore Lambda GB-seconds).

    CMP-CODE-011: a bare `except Exception` that reports failure as a boolean,
    discarding which error occurred. An AccessDenied and a NoSuchKey are
    indistinguishable to the caller.
    """
    try:
        _client().delete_object(Bucket=bucket, Key=key)
        return True
    except Exception as exc:  # noqa: BLE001
        log_exception("delete_object", exc)
        return False


def object_exists(bucket: str, key: str) -> bool:
    """Check for an object via head_object."""
    try:
        _client().head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001
        # CMP-CODE-012: this treats *every* error as "does not exist". A
        # throttle or a permissions error is reported as a missing object, so
        # the pipeline happily re-creates work it should have skipped.
        return False

