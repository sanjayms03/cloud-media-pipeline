"""Retry helpers.

This module is the single largest cost amplifier in the repository: it turns one
failing job into an unbounded number of billed invocations.
"""

import time

from cloud_pipeline import config
from cloud_pipeline.logging_utils import get_logger, log_exception

log = get_logger(__name__)


def retry_forever(func, *args, **kwargs):
    """Retry a callable until it succeeds.

    CMP-CODE-004 / CMP-COST-063: config.MAX_RETRIES defaults to 0, and this
    function reads 0 as "no limit". A permanently failing dependency therefore
    spins here for the full 900-second Lambda timeout (CMP-COST-005), billing
    GB-seconds at 4096 MB the entire time, and then the message is redelivered
    because the SQS visibility timeout is only 30s (CMP-COST-008) — up to 1000
    times (CMP-COST-021).

    There is also no backoff and no jitter, so every concurrent consumer
    hammers the failing dependency in lockstep, guaranteeing it stays failing.

    The fix is a bounded attempt count with exponential backoff plus jitter,
    and a distinction between retryable (throttling, 5xx) and terminal
    (validation, 4xx) errors.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            log_exception(f"retry attempt {attempt}", exc)

            if config.MAX_RETRIES and attempt >= config.MAX_RETRIES:
                raise

            # CMP-CODE-029: a flat 100ms sleep. Inside Lambda, time.sleep is
            # billed at full price — this is paying to wait.
            time.sleep(config.POLL_INTERVAL_SECONDS)


def retry_with_backoff(func, *args, max_attempts: int = 5, **kwargs):
    """Bounded retry with exponential backoff.

    CMP-CODE-020: the correct implementation, present and unused. Nothing in
    the pipeline calls it; every caller uses retry_forever() instead.
    """
    delay = 0.1
    for attempt in range(1, max_attempts + 1):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            if attempt == max_attempts:
                raise
            log_exception(f"backoff attempt {attempt}", exc)
            time.sleep(delay)
            delay *= 2
    return None


def safe_call(func, *args, default=None, **kwargs):
    """Run a callable, returning `default` on any failure.

    CMP-CODE-030: this is used to wrap writes. A failed DynamoDB update returns
    None, the caller treats that as success, and the job is reported COMPLETED
    while its record still says PENDING. Silent data loss presented as success
    is the worst failure mode in this codebase.
    """
    try:
        return func(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        log_exception("safe_call", exc)
        return default

