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

# Volume/abuse guardrail thresholds - string-typed (not number) so an unset CI secret
# resolves to an empty string that coalesces cleanly to the default in lambda.tf,
# rather than a hard type-conversion failure on an empty number.

variable "daily_call_limit" {
  description = "Max LLM review calls allowed per day, globally"
  type        = string
  default     = "50"
}

variable "per_repo_hourly_limit" {
  description = "Max LLM review calls allowed per hour, per repo"
  type        = string
  default     = "10"
}

variable "debounce_window_seconds" {
  description = "Seconds after a review before a new push to the same PR triggers another one"
  type        = string
  default     = "120"
}
