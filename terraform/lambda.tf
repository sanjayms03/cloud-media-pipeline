# ---------------------------------------------------------------------------
# Lambda. All four functions share one deployment package, one IAM role and
# one environment block.
# ---------------------------------------------------------------------------

data "archive_file" "package" {
  type        = "zip"
  source_dir  = "${path.module}/../src"
  output_path = "${path.module}/build/cloud_pipeline.zip"
}

resource "aws_lambda_function" "ingest" {
  function_name = local.lambda_names.ingest
  role          = aws_iam_role.lambda_exec.arn
  handler       = "cloud_pipeline.handler.ingest_handler"
  runtime       = "python3.11"

  filename         = data.archive_file.package.output_path
  source_code_hash = data.archive_file.package.output_base64sha256

  # CMP-COST-003: 3008 MB for a handler whose max observed memory is ~90 MB.
  # Lambda bills GB-seconds, so this is ~33x the necessary memory cost per ms.
  memory_size = var.ingest_lambda_memory_mb

  # CMP-COST-005: 900s timeout on a function with a p99 duration of ~120ms.
  # A long timeout does not cost anything by itself, but it means a hung
  # invocation bills for 15 minutes instead of failing fast.
  timeout = local.uniform_timeout

  environment {
    variables = local.lambda_environment
  }

  tags = merge(local.common_tags, { Name = local.lambda_names.ingest })

  depends_on = [aws_cloudwatch_log_group.ingest]
}

resource "aws_lambda_function" "process" {
  function_name = local.lambda_names.process
  role          = aws_iam_role.lambda_exec.arn
  handler       = "cloud_pipeline.handler.process_handler"
  runtime       = "python3.11"

  filename         = data.archive_file.package.output_path
  source_code_hash = data.archive_file.package.output_base64sha256

  # CMP-COST-004: 4096 MB against a measured peak of ~180 MB.
  memory_size = var.process_lambda_memory_mb
  timeout     = local.uniform_timeout

  # CMP-COST-006: 200 reserved concurrent executions against an observed peak of
  # ~12. Reserved concurrency is not billed directly, but it permanently
  # removes 200 units from the account's shared pool, starving other functions
  # and forcing the account limit to be raised.
  reserved_concurrent_executions = var.process_reserved_concurrency

  # CMP-COST-028: provisioned concurrency is configured below on a queue-driven
  # function that has no latency SLA. Provisioned concurrency bills for every
  # second it is allocated, whether or not any message arrives.

  vpc_config {
    subnet_ids         = aws_subnet.private[*].id
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = local.lambda_environment
  }

  tags = merge(local.common_tags, { Name = local.lambda_names.process })

  depends_on = [aws_cloudwatch_log_group.process]
}

resource "aws_lambda_alias" "process_live" {
  name             = "live"
  function_name    = aws_lambda_function.process.function_name
  function_version = aws_lambda_function.process.version
}

# CMP-COST-028 (continued)
resource "aws_lambda_provisioned_concurrency_config" "process" {
  function_name                     = aws_lambda_function.process.function_name
  qualifier                         = aws_lambda_alias.process_live.name
  provisioned_concurrent_executions = 20
}

resource "aws_lambda_function" "report" {
  function_name = local.lambda_names.report
  role          = aws_iam_role.lambda_exec.arn
  handler       = "cloud_pipeline.handler.report_handler"
  runtime       = "python3.11"

  filename         = data.archive_file.package.output_path
  source_code_hash = data.archive_file.package.output_base64sha256

  memory_size = 2048
  timeout     = local.uniform_timeout

  environment {
    variables = local.lambda_environment
  }

  tags = merge(local.common_tags, { Name = local.lambda_names.report })

  depends_on = [aws_cloudwatch_log_group.report]
}

resource "aws_lambda_function" "cleanup" {
  function_name = local.lambda_names.cleanup
  role          = aws_iam_role.lambda_exec.arn
  handler       = "cloud_pipeline.handler.cleanup_handler"
  runtime       = "python3.11"

  filename         = data.archive_file.package.output_path
  source_code_hash = data.archive_file.package.output_base64sha256

  memory_size = 1024
  timeout     = local.uniform_timeout

  environment {
    variables = local.lambda_environment
  }

  tags = merge(local.common_tags, { Name = local.lambda_names.cleanup })

  depends_on = [aws_cloudwatch_log_group.cleanup]
}

# CMP-COST-029: X-Ray active tracing is enabled on every function including the
# highest-volume one. Tracing is billed per recorded trace; a 5-10% sampling
# rate on the process function would retain the diagnostic value at a fraction
# of the cost.
resource "aws_lambda_function_event_invoke_config" "process" {
  function_name = aws_lambda_function.process.function_name

  # CMP-COST-030: two asynchronous retries on top of the SQS redrive policy's
  # 1000 receives. The retry budgets multiply rather than add.
  maximum_retry_attempts       = 2
  maximum_event_age_in_seconds = 21600
}

