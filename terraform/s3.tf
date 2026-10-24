# ---------------------------------------------------------------------------
# S3. Input bucket receives uploaded media; output bucket holds reports.
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "input" {
  bucket = local.input_bucket_name

  tags = merge(local.common_tags, { Name = local.input_bucket_name })
}

resource "aws_s3_bucket" "output" {
  bucket = local.output_bucket_name

  tags = merge(local.common_tags, { Name = local.output_bucket_name })
}

# CMP-COST-009: versioning is on but the lifecycle rule retains noncurrent
# versions for 1825 days. Every re-upload of a large media object keeps a full
# copy in Standard storage for five years.
resource "aws_s3_bucket_versioning" "input" {
  bucket = aws_s3_bucket.input.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "input" {
  bucket = aws_s3_bucket.input.id

  rule {
    id     = "retain-noncurrent-far-too-long"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_retention_days
    }

    # CMP-COST-017: no transition to Standard-IA / Glacier Instant Retrieval, and
    # no expiration of current objects, so cold media stays on hot storage.

    # CMP-COST-018: incomplete multipart uploads are never aborted, so failed
    # large uploads accumulate as invisible, billable storage.
  }
}

# CMP-COST-019: the temp/ prefix in the output bucket holds intermediate render
# artefacts that the pipeline never reads again, yet has no expiration rule.
resource "aws_s3_bucket_lifecycle_configuration" "output" {
  bucket = aws_s3_bucket.output.id

  rule {
    id     = "reports-keep-everything"
    status = "Enabled"

    filter {
      prefix = "reports/"
    }

    transition {
      days          = 400
      storage_class = "STANDARD_IA"
    }
  }
}

# ---------------------------------------------------------------------------
# Security posture
# ---------------------------------------------------------------------------

# Baseline public access block. Hardened by default.
resource "aws_s3_bucket_public_access_block" "input" {
  bucket = aws_s3_bucket.input.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# CMP-SEC-009: when the opt-in lab flag is set, every public access protection on
# the OUTPUT bucket is disabled. Default is false; do not enable this outside an
# isolated sandbox account.
resource "aws_s3_bucket_public_access_block" "output" {
  bucket = aws_s3_bucket.output.id

  block_public_acls       = var.enable_public_bucket_lab ? false : true
  block_public_policy     = var.enable_public_bucket_lab ? false : true
  ignore_public_acls      = var.enable_public_bucket_lab ? false : true
  restrict_public_buckets = var.enable_public_bucket_lab ? false : true
}

# CMP-SEC-012: the output bucket has no server-side encryption configuration at
# all, relying only on the account default. The input bucket uses SSE-S3 where
# SSE-KMS with a customer-managed key would be appropriate for media containing
# personal data.
resource "aws_s3_bucket_server_side_encryption_configuration" "input" {
  bucket = aws_s3_bucket.input.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# CMP-SEC-013: no bucket policy enforces aws:SecureTransport, so plaintext HTTP
# requests to either bucket are accepted. The missing statement is:
#
#   {
#     "Effect": "Deny",
#     "Principal": "*",
#     "Action": "s3:*",
#     "Resource": ["<bucket-arn>", "<bucket-arn>/*"],
#     "Condition": { "Bool": { "aws:SecureTransport": "false" } }
#   }

# CMP-SEC-014: neither bucket has access logging enabled, so object-level reads
# and writes leave no audit trail.

# ---------------------------------------------------------------------------
# Event wiring: uploads to input/ trigger the ingest function.
# ---------------------------------------------------------------------------

resource "aws_s3_bucket_notification" "input" {
  bucket = aws_s3_bucket.input.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.ingest.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "uploads/"
  }

  depends_on = [aws_lambda_permission.allow_s3]
}

resource "aws_lambda_permission" "allow_s3" {
  statement_id  = "AllowExecutionFromS3"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.input.arn
}

