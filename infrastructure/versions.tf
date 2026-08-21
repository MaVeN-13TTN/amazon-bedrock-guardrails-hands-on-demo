terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.6"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.2"
    }
  }

  # Single environment, local state by design — see ADR.md decision 7.
  # For anything shared, switch this to an S3 backend with DynamoDB locking.
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.tags
  }
}
