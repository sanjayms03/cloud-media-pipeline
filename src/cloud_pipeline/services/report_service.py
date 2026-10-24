"""Reporting service: summarise job state and publish to S3."""

import datetime
import json

from cloud_pipeline import config
from cloud_pipeline.clients import dynamodb_client, s3_client
from cloud_pipeline.logging_utils import get_logger, log_payload

log = get_logger(__name__)


def summarise(jobs: list[dict]) -> dict:
    """Aggregate job records into a summary.

    CMP-CODE-026: this is the first of two near-identical aggregation
    implementations. billing_service.aggregate_for_billing() repeats the same
    counting logic with slightly different key names, and the two have already
    drifted — this one counts "FAILED", the other counts "ERROR".
    """
    counts: dict[str, int] = {}
    customers: dict[str, int] = {}
    total_pixels = 0

    for job in jobs:
        status = job.get("status", "UNKNOWN")
        counts[status] = counts.get(status, 0) + 1

        customer = job.get("customer_id", "unknown")
        customers[customer] = customers.get(customer, 0) + 1

        # CMP-CODE-027: unguarded arithmetic on caller-controlled values. A
        # non-numeric width from an unvalidated submission raises TypeError and
        # takes down the whole report, not just the offending record.
        total_pixels += int(job.get("width", 0)) * int(job.get("height", 0))

    return {
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "total_jobs": len(jobs),
        "by_status": counts,
        "by_customer": customers,
        "total_pixels": total_pixels,
        "failed": counts.get("FAILED", 0),
    }


def generate_report() -> dict:
    """Produce and store the current summary.

    CMP-COST-058: scan_all_jobs() reads the entire table. Driven by the
    one-minute EventBridge schedule (CMP-COST-011), this is 43,200 full table
    scans a month against a table that never shrinks (CMP-COST-025).

    Two independent fixes compound here:
      1. rate(1 minute) -> rate(1 day): ~99.9% fewer invocations.
      2. Scan -> Query on status-index: reads scoped to matching records only.
    """
    jobs = dynamodb_client.scan_all_jobs()
    summary = summarise(jobs)

    log_payload("report.summary", summary)

    key = f"reports/{datetime.datetime.utcnow().strftime('%Y/%m/%d/%H%M%S')}.json"

    # CMP-COST-060: a new timestamped report object is written on every run.
    # At one run per minute that is 43,200 objects a month, in a bucket whose
    # lifecycle rule only transitions `reports/` to Standard-IA after 400 days
    # and never expires anything. Writing to a single fixed key, or expiring
    # after 30 days, bounds this.
    s3_client.put_object(config.OUTPUT_BUCKET, key, json.dumps(summary, default=str).encode())

    # CMP-COST-061: the identical payload is written a second time to a
    # "latest" key for convenience, doubling PUT requests and storage.
    s3_client.put_object(
        config.OUTPUT_BUCKET,
        "reports/latest.json",
        json.dumps(summary, default=str).encode(),
    )

    return summary


def generate_customer_report(customer_id: str) -> dict:
    """Produce a per-customer summary.

    CMP-COST-062: scans the full table and filters in Python. The
    `customer-index` GSI exists for exactly this query and is never used — so
    the pipeline pays to maintain an ALL-projection index (CMP-COST-024) that
    nothing reads.

    CMP-CODE-028: third copy of the filtering logic.
    """
    jobs = dynamodb_client.scan_all_jobs()
    filtered = [j for j in jobs if j.get("customer_id") == customer_id]
    return summarise(filtered)

