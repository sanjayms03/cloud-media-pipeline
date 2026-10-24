# ---------------------------------------------------------------------------
# cloud-media-pipeline — root module entrypoint.
#
# Resources are organised by service in sibling files:
#
#   networking.tf       VPC, subnets, routes, optional NAT Gateway
#   security_groups.tf  worker / lambda / database security groups
#   iam.tf              execution roles and (over-broad) policies
#   s3.tf               input and output buckets, lifecycle, notifications
#   sqs.tf              jobs queue, DLQ, FIFO billing queue, event source
#   dynamodb.tf         jobs table and its two ALL-projection GSIs
#   lambda.tf           ingest / process / report / cleanup functions
#   ec2.tf              opt-in media worker instance
#   cloudwatch.tf       log groups, metric filters, alarms, dashboard
#   api_gateway.tf      HTTP API, routes, stage
#   eventbridge.tf      schedules, custom bus, archive
#   rds.tf              opt-in database lab
#
# This file holds only cross-cutting resources and guard rails.
# ---------------------------------------------------------------------------

# A budget is the one thing in this repository that genuinely protects you.
# It is created unconditionally and notifies nobody by default — set
# var.budget_notification_email to receive alerts.
resource "aws_budgets_budget" "lab_guardrail" {
  name         = "${local.prefix}-monthly-guardrail"
  budget_type  = "COST"
  limit_amount = var.monthly_budget_limit
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = ["user:Project$cloud-media-pipeline"]
  }

  dynamic "notification" {
    for_each = var.budget_notification_email == "" ? [] : [1]

    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = 80
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.budget_notification_email]
    }
  }
}

# CMP-CFG-004: there is no aws_cloudtrail resource anywhere in this module, so
# no management-event audit trail exists for the lab account.

# CMP-CFG-005: no aws_resourcegroups_group and no enforced tagging policy. The
# `Owner` tag in locals.tf is literally "unassigned" on every resource, which
# makes cost allocation and ownership attribution impossible. Showback reports
# built on these tags will be meaningless.

