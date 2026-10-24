"""Unit tests for ingest_service validation.

DELIBERATELY INCOMPLETE. Pure functions only — nothing that touches AWS, and
none of the failure paths.
"""

import os

os.environ.setdefault("JOBS_TABLE_NAME", "test-jobs")
os.environ.setdefault("INPUT_BUCKET", "test-input")
os.environ.setdefault("OUTPUT_BUCKET", "test-output")

from cloud_pipeline.services import ingest_service  # noqa: E402


def test_validate_accepts_minimal_valid_payload():
    ok, error = ingest_service.validate_submission(
        {"customer_id": "cust-0001", "media_format": "mp4"}
    )

    assert ok is True
    assert error == ""


def test_validate_rejects_missing_customer_id():
    ok, error = ingest_service.validate_submission({"media_format": "mp4"})

    assert ok is False
    assert "customer_id" in error


def test_validate_rejects_unsupported_format():
    ok, error = ingest_service.validate_submission(
        {"customer_id": "cust-0001", "media_format": "avi"}
    )

    assert ok is False
    assert "media_format" in error


def test_validate_rejects_non_dict():
    ok, _ = ingest_service.validate_submission("not-a-dict")

    assert ok is False


def test_build_job_record_sets_pending_status():
    record = ingest_service.build_job_record(
        {"customer_id": "cust-0001", "media_format": "mp4"}
    )

    assert record["status"] == "PENDING"
    assert record["customer_id"] == "cust-0001"
    assert record["job_id"]


# CMP-TEST-007: no test that object_key is sanitised — because it is not
#               (CMP-SEC-010). A test asserting traversal is rejected would fail.
# CMP-TEST-008: no test for width/height bounds (CMP-CODE-022).
# CMP-TEST-009: no test that two identical submissions deduplicate
#               (CMP-CODE-024) — they do not.
# CMP-TEST-010: no test for submit() at all, so no coverage of the
#               DynamoDB/SQS write path.
# CMP-TEST-011: no test for submit_batch() size limits (CMP-CODE-025).
# CMP-TEST-012: no test for the case-sensitivity bug (CMP-CODE-023) —
#               "MP4" is silently rejected.

