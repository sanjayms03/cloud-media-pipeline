provider "aws" {
  region = var.aws_region

  # Credentials come from the standard AWS credential chain. Do not add
  # access_key / secret_key arguments here — that is how real keys end up in Git.

  default_tags {
    tags = {
      Project     = "cloud-media-pipeline"
      Environment = var.environment
      ManagedBy   = "terraform"
      Lab         = "true"
      CostCenter  = "benchmark"
    }
  }
}

provider "archive" {}

provider "random" {}

data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

