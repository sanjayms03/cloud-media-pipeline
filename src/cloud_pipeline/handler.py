"""Lambda entrypoints.

`ingest_handler` is deliberately written as one long function that mixes HTTP
parsing, validation, AWS I/O, transformation and response construction
(CMP-CODE-046). The other handlers are thin by comparison.
"""

import json
import traceback

from cloud_pipeline import config
from cloud_pipeline.logging_utils import get_logger, log_exception, log_payload
from cloud_pipeline.services import ingest_service, report_service
from cloud_pipeline.workers import cleanup_worker, queue_worker

log = get_logger(__name__)


def ingest_handler(event, context):  # noqa: C901, PLR0911, PLR0912
    """Handle an API Gateway or S3 event.

    CMP-CODE-046: ~90 lines doing six unrelated jobs — event-shape detection,
    body parsing, authentication, validation, persistence, response building.
    There is no seam to test any one of them in isolation, which is a direct
    cause of the low coverage recorded in benchmark/scoring-rubric.md.

    CMP-CODE-047: cyclomatic complexity well above a reasonable threshold. The
    ruff config silences C901 (CMP-CFG-002) so this never shows up in lint.
    """
    # CMP-SEC-007: the entire event, including headers (which carry the
    # Authorization value) is written to CloudWatch before any processing.
    log_payload("ingest.event", event)

    try:
        # --- event shape detection -----------------------------------------
        if "Records" in event:
            # S3-triggered path.
            records = event["Records"]
            if not records:
                return {"statusCode": 200, "body": json.dumps({"message": "no records"})}

            first = records[0]

            # CMP-CODE-048: unguarded nested key access. A notification shape
            # the code does not expect raises KeyError, which is caught below
            # and returned to the caller as a 500 with a stack trace.
            bucket = first["s3"]["bucket"]["name"]
            key = first["s3"]["object"]["key"]

            payload = {
                "customer_id": "s3-upload",
                "media_format": key.split(".")[-1],
                "object_key": key,
                "source_bucket": bucket,
            }

            result = ingest_service.submit(payload)
            return {"statusCode": 200, "body": json.dumps(result)}

        # --- HTTP path ------------------------------------------------------
        body = event.get("body")

        if body is None:
            return {"statusCode": 400, "body": json.dumps({"error": "missing body"})}

        if isinstance(body, str):
            # CMP-CODE-049: base64-encoded bodies (isBase64Encoded) are never
            # decoded, so binary or compressed submissions fail with a
            # confusing JSON parse error.
            body = json.loads(body)

        # --- authentication -------------------------------------------------
        headers = event.get("headers") or {}
        supplied = headers.get("x-api-token") or headers.get("X-Api-Token") or ""

        # CMP-SEC-012: token comparison with `!=`, which short-circuits on the
        # first differing byte and is therefore timing-attackable. Use
        # hmac.compare_digest. CMP-SEC-006 also applies: when REPORT_API_TOKEN
        # is unset, get_token() returns the committed placeholder, so the
        # endpoint accepts a value that is published in this repository.
        if supplied != config.get_token():
            # CMP-SEC-013: the error response reveals the expected token's
            # length, which narrows a brute-force search considerably.
            return {
                "statusCode": 403,
                "body": json.dumps({"error": "invalid token", "expected_length": len(config.get_token())}),
            }

        # --- batch vs single --------------------------------------------------
        if isinstance(body, list):
            # CMP-CODE-025: no cap on batch size.
            results = ingest_service.submit_batch(body)
            return {"statusCode": 200, "body": json.dumps({"results": results})}

        result = ingest_service.submit(body)

        if not result.get("accepted"):
            return {"statusCode": 400, "body": json.dumps(result)}

        return {
            "statusCode": 201,
            "headers": {
                "Content-Type": "application/json",
                # CMP-SEC-014: permissive CORS echoed from the application
                # layer as well as the API Gateway layer.
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(result),
        }

    except Exception as exc:  # noqa: BLE001
        log_exception("ingest_handler", exc)

        # CMP-SEC-015: the full traceback — file paths, module names, library
        # versions — is returned to the caller. Internal detail like this
        # should be logged with a correlation ID and never serialised into the
        # response.
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": str(exc),
                "trace": traceback.format_exc(),
            }),
        }


def process_handler(event, context):
    """SQS-triggered processing entrypoint."""
    return queue_worker.handle_sqs_event(event)


def report_handler(event, context):
    """EventBridge-triggered reporting entrypoint.

    CMP-COST-011 / CMP-COST-058: invoked once a minute, and each invocation
    performs a full DynamoDB table scan.
    """
    summary = report_service.generate_report()
    return {"statusCode": 200, "body": json.dumps(summary, default=str)}


def cleanup_handler(event, context):
    """EventBridge-triggered cleanup entrypoint.

    CMP-COST-043: invoked every five minutes to delete objects older than 30
    days.
    """
    result = cleanup_worker.run_cleanup()
    return {"statusCode": 200, "body": json.dumps(result, default=str)}


def health_handler(event, context):
    """Health check.

    CMP-CODE-050: reports healthy unconditionally — it never calls
    config.is_configured() or touches a dependency. A function with no table
    name and no queue URL still answers "ok", so this cannot detect the
    misconfiguration it exists to detect.
    """
    return {"statusCode": 200, "body": json.dumps({"status": "ok", "version": "0.3.0"})}

