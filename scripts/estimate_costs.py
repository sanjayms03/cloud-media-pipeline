#!/usr/bin/env python3
"""Estimate the monthly cost of the seeded inefficiencies.

READ THIS FIRST
---------------
Every number this script prints is an ESTIMATE derived from the editable
assumptions in ASSUMPTIONS below. It is NOT a quote, NOT a bill, and NOT
AWS-published pricing. Prices vary by region, by account agreement, by
commitment, and over time.

Use it to rank opportunities by order of magnitude, then validate each one
against Cost Explorer, the AWS Pricing Calculator, and CloudWatch utilisation
data before acting. Each opportunity carries an explicit `validation` step and a
`confidence` rating for exactly this reason.

Usage:
    python scripts/estimate_costs.py
    python scripts/estimate_costs.py --json
    python scripts/estimate_costs.py --assumptions
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

HOURS_PER_MONTH = 730

# ---------------------------------------------------------------------------
# ASSUMPTIONS — edit these to match your region and workload before trusting
# any output. Rates are rough eu-west-2 on-demand list prices and WILL drift.
# ---------------------------------------------------------------------------
ASSUMPTIONS = {
    "region": "eu-west-2",
    "currency": "USD",
    "hours_per_month": HOURS_PER_MONTH,
    "rates": {
        "ec2_m5_4xlarge_hour": 0.856,
        "ec2_m5_large_hour": 0.107,
        "ebs_gp2_gb_month": 0.11,
        "ebs_gp3_gb_month": 0.088,
        "ebs_io1_gb_month": 0.138,
        "ebs_io1_iops_month": 0.072,
        "lambda_gb_second": 0.0000166667,
        "lambda_request": 0.0000002,
        "sqs_request": 0.0000004,
        "cw_logs_ingest_gb": 0.57,
        "cw_logs_store_gb_month": 0.03,
        "cw_custom_metric_month": 0.30,
        "nat_gateway_hour": 0.045,
        "nat_gateway_gb": 0.045,
        "eip_idle_hour": 0.005,
        "ddb_write_request_unit": 0.00000142,
        "ddb_read_request_unit": 0.000000283,
        "s3_standard_gb_month": 0.024,
    },
    "workload": {
        "jobs_per_month": 200_000,
        "avg_object_mb": 180,
        "report_invocations_per_month": 43_200,
        "cleanup_invocations_per_month": 8_760,
        "ingest_avg_duration_ms": 120,
        "process_avg_duration_ms": 2_400,
        "report_avg_duration_ms": 9_000,
        "ddb_table_items": 2_400_000,
        "ddb_avg_item_kb": 14,
        "worker_count": 1,
        "worker_cpu_utilisation_pct": 4,
        "log_gb_per_month": 95,
    },
}

R = ASSUMPTIONS["rates"]
W = ASSUMPTIONS["workload"]


def gb_seconds(invocations: int, duration_ms: float, memory_mb: int) -> float:
    return invocations * (duration_ms / 1000.0) * (memory_mb / 1024.0)


def opportunities() -> list[dict]:
    """Build the estimate set. Each entry explains its own arithmetic."""
    items: list[dict] = []

    # --- CMP-COST-001 / 031 / 032: oversized, always-on EC2 worker ----------
    current = R["ec2_m5_4xlarge_hour"] * HOURS_PER_MONTH * W["worker_count"]
    # Right-size to m5.large AND stop outside business hours (~160h/month).
    proposed = R["ec2_m5_large_hour"] * 160 * W["worker_count"]
    items.append({
        "id": "CMP-COST-001",
        "category": "compute",
        "title": "m5.4xlarge worker at ~4% CPU, running 24/7",
        "evidence": "terraform/ec2.tf: instance_type=m5.4xlarge, no stop schedule, no ASG",
        "current_estimate": round(current, 2),
        "proposed_estimate": round(proposed, 2),
        "confidence": "medium",
        "assumption": f"{W['worker_cpu_utilisation_pct']}% average CPU; 160 business hours/month",
        "recommendation": "Right-size to m5.large (or Graviton m7g.large) and add an EventBridge start/stop schedule. Better still, fold the work into the existing process Lambda and delete the instance.",
        "tradeoff": "A stop schedule adds cold-start latency for out-of-hours jobs. Confirm the queue is genuinely idle overnight first.",
        "validation": "Compute Optimizer recommendation + 30 days of CloudWatch CPUUtilization and SQS ApproximateNumberOfMessagesVisible.",
    })

    # --- CMP-COST-033 / 034: EBS ------------------------------------------
    gp2 = R["ebs_gp2_gb_month"] * 500
    io1 = (R["ebs_io1_gb_month"] * 1024) + (R["ebs_io1_iops_month"] * 10_000)
    current = gp2 + io1
    proposed = (R["ebs_gp3_gb_month"] * 100) + (R["ebs_gp3_gb_month"] * 200)
    items.append({
        "id": "CMP-COST-033",
        "category": "storage",
        "title": "500 GiB gp2 root + 1 TiB io1 @ 10k provisioned IOPS",
        "evidence": "terraform/ec2.tf: root_block_device gp2/500, ebs_block_device io1/1024/10000",
        "current_estimate": round(current, 2),
        "proposed_estimate": round(proposed, 2),
        "confidence": "high",
        "assumption": "Volumes are ~90% empty; measured EBS queue depth never exceeds 2.",
        "recommendation": "Move both volumes to gp3 and shrink to measured usage. Provisioned IOPS is only justified by sustained queue depth.",
        "tradeoff": "Shrinking a volume requires a snapshot-and-restore, i.e. downtime.",
        "validation": "CloudWatch VolumeQueueDepth, VolumeReadOps/VolumeWriteOps, and df output from the instance.",
    })

    # --- CMP-COST-003 / 004: Lambda memory ---------------------------------
    ingest_current = gb_seconds(W["jobs_per_month"], W["ingest_avg_duration_ms"], 3008) * R["lambda_gb_second"]
    ingest_proposed = gb_seconds(W["jobs_per_month"], W["ingest_avg_duration_ms"], 256) * R["lambda_gb_second"]
    process_current = gb_seconds(W["jobs_per_month"], W["process_avg_duration_ms"], 4096) * R["lambda_gb_second"]
    process_proposed = gb_seconds(W["jobs_per_month"], W["process_avg_duration_ms"], 512) * R["lambda_gb_second"]
    items.append({
        "id": "CMP-COST-003",
        "category": "serverless",
        "title": "Lambda memory far above measured peak usage",
        "evidence": "terraform/variables.tf: ingest_lambda_memory_mb=3008, process_lambda_memory_mb=4096",
        "current_estimate": round(ingest_current + process_current, 2),
        "proposed_estimate": round(ingest_proposed + process_proposed, 2),
        "confidence": "medium",
        "assumption": "ingest peaks ~90 MB, process ~180 MB; durations per workload assumptions.",
        "recommendation": "Use AWS Lambda Power Tuning to find the cost/latency optimum per function rather than guessing.",
        "tradeoff": "Lambda scales CPU with memory, so cutting memory can increase duration and partly offset the saving. Power Tuning measures the actual curve. Note the process function must stop loading whole objects into memory (CMP-COST-052) before it can be shrunk.",
        "validation": "CloudWatch Logs Insights on 'Max Memory Used' across 30 days of REPORT lines.",
    })

    # --- CMP-COST-011 / 058: one-minute report doing a full scan -----------
    scan_rru = (W["ddb_table_items"] * W["ddb_avg_item_kb"]) / 4.0
    current_reads = W["report_invocations_per_month"] * scan_rru * R["ddb_read_request_unit"] * 2
    current_lambda = gb_seconds(W["report_invocations_per_month"], W["report_avg_duration_ms"], 2048) * R["lambda_gb_second"]
    current = current_reads + current_lambda
    proposed = current / 1440.0
    items.append({
        "id": "CMP-COST-011",
        "category": "serverless+database",
        "title": "rate(1 minute) report performing a full DynamoDB table scan",
        "evidence": "terraform/eventbridge.tf schedule_expression=rate(1 minute); report_service.generate_report -> dynamodb_client.scan_all_jobs",
        "current_estimate": round(current, 2),
        "proposed_estimate": round(proposed, 2),
        "confidence": "medium",
        "assumption": f"{W['ddb_table_items']:,} items at {W['ddb_avg_item_kb']} KB; strongly consistent reads (2x RRU).",
        "recommendation": "Two independent fixes, both large: (1) move to rate(1 day); (2) replace the Scan with a Query against the existing status-index GSI.",
        "tradeoff": "Daily reporting loses near-real-time visibility. Confirm no stakeholder depends on minute-level freshness.",
        "validation": "DynamoDB ConsumedReadCapacityUnits by operation, and Lambda Invocations/Duration for the report function.",
    })

    # --- CMP-COST-007: short polling ---------------------------------------
    empty_receives = 2_600_000 * W["worker_count"]
    current = empty_receives * R["sqs_request"]
    proposed = (empty_receives / 200.0) * R["sqs_request"]
    items.append({
        "id": "CMP-COST-007",
        "category": "messaging",
        "title": "Long polling disabled; consumers spin on empty receives",
        "evidence": "terraform/sqs.tf receive_wait_time_seconds=0; sqs_client.receive_messages WaitTimeSeconds=0",
        "current_estimate": round(current, 2),
        "proposed_estimate": round(proposed, 2),
        "confidence": "high",
        "assumption": "One worker polling continuously with a 100ms sleep between empty receives.",
        "recommendation": "Set receive_wait_time_seconds=20 on the queue and WaitTimeSeconds=20 in the client. Raise MaxNumberOfMessages to 10.",
        "tradeoff": "Essentially none. Long polling also reduces latency.",
        "validation": "SQS NumberOfEmptyReceives metric before and after.",
    })

    # --- CMP-COST-008 / 021 / 063: retry amplification ---------------------
    wasted_invocations = W["jobs_per_month"] * 0.02 * 50
    current = (wasted_invocations * R["lambda_request"]) + (
        gb_seconds(int(wasted_invocations), W["process_avg_duration_ms"], 4096) * R["lambda_gb_second"]
    )
    items.append({
        "id": "CMP-COST-008",
        "category": "serverless",
        "title": "Visibility timeout < function timeout, maxReceiveCount=1000, unbounded retry loop",
        "evidence": "terraform/sqs.tf visibility_timeout_seconds=30 vs lambda timeout 900; maxReceiveCount=1000; retry_service.retry_forever",
        "current_estimate": round(current, 2),
        "proposed_estimate": round(current * 0.04, 2),
        "confidence": "low",
        "assumption": "2% of jobs fail and are reprocessed ~50 times each. This is the weakest assumption in the file — measure it.",
        "recommendation": "Set visibility timeout to at least 6x the function timeout, reduce maxReceiveCount to ~5, and replace retry_forever with bounded exponential backoff.",
        "tradeoff": "A lower maxReceiveCount moves genuinely transient failures to the DLQ sooner, so the DLQ needs an owner and a redrive process.",
        "validation": "Compare SQS NumberOfMessagesReceived against Lambda Invocations; the ratio exposes the duplication factor directly.",
    })

    # --- CMP-COST-010 / 014 / 036: logs ------------------------------------
    ingest_cost = W["log_gb_per_month"] * R["cw_logs_ingest_gb"]
    store_cost = W["log_gb_per_month"] * 12 * R["cw_logs_store_gb_month"]
    current = ingest_cost + store_cost
    proposed = (W["log_gb_per_month"] * 0.15 * R["cw_logs_ingest_gb"]) + (
        W["log_gb_per_month"] * 0.15 * 0.5 * R["cw_logs_store_gb_month"]
    )
    items.append({
        "id": "CMP-COST-010",
        "category": "observability",
        "title": "DEBUG-level full-payload logging into never-expiring log groups",
        "evidence": "terraform/cloudwatch.tf retention_in_days=0 on 7 groups; config.LOG_FULL_PAYLOADS=true; duplicate worker-debug group",
        "current_estimate": round(current, 2),
        "proposed_estimate": round(proposed, 2),
        "confidence": "medium",
        "assumption": f"{W['log_gb_per_month']} GB/month ingested; ~12 months accumulated storage.",
        "recommendation": "Ingestion is the dominant charge, so fix that first: set LOG_LEVEL=INFO and LOG_FULL_PAYLOADS=false. Then set retention to 14-30 days and delete the duplicate worker-debug group.",
        "tradeoff": "Less log detail makes incident forensics harder. Keep DEBUG available behind a runtime flag.",
        "validation": "CloudWatch IncomingBytes per log group over 30 days.",
    })

    # --- CMP-COST-024: ALL-projection GSIs ---------------------------------
    base_wru = (W["jobs_per_month"] * W["ddb_avg_item_kb"]) / 1.0
    current = base_wru * 3 * R["ddb_write_request_unit"]
    proposed = base_wru * 1.2 * R["ddb_write_request_unit"]
    items.append({
        "id": "CMP-COST-024",
        "category": "database",
        "title": "Two ALL-projection GSIs duplicating a large raw_payload attribute",
        "evidence": "terraform/dynamodb.tf projection_type=ALL on status-index and customer-index; ingest_service stores raw_payload",
        "current_estimate": round(current, 2),
        "proposed_estimate": round(proposed, 2),
        "confidence": "medium",
        "assumption": "Every base-table write is replicated in full to both indexes.",
        "recommendation": "Switch both indexes to KEYS_ONLY or INCLUDE with the few attributes actually queried, and move raw_payload to S3 with only a pointer in the item.",
        "tradeoff": "KEYS_ONLY forces a follow-up GetItem for attributes not projected. Check the read patterns first.",
        "validation": "DynamoDB ConsumedWriteCapacityUnits split by table vs index.",
    })

    # --- CMP-COST-002 / 016: NAT without gateway endpoints -----------------
    nat_hours = R["nat_gateway_hour"] * HOURS_PER_MONTH
    nat_data = (W["jobs_per_month"] * W["avg_object_mb"] / 1024.0) * R["nat_gateway_gb"]
    current = nat_hours + nat_data
    items.append({
        "id": "CMP-COST-002",
        "category": "networking",
        "title": "NAT Gateway carrying S3/DynamoDB traffic with no VPC gateway endpoints",
        "evidence": "terraform/networking.tf: aws_nat_gateway with no aws_vpc_endpoint resources anywhere",
        "current_estimate": round(current, 2),
        "proposed_estimate": round(nat_hours, 2),
        "confidence": "high",
        "assumption": f"{W['jobs_per_month']:,} objects at {W['avg_object_mb']} MB traversing NAT.",
        "recommendation": "Add S3 and DynamoDB gateway VPC endpoints. They are free and remove this traffic from NAT entirely.",
        "tradeoff": "None material. Gateway endpoints are route-table entries.",
        "validation": "NAT Gateway BytesOutToDestination before and after adding the endpoints.",
    })

    # --- CMP-COST-009 / 053: versioned copies ------------------------------
    stored_gb = (W["jobs_per_month"] * W["avg_object_mb"] / 1024.0) * 3
    current = stored_gb * R["s3_standard_gb_month"]
    items.append({
        "id": "CMP-COST-009",
        "category": "storage",
        "title": "Three copies of every object, versioned, with 5-year noncurrent retention",
        "evidence": "workers/queue_worker.process_message makes 2 copy_object calls; terraform/s3.tf noncurrent_days=1825, no transitions, no abort_incomplete_multipart_upload",
        "current_estimate": round(current, 2),
        "proposed_estimate": round(current / 3 * 0.6, 2),
        "confidence": "medium",
        "assumption": "One month of ingest retained; copies accumulate rather than replace.",
        "recommendation": "Stop copying between prefixes (use object tags or a metadata field for state). Add lifecycle transitions to Standard-IA/Glacier IR, expire noncurrent versions after 30 days, and abort incomplete multipart uploads after 7 days.",
        "tradeoff": "Shorter noncurrent retention reduces the recovery window for accidental overwrites.",
        "validation": "S3 Storage Lens, and the BucketSizeBytes metric split by storage class and version status.",
    })

    # --- CMP-COST-028: provisioned concurrency -----------------------------
    current = 20 * 0.000004167 * 3600 * HOURS_PER_MONTH
    items.append({
        "id": "CMP-COST-028",
        "category": "serverless",
        "title": "Provisioned concurrency on a queue-driven function with no latency SLA",
        "evidence": "terraform/lambda.tf aws_lambda_provisioned_concurrency_config provisioned_concurrent_executions=20",
        "current_estimate": round(current, 2),
        "proposed_estimate": 0.0,
        "confidence": "high",
        "assumption": "20 units allocated continuously at 4096 MB.",
        "recommendation": "Remove it. Provisioned concurrency buys cold-start elimination, which an asynchronous SQS consumer does not need.",
        "tradeoff": "Cold starts return. Irrelevant for queue processing; verify no synchronous caller depends on the alias.",
        "validation": "Lambda ProvisionedConcurrencyUtilization — low utilisation confirms it is wasted.",
    })

    # --- CMP-COST-035: idle EIP --------------------------------------------
    current = R["eip_idle_hour"] * HOURS_PER_MONTH
    items.append({
        "id": "CMP-COST-035",
        "category": "networking",
        "title": "Unassociated Elastic IP reserved 'for future use'",
        "evidence": "terraform/ec2.tf aws_eip.worker_reserved, never associated",
        "current_estimate": round(current, 2),
        "proposed_estimate": 0.0,
        "confidence": "high",
        "assumption": "Billed for the full month while unassociated.",
        "recommendation": "Release it. Allocate on demand if a static IP is ever genuinely required.",
        "tradeoff": "The specific IP address is lost.",
        "validation": "describe-addresses and filter for entries with no AssociationId.",
    })

    # --- CMP-COST-037 / 038 / 039: metrics, alarms, dashboards -------------
    current = (120 * R["cw_custom_metric_month"]) + (1 * 0.30) + (1 * 3.00)
    items.append({
        "id": "CMP-COST-037",
        "category": "observability",
        "title": "Unbounded custom-metric cardinality, a high-resolution alarm, and a duplicate dashboard widget",
        "evidence": "terraform/cloudwatch.tf metric filter on pattern 'JOB'; aws_cloudwatch_metric_alarm.process_errors period=10; dashboard with two identical widgets",
        "current_estimate": round(current, 2),
        "proposed_estimate": round(0.30 + 3.00, 2),
        "confidence": "low",
        "assumption": "~120 distinct custom metrics produced by the filter.",
        "recommendation": "Narrow the metric filter pattern, move the errors alarm to a 300s period, and deduplicate the dashboard.",
        "tradeoff": "A coarser alarm period detects error spikes slightly later.",
        "validation": "list-metrics in the SkyForgeLab/Jobs namespace to count actual cardinality.",
    })

    return items


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--assumptions", action="store_true", help="print assumptions and exit")
    args = parser.parse_args()

    if args.assumptions:
        print(json.dumps(ASSUMPTIONS, indent=2))
        return 0

    items = opportunities()
    total_current = sum(i["current_estimate"] for i in items)
    total_proposed = sum(i["proposed_estimate"] for i in items)

    payload = {
        "repository": "cloud-media-pipeline",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "disclaimer": (
            "ESTIMATES ONLY, derived from the assumptions in this script. "
            "Not a quote and not AWS-published pricing. Validate each item against "
            "Cost Explorer, the AWS Pricing Calculator and CloudWatch before acting."
        ),
        "assumptions": ASSUMPTIONS,
        "opportunity_count": len(items),
        "estimated_monthly_current": round(total_current, 2),
        "estimated_monthly_proposed": round(total_proposed, 2),
        "estimated_monthly_delta": round(total_current - total_proposed, 2),
        "opportunities": sorted(
            items, key=lambda i: i["current_estimate"] - i["proposed_estimate"], reverse=True
        ),
    }

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print("=" * 78)
    print("cloud-media-pipeline — ESTIMATED monthly cost opportunities")
    print("=" * 78)
    print(payload["disclaimer"])
    print()
    print(f"{'ID':<16} {'CURRENT':>10} {'PROPOSED':>10} {'DELTA':>10}  CONF    TITLE")
    print("-" * 78)

    for item in payload["opportunities"]:
        delta = item["current_estimate"] - item["proposed_estimate"]
        print(
            f"{item['id']:<16} {item['current_estimate']:>10.2f} "
            f"{item['proposed_estimate']:>10.2f} {delta:>10.2f}  "
            f"{item['confidence']:<7} {item['title'][:60]}"
        )

    print("-" * 78)
    print(
        f"{'TOTAL':<16} {payload['estimated_monthly_current']:>10.2f} "
        f"{payload['estimated_monthly_proposed']:>10.2f} "
        f"{payload['estimated_monthly_delta']:>10.2f}"
    )
    print()
    print(f"All figures in {ASSUMPTIONS['currency']}/month. Run with --json for evidence,")
    print("trade-offs and validation steps per opportunity, or --assumptions to review inputs.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

