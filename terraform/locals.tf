locals {
  prefix     = var.name_prefix
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.name

  # Resource names. These MUST stay in sync with src/cloud_pipeline/config.py
  # and .env.example — the Python layer reads them from environment variables.
  input_bucket_name  = "${local.prefix}-input-${random_id.suffix.hex}"
  output_bucket_name = "${local.prefix}-output-${random_id.suffix.hex}"
  jobs_table_name    = "${local.prefix}-jobs"
  jobs_queue_name    = "${local.prefix}-jobs"
  dlq_name           = "${local.prefix}-jobs-dlq"

  lambda_names = {
    ingest  = "${local.prefix}-ingest"
    process = "${local.prefix}-process"
    report  = "${local.prefix}-report"
    cleanup = "${local.prefix}-cleanup"
  }

  # CMP-COST-005: one timeout for every function regardless of workload shape.
  # ingest finishes in ~120ms; cleanup can legitimately run for minutes.
  uniform_timeout = var.lambda_timeout_seconds

  azs = ["${var.aws_region}a", "${var.aws_region}b"]

  common_tags = {
    Project   = "cloud-media-pipeline"
    Lab       = "true"
    Pipeline  = "media-ingest"
    Reviewed  = "never"
    Owner     = "unassigned"
    Terraform = "true"
  }

  # Shared environment block handed to every Lambda. CMP-CODE-009: the same
  # blob goes to all four functions even though each needs a different subset,
  # which widens the blast radius of a bad value.
  lambda_environment = {
    PIPELINE_ENV  = var.environment
    AWS_REGION_NAME   = var.aws_region
    JOBS_TABLE_NAME   = local.jobs_table_name
    INPUT_BUCKET      = local.input_bucket_name
    OUTPUT_BUCKET     = local.output_bucket_name
    JOBS_QUEUE_URL    = aws_sqs_queue.jobs.url
    DLQ_URL           = aws_sqs_queue.jobs_dlq.url
    LOG_LEVEL         = "DEBUG"
    LOG_FULL_PAYLOADS = "true"
    MAX_RETRIES       = "0"
    REPORT_API_TOKEN  = var.report_api_token
  }
}

resource "random_id" "suffix" {
  byte_length = 4
}

