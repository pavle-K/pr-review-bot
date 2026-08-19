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

  # State bucket is created and versioned manually (Terraform can't create the
  # bucket it stores its own state in). Locking uses S3's native lockfile, no
  # separate DynamoDB table.
  backend "s3" {
    bucket       = "pavlek-pr-review-bot-tfstate"
    key          = "pr-review-bot/terraform.tfstate"
    region       = "us-east-1"
    use_lockfile = true
  }
}

provider "aws" {
  region = var.aws_region
}
