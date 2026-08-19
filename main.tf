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

  # bucket/key/region supplied via -backend-config; see backend.hcl.example and
  # .github/workflows/deploy.yml. You must create the bucket yourself first.
  backend "s3" {
    use_lockfile = true
  }
}

provider "aws" {
  region = var.aws_region != "" ? var.aws_region : "us-east-1"
}
