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

  # Partial config: bucket/key/region are supplied at init time via -backend-config,
  # not hardcoded here - S3 bucket names are globally unique per-account, so there's
  # no single value to commit to a public repo. Locally: copy backend.hcl.example to
  # backend.hcl (gitignored) and run `terraform init -backend-config=backend.hcl`. In
  # CI: see .github/workflows/deploy.yml, which reads TF_STATE_BUCKET / AWS_REGION
  # from repo secrets/variables - you must set those and create the bucket yourself
  # before the first deploy; Terraform can't create the bucket it stores its own
  # state in. Locking uses S3's native lockfile, no separate DynamoDB table.
  backend "s3" {
    use_lockfile = true
  }
}

provider "aws" {
  # Same region as the state backend, by convention (not a hard requirement) - keeps
  # "where does this deploy" answerable from one place: the AWS_REGION variable.
  region = var.aws_region != "" ? var.aws_region : "us-east-1"
}
