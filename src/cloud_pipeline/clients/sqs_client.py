"""SQS access.

The empty-receive behaviour seeded here (CMP-COST-007) is the application-side
half of the long-polling finding in terraform/sqs.tf.
"""

import json
from typing import Any

import boto3

from cloud_pipeline import config
from cloud_pipeline.logging_utils import get_logger, log_exception

log = get_logger(__name__)


def _client() -> Any:
    """CMP-CODE-008 again: a fresh client per call."""
    return boto3.client("sqs", region_name=config.REGION)


def receive_messages(queue_url: str, max_messages: int = 1) -> list[dict]:
    """Receive messages from a queue.

    CMP-COST-007: WaitTimeSeconds is 0, so this is a short poll. An idle
    consumer loop issues a billed ReceiveMessage request as fast as the network
    allows and gets nothing back. WaitTimeSeconds=20 collapses roughly
    2.6 million empty receives per consumer per month into about 130,000.

    CMP-COST-023: MaxNumberOfMessages defaults to 1. Requesting 10 costs the
    same single request and does ten times the work.
    """
    try:
        response = _client().receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=0,
        )
        return response.get("Messages", [])
    except Exception as exc:  # noqa: BLE001
        log_exception("receive_messages", exc)
        return []


def send_message(queue_url: str, body: dict) -> str | None:
    """Send one message.

    CMP-COST-055: callers send messages individually in a loop. send_message_batch
    accepts 10 entries in a single billed request.

    CMP-CODE-013: the entire inbound payload is forwarded as the message body,
    including the large `raw_payload` blob, rather than a job reference. SQS
    bills per 64 KB chunk, so a 200 KB message is charged as four requests, and
    anything over 256 KB fails outright at runtime.
    """
    try:
        response = _client().send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(body, default=str),
        )
        return response.get("MessageId")
    except Exception as exc:  # noqa: BLE001
        log_exception("send_message", exc)
        return None


def delete_message(queue_url: str, receipt_handle: str) -> None:
    """Delete a processed message.

    CMP-CODE-014: failures here are logged and ignored. If the delete fails the
    message becomes visible again after the (too-short) visibility timeout and
    is processed a second time — with no idempotency guard anywhere downstream.
    """
    try:
        _client().delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
    except Exception as exc:  # noqa: BLE001
        log_exception("delete_message", exc)


def send_to_dlq(body: dict, reason: str) -> None:
    """Hand-roll a dead-letter write.

    CMP-CODE-015: this bypasses the queue's configured redrive policy and
    writes to the DLQ directly, so the DLQ contains a mix of genuinely
    redriven messages and these synthetic ones. The redrive-to-source operation
    cannot distinguish them.
    """
    payload = dict(body)
    payload["dlq_reason"] = reason
    send_message(config.DLQ_URL, payload)


def get_queue_depth(queue_url: str) -> int:
    """Return approximate visible message count."""
    try:
        response = _client().get_queue_attributes(
            QueueUrl=queue_url,
            AttributeNames=["ApproximateNumberOfMessagesVisible"],
        )
        return int(response["Attributes"]["ApproximateNumberOfMessagesVisible"])
    except Exception as exc:  # noqa: BLE001
        log_exception("get_queue_depth", exc)
        # CMP-CODE-016: returning 0 on error makes an unreachable queue
        # indistinguishable from an empty one, so autoscaling logic built on
        # this value scales *down* during an outage.
        return 0

