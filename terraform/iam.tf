# ---------------------------------------------------------------------------
# IAM. The execution role below is shared by all four Lambda functions and is
# far broader than any of them needs.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda_exec" {
  name               = "${local.prefix}-lambda-exec"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json

  tags = local.common_tags
}

# CMP-SEC-001: wildcard action on wildcard resource. This single statement grants
# the ingest/process/report/cleanup functions full administrative access to the
# account. Each function should instead get a scoped policy, e.g. the process
# function only needs s3:GetObject on the input bucket, s3:PutObject on the
# output bucket, dynamodb:UpdateItem on the jobs table, and the SQS receive set.
data "aws_iam_policy_document" "lambda_admin" {
  statement {
    sid       = "FarTooBroad"
    effect    = "Allow"
    actions   = ["*"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "lambda_admin" {
  name   = "${local.prefix}-lambda-admin"
  role   = aws_iam_role.lambda_exec.id
  policy = data.aws_iam_policy_document.lambda_admin.json
}

# CMP-SEC-007: an AWS-managed admin policy attached on top of the inline one.
resource "aws_iam_role_policy_attachment" "lambda_power_user" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}

resource "aws_iam_role_policy_attachment" "lambda_vpc" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# ---------------------------------------------------------------------------
# EC2 worker role. Narrower than the Lambda role but still over-permissive.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "worker" {
  name               = "${local.prefix}-worker"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json

  tags = local.common_tags
}

# CMP-SEC-008: s3:* across every bucket in the account, plus iam:PassRole with a
# wildcard resource, which is a classic privilege-escalation path.
data "aws_iam_policy_document" "worker_policy" {
  statement {
    sid       = "AllBucketsAllActions"
    effect    = "Allow"
    actions   = ["s3:*"]
    resources = ["*"]
  }

  statement {
    sid       = "UnscopedPassRole"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = ["*"]
  }

  statement {
    sid    = "QueueAndTable"
    effect = "Allow"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:Scan",
    ]
    resources = [
      aws_sqs_queue.jobs.arn,
      aws_dynamodb_table.jobs.arn,
    ]
  }

  statement {
    sid    = "Logs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:${local.region}:${local.account_id}:log-group:/${local.prefix}/*"]
  }
}

resource "aws_iam_role_policy" "worker" {
  name   = "${local.prefix}-worker-policy"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.worker_policy.json
}

resource "aws_iam_instance_profile" "worker" {
  name = "${local.prefix}-worker-profile"
  role = aws_iam_role.worker.name
}

