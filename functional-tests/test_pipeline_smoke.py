"""Smoke-level functional test.

Mock-backed and offline by default. Cloud-backed assertions are marked
`@pytest.mark.aws` and skip unless PIPELINE_ENABLE_AWS_TESTS=1.
"""

import json
import os
import pathlib

import pytest

os.environ.setdefault("JOBS_TABLE_NAME", "test-jobs")
os.environ.setdefault("INPUT_BUCKET", "test-input")
os.environ.setdefault("OUTPUT_BUCKET", "test-output")
os.environ.setdefault("JOBS_QUEUE_URL", "https://sqs.eu-west-2.amazonaws.com/000000000000/test")
os.environ.setdefault("REPORT_API_TOKEN", "test-token")

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures"

AWS_TESTS_ENABLED = os.environ.get("PIPELINE_ENABLE_AWS_TESTS") == "1"
requires_aws = pytest.mark.skipif(
    not AWS_TESTS_ENABLED,
    reason="set PIPELINE_ENABLE_AWS_TESTS=1 and configure LocalStack or a sandbox account",
)


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_sample_event_fixture_is_wellformed():
    event = load_fixture("sample_event.json")

    assert event["routeKey"] == "POST /jobs"
    body = json.loads(event["body"])
    assert body["customer_id"] == "cust-0001"


def test_pipeline_submit_path_with_mocked_aws(monkeypatch):
    """Happy path through ingest_service with both AWS calls stubbed."""
    from cloud_pipeline.clients import dynamodb_client, sqs_client
    from cloud_pipeline.services import ingest_service

    written = {}
    sent = {}

    monkeypatch.setattr(dynamodb_client, "put_job", lambda item: written.update(item))
    monkeypatch.setattr(sqs_client, "send_message", lambda url, body: sent.update(body) or "msg-1")

    result = ingest_service.submit(
        {"customer_id": "cust-0001", "media_format": "mp4", "object_key": "uploads/a.mp4"}
    )

    assert result["accepted"] is True
    assert written["status"] == "PENDING"
    assert sent["customer_id"] == "cust-0001"


def test_summarise_counts_statuses():
    from cloud_pipeline.services import report_service

    jobs = load_fixture("sample_records.json")["jobs"]
    summary = report_service.summarise(jobs)

    assert summary["total_jobs"] == 5
    assert summary["by_status"]["COMPLETED"] == 1
    # The FAILED/ERROR split that billing_service disagrees about (CMP-CODE-026).
    assert summary["failed"] == 1


@requires_aws
def test_end_to_end_against_real_endpoints():
    """Full pipeline against LocalStack or a sandbox account.

    CMP-TEST-013: this is a stub. There is no real end-to-end verification
    anywhere in the repository, so nothing catches the queue/timeout
    misconfiguration (CMP-COST-008) or the lost-message path (CMP-CODE-041).
    """
    pytest.skip("end-to-end harness not implemented")


# Missing functional coverage, by design:
#   CMP-TEST-014: no test for duplicate SQS delivery.
#   CMP-TEST-015: no test for partial batch failure (CMP-CODE-039/040).
#   CMP-TEST-016: no test for S3 pagination beyond 1000 keys (CMP-CODE-010).
#   CMP-TEST-017: no test for retry_forever's unbounded loop (CMP-COST-063).
#   CMP-TEST-018: no test that cleanup actually deletes anything.

