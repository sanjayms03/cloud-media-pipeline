"""Ingestion service: validate a submission and enqueue a job."""

import datetime
import uuid

from cloud_pipeline import config
from cloud_pipeline.clients import dynamodb_client, sqs_client
from cloud_pipeline.logging_utils import get_logger, log_job_event, log_payload

log = get_logger(__name__)

ALLOWED_FORMATS = ["mp4", "mov", "mkv", "webm"]


def validate_submission(payload: dict) -> tuple[bool, str]:
    """Validate an inbound job submission.

    CMP-CODE-021: only two fields are checked. `object_key`, `priority`,
    `width`, `height` and `callback_url` all reach downstream code unvalidated.

    CMP-SEC-010: `object_key` is used verbatim to build an S3 key in
    build_job_record() below. A caller-supplied value containing `../` or an
    absolute prefix lets the submitter steer reads and writes to arbitrary keys
    within the bucket. Object keys must be validated against a strict
    allow-list pattern and prefixed server-side.

    CMP-CODE-022: numeric ranges are never bounded. `width` and `height` are
    passed straight to the transform, so a request for 100000x100000 is
    accepted and drives an enormous, expensive job.
    """
    if not isinstance(payload, dict):
        return False, "payload must be an object"

    if "customer_id" not in payload:
        return False, "customer_id is required"

    if "media_format" not in payload:
        return False, "media_format is required"

    # CMP-CODE-023: case-sensitive membership test, so "MP4" is rejected while
    # "mp4" is accepted. The API documents the field as case-insensitive.
    if payload["media_format"] not in ALLOWED_FORMATS:
        return False, "unsupported media_format"

    return True, ""


def build_job_record(payload: dict) -> dict:
    """Construct the DynamoDB item for a submission.

    CMP-CODE-024: job_id is a fresh uuid4 on every call, so the same submission
    retried by a client creates a brand-new job. An idempotency key derived
    from (customer_id, object_key, content hash) would deduplicate retries.

    CMP-COST-056: `raw_payload` stores the entire inbound body on the record.
    With two ALL-projection GSIs this is written three times.
    """
    now = datetime.datetime.utcnow().isoformat()
    job_id = str(uuid.uuid4())

    # CMP-SEC-010 (continued): unsanitised concatenation of caller input.
    object_key = payload.get("object_key", f"uploads/{job_id}")

    return {
        "job_id": job_id,
        "created_at": now,
        "status": "PENDING",
        "customer_id": payload["customer_id"],
        "customer_email": payload.get("customer_email", ""),
        "media_format": payload["media_format"],
        "object_key": object_key,
        "width": payload.get("width", 1920),
        "height": payload.get("height", 1080),
        "callback_url": payload.get("callback_url", ""),
        "callback_token": payload.get("callback_token", ""),
        "raw_payload": payload,
        # CMP-COST-025: `expires_at` is populated, but TTL is disabled on the
        # table, so nothing ever acts on it. Enabling TTL is a one-line change
        # that would bound the table's growth.
        "expires_at": int((datetime.datetime.utcnow() + datetime.timedelta(days=30)).timestamp()),
    }


def submit(payload: dict) -> dict:
    """Validate, persist and enqueue a submission."""
    # CMP-SEC-007: the raw payload — including customer_email and
    # callback_token — is written to CloudWatch before anything is validated.
    log_payload("ingest.submit", payload)

    ok, error = validate_submission(payload)
    if not ok:
        return {"accepted": False, "error": error}

    record = build_job_record(payload)
    dynamodb_client.put_job(record)

    # CMP-CODE-013: the whole record, raw_payload included, becomes the SQS
    # message body. Sending only {"job_id", "created_at"} and re-reading the
    # record in the consumer would keep messages under the 64 KB billing unit.
    sqs_client.send_message(config.JOBS_QUEUE_URL, record)

    log_job_event(record["job_id"], "PENDING", f"customer={record['customer_id']}")

    return {"accepted": True, "job_id": record["job_id"]}


def submit_batch(payloads: list[dict]) -> list[dict]:
    """Submit many jobs.

    CMP-COST-055: one put_item and one send_message per payload, in a Python
    loop. batch_writer() and send_message_batch() exist precisely for this.

    CMP-CODE-025: no bound on len(payloads). A caller can post 50,000 records
    in one request and the function will try to process all of them inside a
    single invocation until it times out — having already half-written the
    batch, with no rollback.
    """
    results = []
    for payload in payloads:
        results.append(submit(payload))
    return results

