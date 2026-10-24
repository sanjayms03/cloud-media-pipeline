# Scoring rubric

How to score an analysis run against `expected-findings.yaml`. All measurements below were
taken from this tree — nothing here is estimated.

## Measured baseline

Run `make coverage` to reproduce:

```
TOTAL    480 statements    265 missed    62 branches    43% coverage
12 passed, 1 skipped
```

Per-module, lowest first:

| Module | Coverage | Why it matters |
| --- | --- | --- |
| `services/billing_service.py` | **0%** | Invoice arithmetic and MD5 signing entirely untested |
| `services/retry_service.py` | **18%** | The unbounded retry loop (CMP-COST-063) is never exercised |
| `workers/queue_worker.py` | **22%** | Silent message loss (CMP-CODE-041) untested |
| `workers/cleanup_worker.py` | **26%** | Pagination bug and /tmp leak untested |
| `clients/dynamodb_client.py` | 28% | Scan path untested |
| `clients/sqs_client.py` | 32% | Error handling untested |
| `clients/s3_client.py` | 40% | Pagination bug untested |
| `repositories/job_repository.py` | 46% | Idempotency logic untested |
| `handler.py` | 56% | Success path and 500 path untested |
| `services/report_service.py` | 68% | Report generation untested |
| `services/ingest_service.py` | 80% | Validation covered; AWS writes not |

> Note: the original target band was 15–30%. The measured figure is **43%**, because the
> validation helpers are small and pure and therefore cheap to cover. This is reported
> honestly rather than adjusted to hit a target. What matters for the benchmark is not the
> headline number but *which* lines are uncovered — see below.

## The point: uncovered lines map onto the severe findings

The uncovered regions correlate almost exactly with the highest-severity entries in
`expected-findings.yaml`. A test-generation agent that simply raises the percentage has not
succeeded. One that targets these paths has:

| Missing scenario | Guards finding | Severity |
| --- | --- | --- |
| Duplicate SQS delivery processed twice | CMP-CODE-037 | high |
| Mid-batch exception loses remaining messages | CMP-CODE-041 | critical |
| `list_objects` past 1000 keys | CMP-CODE-010 | high |
| `retry_forever` with `MAX_RETRIES=0` never terminates | CMP-COST-063 | critical |
| `safe_call` masks a failed write as success | CMP-CODE-030 | high |
| `summarise` vs `aggregate_for_billing` disagree on failures | CMP-CODE-026 | high |
| `object_key` traversal accepted | CMP-SEC-010 | high |
| 500 response leaks a traceback | CMP-SEC-015 | high |
| Token comparison is not constant-time | CMP-SEC-012 | medium |
| Missing `REPORT_API_TOKEN` falls back to committed default | CMP-SEC-006 | high |
| `width`/`height` unbounded | CMP-CODE-022 | medium |
| Non-numeric `width` crashes the whole report | CMP-CODE-027 | medium |
| Malformed S3 notification shape | CMP-CODE-048 | medium |
| `isBase64Encoded` body never decoded | CMP-CODE-049 | medium |
| `write_cleanup_manifest` leaks a /tmp file per run | CMP-CODE-043 | medium |
| Case-sensitive `media_format` rejects `"MP4"` | CMP-CODE-023 | low |

Fixtures for most of these already exist in `fixtures/sample_records.json`
under `malformed_submissions`.

## Scoring

### Detection (per finding)

| Score | Criteria |
| --- | --- |
| 2 | Correct file **and** correct symbol/resource, with accurate evidence |
| 1 | Correct file, imprecise location or weak evidence |
| 0 | Not reported |
| −1 | Reported with incorrect evidence, or a fabricated location |

### Category weighting

Cost is the primary emphasis, so weight it accordingly:

| Category | Count | Weight |
| --- | --- | --- |
| cost | 26 | ×2 |
| security | 12 | ×1.5 |
| code_health | 6 | ×1 |
| dependency | 2 | ×1 |
| test_coverage | 1 | ×1 |
| configuration | 1 | ×1 |

### Cross-file reasoning bonus

`architecture.yaml` lists eight findings that **cannot** be detected by inspecting a single
file. Award ×2 for each of these detected with correct reasoning stated. An analyser that
finds `visibility_timeout_seconds = 30` but never compares it to the Lambda timeout in
`lambda.tf` scores 1, not 2.

### Penalties

- **−2** for any precise dollar saving stated without assumptions. Cost claims must carry an
  estimation method, as every entry in `expected-findings.yaml` does.
- **−2** for recommending a change gated behind an opt-in variable without noting it is
  already disabled by default.
- **−3** for recommending `terraform apply` or any deployment action.
- **−1** for reporting a dependency as vulnerable without advisory evidence. `CMP-DEP-001`
  and `CMP-DEP-002` are *constraint hygiene* findings; neither claims a CVE.

### Quality gates (pass/fail, independent of score)

A run fails regardless of detection score if it:

1. Recommends enabling any `enable_*` variable.
2. Treats the placeholder secrets as real credentials requiring rotation.
3. Reports the DynamoDB on-demand finding (`CMP-COST-012`) as a guaranteed saving rather
   than a review candidate.
4. Proposes reducing Lambda memory without acknowledging the CPU/duration trade-off.
5. Proposes `batch_size = 10` without first fixing partial batch failure reporting.
6. Reports a clean lint result without noting the suppressions in `pyproject.toml`
   (`CMP-CFG-002`).

## Remediation scoring

For an agent proposing patches:

| Score | Criteria |
| --- | --- |
| 3 | Patch applies cleanly, tests still pass, **and** a new test covers the fixed path |
| 2 | Patch applies cleanly and tests pass |
| 1 | Patch is directionally right but does not apply |
| 0 | No patch |
| −2 | Patch breaks the existing suite or silently changes unrelated behaviour |

Highest-value remediations, in order — all three are correctness bugs, not just cost:

1. **CMP-CODE-041** — silent message loss. Data loss presented as success.
2. **CMP-CODE-037** — ineffective idempotency, made routine by CMP-COST-008.
3. **CMP-CODE-010** — unpaginated listing, which makes cleanup silently ineffective.

Then the largest cost items: CMP-COST-011, CMP-COST-063, CMP-COST-002, CMP-COST-009.

## Reproducing the baseline

```bash
python -m pip install -e ".[dev]"
make coverage            # 43%, 12 passed, 1 skipped
make inventory           # counts of files, resources, deps, tests, finding IDs
make estimate            # cost estimates with assumptions
make lint                # note: suppressions active (CMP-CFG-002)
make security            # bandit, with B101/B311 skipped
```

`make tf-validate` requires Terraform to be installed; it was **not** run when this baseline
was recorded, so HCL validity is unverified.

