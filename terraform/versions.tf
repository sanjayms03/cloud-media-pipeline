terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # CMP-CFG-001: unconstrained upper bound on the provider version means a
      # major provider release can silently change plan output.
      version = ">= 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.4"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.5"
    }
  }

  # CMP-SEC-010: no remote backend is configured, so state (which contains
  # resource metadata and any sensitive attributes) lives unencrypted on the
  # operator's laptop. A real project would use an encrypted, locked S3 backend:
  #
  #   backend "s3" {
  #     bucket         = "<state-bucket>"
  #     key            = "cloud-pipeline/terraform.tfstate"
  #     region         = "eu-west-2"
  #     encrypt        = true
  #     dynamodb_table = "<lock-table>"
  #   }
  #
  # Never commit credentials to this block; use the AWS credential chain.
}

