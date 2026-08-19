variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "webhook_secret" {
  description = "Shared secret used to verify GitHub webhook HMAC signatures"
  type        = string
  sensitive   = true
}

variable "github_token" {
  description = "GitHub PAT used to post PR comments (Pull requests: read/write, scoped to the target repo)"
  type        = string
  sensitive   = true
}
