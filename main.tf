terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  # Partial backend config: bucket/key/region/dynamodb_table are supplied at
  # init time via -backend-config (see backend.hcl.example). You must create
  # the S3 bucket and DynamoDB lock table yourself before the first init.
  backend "s3" {}
}

provider "aws" {
  region = var.aws_region
}
