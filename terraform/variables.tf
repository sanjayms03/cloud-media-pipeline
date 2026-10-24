variable "aws_region" {
  description = "Region for every lab resource."
  type        = string
  default     = "eu-west-2"
}

variable "environment" {
  description = "Environment label. This lab is a dev-grade workload despite its sizing."
  type        = string
  default     = "dev"
}

variable "name_prefix" {
  description = "Prefix applied to all resource names."
  type        = string
  default     = "cloud-pipeline"
}

variable "vpc_cidr" {
  description = "CIDR for the lab VPC."
  type        = string
  default     = "10.42.0.0/16"
}

# ---------------------------------------------------------------------------
# Cost / sizing knobs. The defaults here are deliberately wasteful so that the
# cost-optimisation agent has something to find. See docs/cost-smells.md.
# ---------------------------------------------------------------------------

variable "worker_instance_type" {
  description = "CMP-COST-001: m5.4xlarge for a worker that averages ~4% CPU."
  type        = string
  default     = "m5.4xlarge"
}

variable "ingest_lambda_memory_mb" {
  description = "CMP-COST-003: 3008 MB for a handler that only parses a small JSON body."
  type        = number
  default     = 3008
}

variable "process_lambda_memory_mb" {
  description = "CMP-COST-004: 4096 MB for a transform that peaks around 180 MB."
  type        = number
  default     = 4096
}

variable "lambda_timeout_seconds" {
  description = "CMP-COST-005: 900s (the maximum) applied uniformly to every function."
  type        = number
  default     = 900
}

variable "process_reserved_concurrency" {
  description = "CMP-COST-006: reserved concurrency far above observed peak demand."
  type        = number
  default     = 200
}

variable "sqs_receive_wait_seconds" {
  description = "CMP-COST-007: 0 disables long polling, producing constant empty receives."
  type        = number
  default     = 0
}

variable "sqs_visibility_timeout_seconds" {
  description = "CMP-COST-008: 30s is shorter than the 900s Lambda timeout, so in-flight messages are redelivered."
  type        = number
  default     = 30
}

variable "log_retention_days" {
  description = "CMP-COST-010: 0 means never expire. High-volume groups then grow without bound."
  type        = number
  default     = 0
}

variable "schedule_expression" {
  description = "CMP-COST-011: a one-minute schedule for a report that is only read daily."
  type        = string
  default     = "rate(1 minute)"
}

variable "dynamodb_billing_mode" {
  description = "CMP-COST-012: on-demand for a steady, predictable workload. A review candidate, not a guaranteed saving."
  type        = string
  default     = "PAY_PER_REQUEST"
}

variable "noncurrent_version_retention_days" {
  description = "CMP-COST-009: noncurrent object versions are retained for ~5 years."
  type        = number
  default     = 1825
}

variable "enable_detailed_monitoring" {
  description = "CMP-COST-015: 1-minute EC2 detailed monitoring on an idle instance."
  type        = bool
  default     = true
}

# ---------------------------------------------------------------------------
# Opt-in gates. ALL of these default to false. Flipping any of them to true
# either costs real money or exposes a resource. Read docs/security-lab.md and
# docs/cost-smells.md before changing one.
# ---------------------------------------------------------------------------

variable "enable_rds_lab" {
  description = "Opt-in: Multi-AZ RDS instance. Expensive. Default off."
  type        = bool
  default     = false
}

variable "enable_public_api" {
  description = "Opt-in: unauthenticated public API route. Default off."
  type        = bool
  default     = false
}

variable "enable_public_bucket_lab" {
  description = "Opt-in: relaxes the S3 public access block. Default off."
  type        = bool
  default     = false
}

variable "enable_nat_gateway" {
  description = "Opt-in: NAT Gateway plus EIP. Hourly + per-GB charges. Default off."
  type        = bool
  default     = false
}

variable "enable_open_security_group" {
  description = "Opt-in: adds a 0.0.0.0/0 ingress rule. Default off."
  type        = bool
  default     = false
}

variable "enable_ec2_worker" {
  description = "Opt-in: launches the always-on EC2 worker. Default off."
  type        = bool
  default     = false
}

# ---------------------------------------------------------------------------
# Placeholder configuration. Never a real secret.
# ---------------------------------------------------------------------------

variable "report_api_token" {
  description = "CMP-SEC-004: passed straight into Lambda env vars instead of Secrets Manager."
  type        = string
  default     = "REPLACE_ME_PLACEHOLDER_NOT_A_REAL_SECRET"
  # NOTE (benchmark): sensitive = true is omitted on purpose so the value is
  # echoed in plan output and stored in plaintext state.
}

variable "db_password" {
  description = "CMP-SEC-005: placeholder RDS password with a default committed to the repo."
  type        = string
  default     = "REPLACE_ME_PLACEHOLDER_NOT_A_REAL_SECRET"
}

variable "admin_cidr" {
  description = "CIDR permitted to reach the worker's admin port."
  type        = string
  default     = "10.42.0.0/16"
}

# ---------------------------------------------------------------------------
# Budget guard rail
# ---------------------------------------------------------------------------

variable "monthly_budget_limit" {
  description = "Monthly USD budget for resources tagged Project=cloud-media-pipeline."
  type        = string
  default     = "50"
}

variable "budget_notification_email" {
  description = "Email for the 80%-of-budget alert. Empty disables notifications."
  type        = string
  default     = ""
}

