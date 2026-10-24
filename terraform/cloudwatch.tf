# ---------------------------------------------------------------------------
# CloudWatch logs. CMP-COST-010: retention_in_days = 0 means "never expire".
# The process function logs every payload at DEBUG (see LOG_FULL_PAYLOADS),
# so this group ingests tens of GB a month and then stores it forever.
# Ingestion is the dominant CloudWatch Logs charge; reducing log volume matters
# more than reducing retention, but both apply here.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "ingest" {
  name              = "/aws/lambda/${local.lambda_names.ingest}"
  retention_in_days = var.log_retention_days

  tags = local.common_tags
}

resource "aws_cloudwatch_log_group" "process" {
  name              = "/aws/lambda/${local.lambda_names.process}"
  retention_in_days = var.log_retention_days

  tags = local.common_tags
}

resource "aws_cloudwatch_log_group" "report" {
  name              = "/aws/lambda/${local.lambda_names.report}"
  retention_in_days = var.log_retention_days

  tags = local.common_tags
}

resource "aws_cloudwatch_log_group" "cleanup" {
  name              = "/aws/lambda/${local.lambda_names.cleanup}"
  retention_in_days = var.log_retention_days

  tags = local.common_tags
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/${local.prefix}/worker"
  retention_in_days = var.log_retention_days

  tags = local.common_tags
}

# CMP-COST-036: a second log group capturing the same worker output under a
# different name. Both are written to by the user-data bootstrap, doubling
# ingestion cost for identical content.
resource "aws_cloudwatch_log_group" "worker_debug" {
  name              = "/${local.prefix}/worker-debug"
  retention_in_days = var.log_retention_days

  tags = local.common_tags
}

# ---------------------------------------------------------------------------
# Metrics and alarms
# ---------------------------------------------------------------------------

# CMP-COST-037: a metric filter that emits a custom metric on every single log
# line matching "JOB". Custom metrics are billed per metric per month and this
# filter produces one metric per job status value, creating unbounded metric
# cardinality.
resource "aws_cloudwatch_log_metric_filter" "job_events" {
  name           = "${local.prefix}-job-events"
  log_group_name = aws_cloudwatch_log_group.process.name
  pattern        = "JOB"

  metric_transformation {
    name      = "JobEvents"
    namespace = "the analysis platformLab/Jobs"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "dlq_depth" {
  alarm_name          = "${local.prefix}-dlq-not-empty"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Maximum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.jobs_dlq.name
  }

  # CMP-CODE-012: the alarm has no alarm_actions, so nothing is ever notified.
  # It is monitoring theatre — the DLQ fills silently.

  tags = local.common_tags
}

# CMP-COST-038: a high-resolution (10-second period) alarm on a Lambda metric
# that only needs 5-minute granularity. High-resolution alarms are billed at a
# significantly higher rate than standard alarms.
resource "aws_cloudwatch_metric_alarm" "process_errors" {
  alarm_name          = "${local.prefix}-process-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 10
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.process.function_name
  }

  tags = local.common_tags
}

# CMP-COST-039: a dashboard refreshing a dozen widgets, several of which query
# the same metric already shown elsewhere. Dashboards beyond the free tier are
# billed per dashboard per month.
resource "aws_cloudwatch_dashboard" "lab" {
  dashboard_name = "${local.prefix}-overview"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          region  = var.aws_region
          title   = "Process invocations"
          metrics = [["AWS/Lambda", "Invocations", "FunctionName", local.lambda_names.process]]
        }
      },
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          region  = var.aws_region
          title   = "Process invocations (duplicate widget)"
          metrics = [["AWS/Lambda", "Invocations", "FunctionName", local.lambda_names.process]]
        }
      },
    ]
  })
}

