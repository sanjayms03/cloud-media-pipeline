# Terraform — cloud-media-pipeline

**This module is a deliberately flawed benchmark. Do not deploy it to an account you care about.**

## Safe commands (no resources created, no charges)

```bash
terraform fmt -check -recursive .
terraform init -backend=false
terraform validate
```

`init -backend=false` skips backend configuration entirely, so no state bucket is touched and no
credentials are required. This is what CI runs.

## Static analysis

The module is designed to be scanned without deployment:

```bash
tfsec .
checkov -d .
terraform plan -refresh=false   # requires credentials; still creates nothing
```

## If you really must apply

Only in a dedicated sandbox account, with a budget alarm already in place:

```bash
terraform apply -var="budget_notification_email=you@example.com"
```

All opt-in flags default to `false`. Enabling any of them has consequences:

| Flag | Consequence |
| --- | --- |
| `enable_ec2_worker` | m5.4xlarge billed 24/7, plus 500 GiB gp2 and 1 TiB io1 @ 10k IOPS |
| `enable_rds_lab` | db.r6g.2xlarge Multi-AZ, 2 TiB io1 @ 12k IOPS, 35-day backups |
| `enable_nat_gateway` | NAT hourly charge plus per-GB processing on all private egress |
| `enable_public_api` | Anonymous, unauthenticated write endpoint on the public internet |
| `enable_public_bucket_lab` | Disables every public-access protection on the output bucket |
| `enable_open_security_group` | Opens a debug port to `0.0.0.0/0` |

Run `terraform destroy` immediately afterwards and then work through the teardown checklist in
`../docs/reset-and-cleanup.md` — several resources (versioned buckets, log groups, EIPs, the
EventBridge archive) survive or linger after a destroy.

## File map

| File | Contents |
| --- | --- |
| `versions.tf` | Required versions; documents the missing encrypted remote backend |
| `providers.tf` | Provider config and default tags |
| `variables.tf` | All inputs, including the cost knobs and opt-in gates |
| `locals.tf` | Resource naming; must stay in sync with `src/cloud_pipeline/config.py` |
| `main.tf` | Budget guard rail and cross-cutting notes |
| `networking.tf` | VPC, subnets, routes, optional NAT |
| `security_groups.tf` | Worker, Lambda and database security groups |
| `iam.tf` | Execution roles and over-broad policies |
| `s3.tf` | Buckets, versioning, lifecycle, encryption, notifications |
| `sqs.tf` | Jobs queue, DLQ, FIFO queue, event source mapping |
| `dynamodb.tf` | Jobs table, GSIs, TTL, streams |
| `lambda.tf` | Four functions, provisioned concurrency, invoke config |
| `ec2.tf` | Opt-in worker instance and volumes |
| `cloudwatch.tf` | Log groups, metric filter, alarms, dashboard |
| `api_gateway.tf` | HTTP API, routes, stage, access logs |
| `eventbridge.tf` | Schedules, custom bus, archive |
| `rds.tf` | Opt-in database |
| `outputs.tf` | Outputs, including one deliberately unsafe one |

## Seeded findings

Every intentional flaw is tagged inline with a stable ID (`CMP-COST-*`, `CMP-SEC-*`, `CMP-CFG-*`).
Grep for them:

```bash
grep -rn "CMP-COST-" .
grep -rn "CMP-SEC-" .
```

The authoritative list, with evidence and remediation, is `../benchmark/expected-findings.yaml`.

