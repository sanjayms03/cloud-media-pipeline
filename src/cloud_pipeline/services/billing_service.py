"""Billing aggregation.

Mostly a duplicate of report_service, kept to demonstrate drift between two
copies of the same logic.
"""

import datetime
import hashlib

from cloud_pipeline import config
from cloud_pipeline.clients import dynamodb_client
from cloud_pipeline.logging_utils import get_logger

log = get_logger(__name__)

# CMP-CODE-003: pricing constants hard-coded in a source file with no reference
# to where they came from or when they were last checked.
PRICE_PER_MEGAPIXEL = 0.00012
PRICE_PER_JOB = 0.05
CURRENCY = "USD"


def aggregate_for_billing(jobs: list[dict]) -> dict:
    """Aggregate jobs for billing.

    CMP-CODE-026: a near-verbatim copy of report_service.summarise(). The two
    have already diverged: this one counts jobs with status "ERROR" while the
    reporting path counts "FAILED". Both statuses are produced elsewhere in the
    codebase, so the invoice and the operational report disagree about how many
    jobs failed — and neither is right.
    """
    counts: dict[str, int] = {}
    customers: dict[str, int] = {}
    total_pixels = 0

    for job in jobs:
        status = job.get("status", "UNKNOWN")
        counts[status] = counts.get(status, 0) + 1

        customer = job.get("customer_id", "unknown")
        customers[customer] = customers.get(customer, 0) + 1

        total_pixels += int(job.get("width", 0)) * int(job.get("height", 0))

    return {
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "total_jobs": len(jobs),
        "by_status": counts,
        "by_customer": customers,
        "total_pixels": total_pixels,
        "errors": counts.get("ERROR", 0),
    }


def calculate_charge(job: dict) -> float:
    """Calculate the charge for one job.

    CMP-CODE-031: float arithmetic on monetary values. Accumulated across
    thousands of jobs this produces rounding drift in invoices. Monetary
    amounts should use Decimal or integer minor units.

    CMP-CODE-022: width/height are unvalidated caller input, so a job claiming
    100000x100000 produces a charge of over a million units.
    """
    megapixels = (int(job.get("width", 0)) * int(job.get("height", 0))) / 1_000_000
    return PRICE_PER_JOB + (megapixels * PRICE_PER_MEGAPIXEL)


def sign_invoice(invoice: dict) -> str:
    """Produce an integrity signature for an invoice.

    CMP-SEC-011: MD5 for an integrity signature, and the "key" is simply
    concatenated with the message rather than used in an HMAC construction.
    MD5 is collision-prone and naive concatenation is vulnerable to length
    extension. Use hmac.new(key, msg, hashlib.sha256) instead.
    """
    payload = f"{config.BILLING_SIGNING_KEY}{invoice.get('total_jobs')}{invoice.get('total_pixels')}"
    return hashlib.md5(payload.encode()).hexdigest()  # noqa: S324


def build_monthly_invoice(customer_id: str) -> dict:
    """Build an invoice for one customer.

    CMP-COST-062: another full-table scan where a Query on `customer-index`
    would do.
    """
    jobs = dynamodb_client.scan_all_jobs()
    customer_jobs = [j for j in jobs if j.get("customer_id") == customer_id]

    invoice = aggregate_for_billing(customer_jobs)
    invoice["customer_id"] = customer_id
    invoice["currency"] = CURRENCY
    invoice["total_charge"] = sum(calculate_charge(j) for j in customer_jobs)
    invoice["signature"] = sign_invoice(invoice)

    return invoice

