# Cost smells

Catalogue of the seeded cost inefficiencies, grouped by lever. Full evidence and remediation
for each is in [`../benchmark/expected-findings.yaml`](../benchmark/expected-findings.yaml);
run `make estimate` for figures derived from editable assumptions.

**No figure in this repository is a quote.** Every claim needs validating against Cost Explorer
and CloudWatch before action.

## Where the money actually goes

Ranked by estimated impact under the default assumptions in `scripts/estimate_costs.py`:

| Rank | Finding | Lever |
| --- | --- | --- |
| 1 | `CMP-COST-011` | One-minute schedule × full table scan |
| 2 | `CMP-COST-009` / `053` | Three copies of every object, retained 5 years |
| 3 | `CMP-COST-002` / `016` | NAT data processing with no gateway endpoints |
| 4 | `CMP-COST-033` / `034` | gp2 root + io1 @ 10k provisioned IOPS |
| 5 | `CMP-COST-001` / `031` | m5.4xlarge at 4% CPU, 24/7 |
| 6 | `CMP-COST-028` | Provisioned concurrency on a queue consumer |
| 7 | `CMP-COST-010` / `014` | DEBUG full-payload logs, never expiring |

The top item is an order of magnitude above the rest, and it is only visible by reading two
files together — the schedule in `eventbridge.tf` is harmless until you see that the handler it
triggers performs a `Scan`.

## By lever

### Frequency

Something cheap, run far too often.

- `CMP-COST-011` — `rate(1 minute)` for a report read once a day. 43,200 runs/month.
- `CMP-COST-043` — `rate(5 minutes)` cleanup for a 30-day retention window.
- `CMP-COST-060` — two report objects written per run.

Fixing frequency is usually the highest-leverage change available and needs no code rewrite.

### Access pattern

The right data, fetched the wrong way.

- `CMP-COST-058` — `Scan` where `Query` on an existing GSI would do. Four call sites.
- `CMP-COST-062` — scan-then-filter-in-Python for per-customer views.
- `CMP-COST-057` — `ConsistentRead=True` where eventual consistency suffices.
- `CMP-COST-052` — whole-object reads where a byte-range would do.

Scan cost scales with *table size*, not result size. With TTL disabled (`CMP-COST-025`), that
cost only ever goes up.

### Sizing

Resources provisioned far above measured need.

- `CMP-COST-001` — m5.4xlarge at ~4% CPU.
- `CMP-COST-003` / `004` — 3008 MB and 4096 MB Lambdas against ~90 MB and ~180 MB peaks.
- `CMP-COST-034` — 10,000 provisioned IOPS against a queue depth of 2.
- `CMP-COST-045` / `046` — db.r6g.2xlarge Multi-AZ with 2 TiB io1, for dev.

> Lambda memory is not a pure cost lever: CPU scales with it, so cutting memory can raise
> duration. Use Lambda Power Tuning to find the actual optimum rather than guessing.
> `CMP-COST-004` is also blocked on fixing `CMP-COST-052` first.

### Lifecycle

Data that is never deleted.

- `CMP-COST-009` — noncurrent versions retained 1825 days, no transitions, no multipart abort.
- `CMP-COST-019` — `temp/` and `processed/` have no lifecycle rule at all.
- `CMP-COST-025` — TTL attribute populated, TTL disabled.
- `CMP-COST-010` — seven log groups at `retention_in_days = 0`.
- `CMP-COST-044` — EventBridge archive, indefinite retention, no replay consumer.

### Duplication

The same thing paid for more than once.

- `CMP-COST-053` — three copies of every object, in a versioned bucket.
- `CMP-COST-024` — two ALL-projection GSIs: a 3× write multiplier.
- `CMP-COST-036` — two log groups capturing identical worker output.
- `CMP-COST-061` — the report payload written twice per run.
- `CMP-COST-039` — two dashboard widgets rendering the same metric.

### Retry amplification

One failure becoming many billed invocations. These compound multiplicatively:

- `CMP-COST-008` — visibility timeout (30s) below the function timeout (900s).
- `CMP-COST-021` — `maxReceiveCount = 1000`.
- `CMP-COST-030` — `maximum_retry_attempts = 2` layered on top.
- `CMP-COST-063` — `retry_forever` spins for the full 900s at 4096 MB.

A single poison message can therefore consume a very large number of full-cost invocations.
`time.sleep` inside Lambda is billed at full rate — you are paying to wait.

### Idle and orphaned

- `CMP-COST-031` — instance running 744 h/month for ~160 h of demand.
- `CMP-COST-028` — 20 provisioned concurrency units on an async consumer.
- `CMP-COST-035` — unassociated Elastic IP.
- `CMP-COST-027` — DynamoDB stream with no consumer.
- `CMP-COST-022` — FIFO queue with no producer or consumer.

### Network path

- `CMP-COST-002` / `016` — NAT data processing for traffic that free gateway endpoints would
  carry. Usually the first thing to check in any VPC with a NAT Gateway.
- `CMP-COST-013` — single NAT serving two AZs, adding cross-AZ transfer.

### Observability

- `CMP-COST-014` — full-payload DEBUG logging. **Ingestion dominates the CloudWatch bill**, so
  reducing log volume matters more than reducing retention.
- `CMP-COST-037` — unbounded custom-metric cardinality from a bare `"JOB"` filter pattern.
- `CMP-COST-038` — 10-second high-resolution alarm.
- `CMP-COST-041` — full access logging into a never-expiring group.

### Not a straightforward saving

Flagged as review candidates, not wins:

- `CMP-COST-012` — DynamoDB on-demand. Cheaper provisioned *only* if traffic is genuinely
  steady. Needs 30+ days of consumed-capacity data first.
- `CMP-COST-032` — Savings Plan on the EC2 worker. Right-size first; never commit to waste.
- `CMP-COST-013` — per-AZ NAT trades transfer charges for a second hourly charge. There is a
  break-even volume.

## Suggested order of work

1. **Free, no trade-off:** VPC gateway endpoints, release the EIP, drop the duplicate log
   group and dashboard widget, enable long polling.
2. **Config-only:** log level and payload logging, log retention, DynamoDB TTL, S3 lifecycle
   rules, remove provisioned concurrency, report schedule.
3. **Needs validation:** EC2 right-sizing and scheduling, EBS gp3 migration, Lambda Power
   Tuning, GSI projections.
4. **Needs code changes:** `Scan` → `Query`, streaming reads, bounded retry, stop copying
   objects between prefixes, batch deletes.
5. **Needs measurement first:** DynamoDB capacity mode, Savings Plans, NAT topology.

Note that several items are *blocked* on others: batch size 10 requires partial-batch-failure
handling; reducing process Lambda memory requires streaming reads first.

