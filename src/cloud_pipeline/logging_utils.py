"""Logging helpers.

CMP-COST-014 / CMP-SEC-007 live here: the pipeline logs entire payloads at
DEBUG, including fields that look like personal data, into log groups that
never expire.
"""

import json
import logging
import sys

from cloud_pipeline import config

_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger.

    CMP-CODE-006: this adds a handler every time it is called. Modules call it
    at import time *and* inside functions, so a warm Lambda container
    accumulates handlers and emits the same line several times — multiplying
    CloudWatch ingestion cost for identical content.
    """
    logger = logging.getLogger(name)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(config.LOG_LEVEL)
    return logger


log = get_logger(__name__)


def log_payload(label: str, payload: object) -> None:
    """Dump a full payload to the log.

    CMP-SEC-007: no redaction of any kind. The job records in this pipeline
    carry `customer_email`, `customer_id` and `callback_token`, all of which end
    up in plaintext in CloudWatch. A real implementation would allow-list the
    fields it logs, or hash identifiers.

    CMP-COST-014: payloads here are routinely tens of kilobytes and this runs on
    every message.
    """
    if not config.LOG_FULL_PAYLOADS:
        return
    try:
        log.debug("%s %s", label, json.dumps(payload, default=str))
    except Exception:  # noqa: BLE001
        # CMP-CODE-007: swallowing the serialisation error means a payload that
        # cannot be rendered disappears without trace.
        pass


def log_job_event(job_id: str, status: str, detail: str = "") -> None:
    """Emit a JOB line.

    CMP-COST-037: the CloudWatch metric filter in terraform/cloudwatch.tf
    matches the literal string "JOB" and emits a custom metric for every one of
    these lines. Custom metrics are billed per metric per month.
    """
    log.info("JOB %s status=%s %s", job_id, status, detail)


def log_exception(context: str, exc: Exception) -> None:
    """Log an exception.

    CMP-SEC-008: str(exc) on a botocore error includes the full request context,
    sometimes including bucket names, ARNs and account identifiers. Combined
    with the API Gateway error passthrough in handler.py, this is how internal
    detail reaches callers.
    """
    log.error("%s failed: %s", context, exc)

