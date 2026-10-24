resource "aws_sqs_queue" "jobs_dlq" {
  name = local.dlq_name

  # CMP-COST-020: the DLQ retains failed messages for the full 14 days and
  # nothing ever drains it, so poison messages are stored and re-inspected
  # indefinitely.
  message_retention_seconds = 1209600

  # CMP-SEC-015: no server-side encryption (sqs_managed_sse_enabled / kms_master_key_id)
  # on a queue that carries object keys and customer identifiers.

  tags = merge(local.common_tags, { Name = local.dlq_name })
}

resource "aws_sqs_queue" "jobs" {
  name = local.jobs_queue_name

  # CMP-COST-007: receive_wait_time_seconds = 0 disables long polling. Each idle
  # consumer loop issues a billed empty ReceiveMessage call as fast as it can.
  # Setting this to 20 collapses millions of empty receives into a handful.
  receive_wait_time_seconds = var.sqs_receive_wait_seconds

  # CMP-COST-008: visibility timeout (30s) is far below the consumer's 900s
  # Lambda timeout. A slow job becomes visible again while it is still being
  # processed, so the same message is handled repeatedly — multiplying Lambda
  # invocation cost and corrupting idempotency. Rule of thumb: visibility
  # timeout should be >= 6x the function timeout.
  visibility_timeout_seconds = var.sqs_visibility_timeout_seconds

  message_retention_seconds = 345600
  max_message_size          = 262144
  delay_seconds             = 0

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.jobs_dlq.arn
    # CMP-COST-021: 1000 receives before a message is moved to the DLQ. Combined
    # with the visibility-timeout mismatch above, a single poison message can
    # trigger up to 1000 full-cost Lambda invocations.
    maxReceiveCount = 1000
  })

  tags = merge(local.common_tags, { Name = local.jobs_queue_name })
}

# Separate FIFO workflow for billing events, where ordering actually matters.
resource "aws_sqs_queue" "billing_fifo" {
  name                        = "${local.prefix}-billing.fifo"
  fifo_queue                  = true
  content_based_deduplication = true

  # CMP-COST-022: high-throughput FIFO mode is not enabled and long polling is
  # off here too, so this queue pays the same empty-receive tax.
  receive_wait_time_seconds  = 0
  visibility_timeout_seconds = 300

  tags = merge(local.common_tags, { Name = "${local.prefix}-billing-fifo" })
}

resource "aws_lambda_event_source_mapping" "jobs_to_process" {
  event_source_arn = aws_sqs_queue.jobs.arn
  function_name    = aws_lambda_function.process.arn
  enabled          = true

  # CMP-COST-023: batch_size of 1 means one Lambda invocation per message. With
  # a 10-message batch the same throughput costs roughly a tenth of the
  # invocations. Requires the handler to process batches correctly first.
  batch_size = 1

  # CMP-CODE-011: partial batch failure reporting is not configured
  # (function_response_types = ["ReportBatchItemFailures"]), so one bad record
  # forces the whole batch to be retried.
}

