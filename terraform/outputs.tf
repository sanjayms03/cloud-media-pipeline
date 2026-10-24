output "api_endpoint" {
  description = "Base URL of the HTTP API."
  value       = aws_apigatewayv2_api.lab.api_endpoint
}

output "input_bucket" {
  description = "Name of the media input bucket."
  value       = aws_s3_bucket.input.bucket
}

output "output_bucket" {
  description = "Name of the report output bucket."
  value       = aws_s3_bucket.output.bucket
}

output "jobs_queue_url" {
  description = "URL of the jobs queue. Set as JOBS_QUEUE_URL for the application."
  value       = aws_sqs_queue.jobs.url
}

output "dlq_url" {
  description = "URL of the dead-letter queue."
  value       = aws_sqs_queue.jobs_dlq.url
}

output "jobs_table_name" {
  description = "DynamoDB jobs table name."
  value       = aws_dynamodb_table.jobs.name
}

output "lambda_function_names" {
  description = "All four Lambda function names."
  value       = local.lambda_names
}

output "worker_private_ip" {
  description = "Private IP of the opt-in EC2 worker, if deployed."
  value       = try(aws_instance.worker[0].private_ip, null)
}

output "database_endpoint" {
  description = "Endpoint of the opt-in RDS instance, if deployed."
  value       = try(aws_db_instance.lab[0].endpoint, null)
}

# CMP-SEC-026: this output echoes a credential-shaped value into CLI output and
# into any CI log that runs `terraform output`. The value here is a placeholder,
# but marking an output `sensitive = false` on a secret is the finding. Real
# projects should not output secrets at all.
output "report_api_token_echo" {
  description = "Placeholder token, echoed for lab debugging. Do not copy this pattern."
  value       = var.report_api_token
  sensitive   = false
}

output "enabled_optional_features" {
  description = "Which opt-in (cost or exposure) features are currently switched on."
  value = {
    ec2_worker          = var.enable_ec2_worker
    rds_lab             = var.enable_rds_lab
    public_api          = var.enable_public_api
    public_bucket_lab   = var.enable_public_bucket_lab
    nat_gateway         = var.enable_nat_gateway
    open_security_group = var.enable_open_security_group
  }
}

