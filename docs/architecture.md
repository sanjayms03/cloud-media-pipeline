# Architecture

A media job ingestion pipeline. Jobs arrive over HTTP or via S3 upload, are queued, processed,
recorded in DynamoDB, and summarised into reports.

## Flow

```text
                    ┌──────────────────┐
  POST /jobs ──────▶│  API Gateway     │
                    │  (HTTP API v2)   │
                    └────────┬─────────┘
                             │ AWS_PROXY
                             ▼
  s3://input/uploads/ ─────▶ ingest Lambda ──┬──▶ DynamoDB jobs table
  (ObjectCreated)            3008 MB / 900s  │
                                             └──▶ SQS jobs queue
                                                       │
                                                       │ batch_size = 1
                                                       ▼
                                              process Lambda
                                              4096 MB / 900s
                                              reserved 200, provisioned 20
                                                       │
                      ┌────────────────────────────────┼──────────────────┐
                      ▼                                ▼                  ▼
              s3://input/working/            s3://output/processed/   DynamoDB
              s3://input/archive/                                     (status)
                      │
                      │ after 1000 receives
                      ▼
              SQS dead-letter queue  ──▶ (no consumer)

  EventBridge rate(1 minute) ──▶ report Lambda ──▶ full DynamoDB Scan
                                                ──▶ s3://output/reports/

  EventBridge rate(5 minutes) ─▶ cleanup Lambda ─▶ S3 list + per-key delete
                                                ─▶ DynamoDB Scan + per-item delete

  EC2 worker (opt-in, m5.4xlarge) ──▶ polls SQS jobs queue directly
```

## Components

### Ingestion

`handler.ingest_handler` accepts two event shapes — API Gateway HTTP v2 and S3
`ObjectCreated` notifications — and branches on the presence of a `Records` key. It
authenticates with a shared token header, validates a subset of fields, writes a job record to
DynamoDB and enqueues the whole record to SQS.

The handler is intentionally monolithic (`CMP-CODE-046`): event detection, parsing, auth,
validation, persistence and response construction all live in one function with six exit
points.

### Processing

`workers/queue_worker.handle_sqs_event` is the SQS entrypoint. For each message it checks a
process-local duplicate cache, marks the job `PROCESSING`, reads the source object **in full**
into memory, copies it through two intermediate prefixes, writes a transform result, and marks
the job complete.

The EC2 worker runs `queue_worker.poll_loop` against the same queue — a long-lived short-polling
loop with unbounded retry. Both consumers compete for the same messages.

### Reporting

`services/report_service.generate_report` scans the entire jobs table, aggregates counts, and
writes the summary twice: once under a timestamped key and once to `reports/latest.json`.
Triggered every minute.

`services/billing_service` contains a near-duplicate of the aggregation logic that has drifted
— it counts status `ERROR` where reporting counts `FAILED` (`CMP-CODE-026`).

### Cleanup

`workers/cleanup_worker.run_cleanup` lists stale objects (without pagination), deletes them one
at a time, scans DynamoDB for expired records, and deletes those one at a time too. Runs every
five minutes against a 30-day retention window.

## Data model

Single DynamoDB table, `cloud-pipeline-jobs`:

| Attribute | Role |
| --- | --- |
| `job_id` | Partition key (fresh UUID per submission — no idempotency) |
| `created_at` | Sort key (ISO-8601 string, compared lexicographically) |
| `status` | `PENDING` → `PROCESSING` → `COMPLETED` \| `FAILED` (and `ERROR` from billing) |
| `customer_id` | GSI partition key on `customer-index` |
| `raw_payload` | Full inbound body, replicated into both ALL-projection GSIs |
| `expires_at` | TTL attribute — populated, but TTL is disabled on the table |

Two GSIs exist (`status-index`, `customer-index`), both with `projection_type = ALL`. Neither
is ever queried: `dynamodb_client.query_by_status` is dead code, and every real caller scans
and filters in Python.

## Trust boundaries

| Boundary | Control | Weakness |
| --- | --- | --- |
| Internet → API Gateway | `AWS_IAM` on `POST /jobs` | Optional `NONE`-auth public route |
| API Gateway → ingest | Shared token header | Non-constant-time compare; committed fallback |
| Caller → S3 key | None | `object_key` used verbatim (`CMP-SEC-010`) |
| Lambda → AWS APIs | Shared execution role | `Action: *` on `Resource: *` |
| Worker → AWS APIs | Instance profile | `s3:*` plus unscoped `iam:PassRole` |
| VPC → database | Security group | Entire VPC CIDR, not specific SGs |

All four Lambda functions share one execution role and one environment block, so the
least-privileged function has the same account-wide access as the most privileged.

## Known structural problems

These are architectural, not line-level:

1. **Two competing consumers.** The EC2 worker and the process Lambda both consume the jobs
   queue, with no coordination and no shared idempotency.
2. **Idempotency is process-local.** `PROCESSED_JOBS` is a module-level dict, so deduplication
   only works within a single warm container.
3. **The repository abstraction leaks.** `JobRepository` exists, but services import
   `dynamodb_client` directly, giving two data-access paths with different error handling.
4. **Queue timing is inverted.** A 30-second visibility timeout against a 900-second function
   timeout guarantees concurrent duplicate processing under load.
5. **Retry budgets multiply.** `retry_forever` (unbounded) inside a Lambda with
   `maximum_retry_attempts = 2`, behind a queue with `maxReceiveCount = 1000`.
6. **Failure is reported as success.** `handle_sqs_event`, `safe_call` and `run_cleanup` all
   return success-shaped responses after catching exceptions.
7. **Indexes are paid for but unused.** Both GSIs carry full-projection write cost; no code
   queries them.

See [`../benchmark/architecture.yaml`](../benchmark/architecture.yaml) for the machine-readable
graph, including the orphaned resources and the cross-file findings.

