resource "aws_dynamodb_table" "jobs" {
  name = local.jobs_table_name

  # CMP-COST-012: PAY_PER_REQUEST on a workload that runs at a near-constant
  # 40 WCU / 25 RCU around the clock. This is a REVIEW CANDIDATE, not an
  # automatic saving — validate against CloudWatch ConsumedWriteCapacityUnits
  # over at least 30 days before switching to provisioned capacity with
  # autoscaling. On-demand remains correct if traffic is genuinely spiky.
  billing_mode = var.dynamodb_billing_mode

  hash_key  = "job_id"
  range_key = "created_at"

  attribute {
    name = "job_id"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  attribute {
    name = "status"
    type = "S"
  }

  attribute {
    name = "customer_id"
    type = "S"
  }

  # CMP-COST-024: a GSI that projects ALL attributes, including the large
  # `raw_payload` blob the application stores on every record. Every write to
  # the base table is duplicated in full into this index. Switching to
  # projection_type = "KEYS_ONLY" or INCLUDE with a short attribute list
  # typically removes most of the index's write and storage cost.
  global_secondary_index {
    name            = "status-index"
    hash_key        = "status"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "customer-index"
    hash_key        = "customer_id"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  # CMP-COST-025: TTL is declared but disabled, so completed job records are
  # never removed and the table (plus both ALL-projection GSIs) grows forever.
  ttl {
    attribute_name = "expires_at"
    enabled        = false
  }

  # CMP-COST-026: point-in-time recovery adds continuous backup charges
  # proportional to table size on what is a reconstructible dev table.
  point_in_time_recovery {
    enabled = true
  }

  # CMP-SEC-016: no server_side_encryption block, so the table uses the
  # AWS-owned default key rather than a customer-managed KMS key, despite
  # storing customer identifiers.

  # CMP-COST-027: streams are enabled with NEW_AND_OLD_IMAGES but no consumer
  # exists anywhere in this repository. Verify with
  # `aws dynamodbstreams describe-stream` before disabling.
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  tags = merge(local.common_tags, { Name = local.jobs_table_name })
}

