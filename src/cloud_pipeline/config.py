"""Configuration.

CMP-CODE-002: configuration is read at import time from os.environ with no
validation and no schema. A missing variable yields an empty string rather than
a startup failure, so the error surfaces much later as an opaque AWS ClientError.
"""

import os

# CMP-CODE-003: hard-coded operational constants scattered next to environment
# lookups, with no indication of which are tunable.
DEFAULT_REGION = "eu-west-2"
MAX_BATCH_SIZE = 1000
CHUNK_BYTES = 8 * 1024 * 1024
POLL_INTERVAL_SECONDS = 0.1
REPORT_SCAN_LIMIT = 100000
DEFAULT_TIMEOUT = 900

ENV = os.environ.get("PIPELINE_ENV", "lab")
REGION = os.environ.get("AWS_REGION_NAME", DEFAULT_REGION)

JOBS_TABLE_NAME = os.environ.get("JOBS_TABLE_NAME", "")
INPUT_BUCKET = os.environ.get("INPUT_BUCKET", "")
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET", "")
JOBS_QUEUE_URL = os.environ.get("JOBS_QUEUE_URL", "")
DLQ_URL = os.environ.get("DLQ_URL", "")

# CMP-SEC-004: secrets read from plain environment variables. In the deployed
# stack these come straight from the Lambda environment block, which is visible
# to anyone with lambda:GetFunctionConfiguration and is stored unencrypted in
# Terraform state. They should come from Secrets Manager or an SSM
# SecureString, fetched at runtime and cached.
REPORT_API_TOKEN = os.environ.get("REPORT_API_TOKEN", "")
BILLING_SIGNING_KEY = os.environ.get("BILLING_SIGNING_KEY", "")

# CMP-SEC-006: a hard-coded fallback credential. The value is an obvious
# placeholder, but the pattern — a committed default that silently takes effect
# when the environment variable is absent — is the finding.
FALLBACK_API_TOKEN = "REPLACE_ME_PLACEHOLDER_NOT_A_REAL_SECRET"  # noqa: S105

LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG")

# CMP-COST-014: full request and response payloads are logged by default.
# CloudWatch Logs bills on ingested GB, and these payloads dominate it.
LOG_FULL_PAYLOADS = os.environ.get("LOG_FULL_PAYLOADS", "true").lower() == "true"

# CMP-CODE-004: MAX_RETRIES defaults to 0, which retry_service interprets as
# "unbounded" rather than "do not retry". The naming makes the dangerous value
# look like the safe one.
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "0"))

# CMP-CODE-005: three different timeout values for the same logical operation,
# defined in three places and never reconciled.
S3_TIMEOUT = 5
SQS_TIMEOUT = 60
DDB_TIMEOUT = 900


def get_token() -> str:
    """Return the report API token, falling back to the committed placeholder."""
    return REPORT_API_TOKEN or FALLBACK_API_TOKEN


def is_configured() -> bool:
    """Crude readiness check. Never called by any handler."""
    return bool(JOBS_TABLE_NAME and INPUT_BUCKET and OUTPUT_BUCKET)

