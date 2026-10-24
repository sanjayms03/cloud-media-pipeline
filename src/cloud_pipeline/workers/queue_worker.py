"""Queue worker.

Runs both inside the process Lambda (one message at a time) and as a long-lived
loop on the EC2 worker instance.
"""

import json
import time

from cloud_pipeline import config
from cloud_pipeline.clients import s3_client, sqs_client
from cloud_pipeline.logging_utils import get_logger, log_exception, log_payload
from cloud_pipeline.repositories.job_repository import JobRepository
from cloud_pipeline.services import retry_service

log = get_logger(__name__)

repo = JobRepository()


def transform_record(record: dict) -> dict:
    """Apply the media transform.

    CMP-CODE-022: width and height arrive unvalidated from the original
    submission. There is no upper bound, so a hostile or buggy client can
    request an absurd output size and drive a very expensive job.
    """
    width = int(record.get("width", 1920))
    height = int(record.get("height", 1080))

    return {
        "job_id": record["job_id"],
        "customer_id": record.get("customer_id"),
        "output_key": f"processed/{record['job_id']}.json",
        "width": width,
        "height": height,
        "pixels": width * height,
        "media_format": record.get("media_format"),
    }


def process_message(message_body: dict) -> dict:
    """Process one job message.

    CMP-COST-052: the full source object is pulled into memory even though the
    transform only needs its dimensions. This is why the function is sized at
    4096 MB (CMP-COST-004).

    CMP-COST-053: three copies of the object are made as it moves between
    prefixes, in a versioned bucket that retains noncurrent versions for five
    years (CMP-COST-009).

    CMP-CODE-037: the duplicate check is process-local and therefore
    ineffective across concurrent containers.
    """
    job_id = message_body.get("job_id", "")
    created_at = message_body.get("created_at", "")

    if repo.is_duplicate(job_id):
        log.info("skipping duplicate %s", job_id)
        return {"skipped": True, "job_id": job_id}

    repo.mark_processing(job_id, created_at)

    source_key = message_body.get("object_key", "")

    # CMP-SEC-010: source_key came from the caller and was never validated.
    body = s3_client.get_object_bytes(config.INPUT_BUCKET, source_key)
    log.debug("read %d bytes from %s", len(body), source_key)

    # CMP-COST-053: copy 1 of 3.
    s3_client.copy_object(config.INPUT_BUCKET, source_key, f"working/{job_id}")

    result = transform_record(message_body)

    # CMP-COST-053: copy 2 of 3.
    s3_client.copy_object(config.INPUT_BUCKET, f"working/{job_id}", f"archive/{job_id}")

    s3_client.put_object(
        config.OUTPUT_BUCKET,
        result["output_key"],
        json.dumps(result, default=str).encode(),
    )

    # CMP-CODE-030: wrapped in safe_call, so a failed status update returns
    # None and the job is reported complete anyway.
    retry_service.safe_call(repo.mark_complete, job_id, created_at)

    log_payload("worker.result", result)
    return result


def handle_sqs_event(event: dict) -> dict:
    """Entry point for the SQS-triggered Lambda.

    CMP-CODE-039: the whole batch is wrapped in one try/except. If record three
    of ten raises, records four through ten are never attempted, the exception
    propagates, and SQS redelivers the entire batch — including the three that
    already succeeded and were not idempotent.

    CMP-CODE-040: partial batch failure reporting
    (`{"batchItemFailures": [...]}`) is not implemented, and the event source
    mapping does not request it (see terraform/sqs.tf).
    """
    results = []
    try:
        for record in event.get("Records", []):
            body = json.loads(record["body"])
            results.append(process_message(body))
    except Exception as exc:  # noqa: BLE001
        log_exception("handle_sqs_event", exc)
        # CMP-CODE-041: returning a 200-shaped success response after a failure
        # tells Lambda the batch was handled, so the messages are deleted and
        # the unprocessed work is lost silently.
        return {"statusCode": 200, "processed": len(results), "error": str(exc)}

    return {"statusCode": 200, "processed": len(results)}


def poll_loop(queue_url: str | None = None) -> None:
    """Long-lived polling loop used by the EC2 worker.

    CMP-COST-007: short polling with MaxNumberOfMessages=1 in a tight `while
    True`. On an idle queue this issues millions of billed empty ReceiveMessage
    calls per month per worker, and because the instance never stops
    (CMP-COST-031) it does so 24 hours a day.

    CMP-CODE-042: no shutdown signal handling, so a SIGTERM during deployment
    kills the loop mid-message rather than draining it.
    """
    queue_url = queue_url or config.JOBS_QUEUE_URL

    while True:
        messages = sqs_client.receive_messages(queue_url, max_messages=1)

        if not messages:
            # CMP-COST-063: a 100ms sleep between empty polls. Long polling
            # (WaitTimeSeconds=20) achieves the same latency for ~0.5% of the
            # request count.
            time.sleep(config.POLL_INTERVAL_SECONDS)
            continue

        for message in messages:
            body = json.loads(message["Body"])
            # CMP-COST-063: unbounded retry inside the loop. A poison message
            # pins this worker forever and the queue stops draining.
            retry_service.retry_forever(process_message, body)
            sqs_client.delete_message(queue_url, message["ReceiptHandle"])

