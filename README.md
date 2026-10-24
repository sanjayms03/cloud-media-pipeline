# Cloud Media Pipeline

> **WARNING — deliberately vulnerable benchmark repository.**
> Intentionally insecure, intentionally wasteful, intentionally under-tested.
> It exists only as a controlled benchmark for automated code/cloud analysis tooling.
> **Not a production template.** Deploying this Terraform **can incur real AWS charges**.

`cloud-media-pipeline` models a small event-driven media job ingestion service on AWS, seeded
with reproducible, documented flaws so analysis runs can be scored against the ground truth in
[`benchmark/expected-findings.yaml`](benchmark/expected-findings.yaml).

Every seeded flaw carries a stable ID (`CMP-COST-*`, `CMP-SEC-*`, `CMP-CODE-*`, `CMP-DEP-*`,
`CMP-TEST-*`, `CMP-CFG-*`) so results can be diffed across runs.

## Architecture

```text
   API Gateway (HTTP)              EventBridge rate(1 minute)
          |                                  |
          v                                  v
   ingest Lambda  --->  SQS jobs queue  --->  process Lambda  ---> DynamoDB jobs table
          |                    |                     |                     |
          v                    v                     v                     v
   S3 input bucket       SQS dead-letter       S3 output bucket      report Lambda
          ^                                          ^                     |
          |                                          |                     v
   EC2 worker (m5.4xlarge, always on) ---------------+              cleanup Lambda
```

See [`docs/architecture.md`](docs/architecture.md) and
[`benchmark/architecture.yaml`](benchmark/architecture.yaml).

## Layout

| Path | Purpose |
| --- | --- |
| `src/cloud_pipeline/` | Application package (handlers, services, clients, repositories, workers) |
| `terraform/` | AWS infrastructure, intentionally cost-heavy and insecure |
| `unit-tests/` | Deliberately thin unit suite (happy paths only) |
| `functional-tests/` | One mock-backed smoke test |
| `fixtures/` | Deterministic synthetic events and records |
| `scripts/` | Inventory JSON emitter and cost estimator |
| `benchmark/` | Ground-truth findings, architecture graph, scoring rubric |
| `docs/` | Architecture, cost smells, security notes, teardown |

## Quick start

```bash
python -m pip install -e ".[dev]"

make test        # pytest, no AWS credentials required
make coverage    # measured at 43% line coverage; many failure paths untested
make lint        # ruff
make security    # bandit
make inventory   # JSON inventory of the repository
make estimate    # assumption-driven cost estimates (NOT a quote)
```

No test requires AWS credentials. Cloud-backed tests are marked `@pytest.mark.aws` and skip
unless `PIPELINE_ENABLE_AWS_TESTS=1`.

## Terraform

```bash
make tf-fmt
make tf-validate   # terraform init -backend=false && terraform validate
```

CI never runs `terraform apply`. Every expensive or publicly exposed resource is gated behind a
variable defaulting to `false`:

| Variable | Default | Gates |
| --- | --- | --- |
| `enable_ec2_worker` | `false` | Always-on m5.4xlarge worker + 1.5 TiB of EBS |
| `enable_rds_lab` | `false` | Multi-AZ RDS instance |
| `enable_public_api` | `false` | Unauthenticated public API route |
| `enable_public_bucket_lab` | `false` | Relaxed S3 public access block |
| `enable_nat_gateway` | `false` | NAT Gateway + Elastic IP |
| `enable_open_security_group` | `false` | `0.0.0.0/0` ingress rule |

## Safety notes

- No real credentials. Secret-shaped values are obvious placeholders
  (`REPLACE_ME_PLACEHOLDER_NOT_A_REAL_SECRET`).
- All sample data in `fixtures/` is synthetic; emails resolve to `.invalid`.
- Nothing here attacks, scans, or exfiltrates to any third-party system.
- The flaws are **detection targets** for static analysis, not working exploits.
- No dollar figure is a quote. `scripts/estimate_costs.py` publishes its assumptions and labels
  every number an estimate.

## Teardown checklist

Full version in [`docs/reset-and-cleanup.md`](docs/reset-and-cleanup.md):

1. `terraform -chdir=terraform destroy`
2. Empty **and** delete both S3 buckets — versioned, so remove noncurrent versions and abort
   incomplete multipart uploads.
3. Delete the CloudWatch log groups (`/aws/lambda/cloud-pipeline-*`, `/cloud-pipeline/*`,
   `/aws/apigateway/cloud-pipeline`) — they have no expiry.
4. Purge and delete the SQS queues, including the DLQ and the FIFO queue.
5. Release the Elastic IPs.
6. Delete the EventBridge archive (retains events indefinitely).
7. Confirm Cost Explorer shows no residual spend after 48 hours.

