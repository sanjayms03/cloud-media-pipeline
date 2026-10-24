"""Unit tests for handler.py.

DELIBERATELY INCOMPLETE. Only the shortest happy/obvious paths are covered.
See benchmark/scoring-rubric.md for the catalogue of missing scenarios
(CMP-TEST-001 .. CMP-TEST-012).
"""

import json
import os

os.environ.setdefault("JOBS_TABLE_NAME", "test-jobs")
os.environ.setdefault("INPUT_BUCKET", "test-input")
os.environ.setdefault("OUTPUT_BUCKET", "test-output")
os.environ.setdefault("REPORT_API_TOKEN", "test-token")

from cloud_pipeline import handler  # noqa: E402


def test_health_handler_returns_ok():
    response = handler.health_handler({}, None)
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert body["status"] == "ok"


def test_ingest_handler_rejects_missing_body():
    response = handler.ingest_handler({}, None)
    body = json.loads(response["body"])

    assert response["statusCode"] == 400
    assert body["error"] == "missing body"


def test_ingest_handler_rejects_bad_token():
    event = {
        "body": json.dumps({"customer_id": "cust-0001", "media_format": "mp4"}),
        "headers": {"x-api-token": "wrong"},
    }

    response = handler.ingest_handler(event, None)

    assert response["statusCode"] == 403


def test_ingest_handler_empty_s3_records():
    response = handler.ingest_handler({"Records": []}, None)

    assert response["statusCode"] == 200


# CMP-TEST-001: no test for a successful submission (the 201 path).
# CMP-TEST-002: no test for the batch/list body path.
# CMP-TEST-003: no test that the 500 handler leaks a traceback (CMP-SEC-015).
# CMP-TEST-004: no test for a malformed S3 notification shape (CMP-CODE-048).
# CMP-TEST-005: no test for isBase64Encoded bodies (CMP-CODE-049).
# CMP-TEST-006: no test asserting the timing-unsafe token comparison.

