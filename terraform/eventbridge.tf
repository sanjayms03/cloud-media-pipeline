# ---------------------------------------------------------------------------
# CMP-COST-011: the reporting function runs on rate(1 minute) — 43,200
# invocations a month — to regenerate a summary that the business reads once a
# day. Each run performs a full DynamoDB scan (see report_service.py), so the
# schedule drives both Lambda and DynamoDB read cost.
#
# rate(1 day) would reduce this to ~30 invocations/month: a >99% reduction on
# this path. Confirm with stakeholders that near-real-time reporting is not a
# requirement before changing it.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "report_schedule" {
  name                = "${local.prefix}-report-schedule"
  description         = "Triggers the reporting Lambda"
  schedule_expression = var.schedule_expression

  tags = local.common_tags
}

resource "aws_cloudwatch_event_target" "report" {
  rule      = aws_cloudwatch_event_rule.report_schedule.name
  target_id = "report-lambda"
  arn       = aws_lambda_function.report.arn
}

resource "aws_lambda_permission" "allow_eventbridge_report" {
  statement_id  = "AllowExecutionFromEventBridgeReport"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.report.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.report_schedule.arn
}

# CMP-COST-043: the cleanup function also runs every five minutes even though
# it deletes objects older than 30 days. Hourly or daily is ample. Each run
# performs an unpaginated S3 list (see cleanup_worker.py).
resource "aws_cloudwatch_event_rule" "cleanup_schedule" {
  name                = "${local.prefix}-cleanup-schedule"
  description         = "Triggers the cleanup Lambda"
  schedule_expression = "rate(5 minutes)"

  tags = local.common_tags
}

resource "aws_cloudwatch_event_target" "cleanup" {
  rule      = aws_cloudwatch_event_rule.cleanup_schedule.name
  target_id = "cleanup-lambda"
  arn       = aws_lambda_function.cleanup.arn
}

resource "aws_lambda_permission" "allow_eventbridge_cleanup" {
  statement_id  = "AllowExecutionFromEventBridgeCleanup"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.cleanup.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.cleanup_schedule.arn
}

# CMP-COST-044: a custom event bus with an archive retaining every event
# indefinitely (retention_days = 0) plus replay enabled. Archive storage is
# billed per GB-month and nothing in this repo ever replays these events.
resource "aws_cloudwatch_event_bus" "jobs" {
  name = "${local.prefix}-jobs-bus"

  tags = local.common_tags
}

resource "aws_cloudwatch_event_archive" "jobs" {
  name             = "${local.prefix}-jobs-archive"
  event_source_arn = aws_cloudwatch_event_bus.jobs.arn
  retention_days   = 0
}

