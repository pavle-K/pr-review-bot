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

# Only one LLM provider needs to be set; the Lambda auto-selects based on which key
# is present (Anthropic takes precedence if both are). Leave the other blank.

variable "anthropic_api_key" {
  description = "Anthropic API key for the LLM review summary. Leave blank to use OpenRouter instead."
  type        = string
  sensitive   = true
  default     = ""
}

variable "anthropic_model" {
  description = "Anthropic model ID to use, if anthropic_api_key is set"
  type        = string
  default     = "claude-haiku-4-5"
}

variable "openrouter_api_key" {
  description = "OpenRouter API key for the LLM review summary. Leave blank to use Anthropic instead."
  type        = string
  sensitive   = true
  default     = ""
}

variable "openrouter_model" {
  description = "OpenRouter model ID (e.g. deepseek/deepseek-chat, mistralai/mistral-small, qwen/qwen-2.5-coder-32b-instruct), if openrouter_api_key is set"
  type        = string
  default     = "deepseek/deepseek-chat"
}
