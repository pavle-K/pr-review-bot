data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.module}/src"
  output_path = "${path.module}/lambda.zip"
}

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "pr-review-bot-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "webhook" {
  function_name    = "pr-review-bot"
  role             = aws_iam_role.lambda.arn
  handler          = "index.handler"
  runtime          = "python3.11"
  timeout          = 20
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256

  environment {
    variables = {
      WEBHOOK_SECRET     = var.webhook_secret
      GITHUB_TOKEN       = var.github_token
      ANTHROPIC_API_KEY  = var.anthropic_api_key
      ANTHROPIC_MODEL    = var.anthropic_model != "" ? var.anthropic_model : "claude-haiku-4-5"
      OPENROUTER_API_KEY = var.openrouter_api_key
      OPENROUTER_MODEL   = var.openrouter_model != "" ? var.openrouter_model : "deepseek/deepseek-chat"
      GUARDRAILS_TABLE   = aws_dynamodb_table.guardrails.name

      DAILY_CALL_LIMIT        = var.daily_call_limit != "" ? var.daily_call_limit : "50"
      PER_REPO_HOURLY_LIMIT   = var.per_repo_hourly_limit != "" ? var.per_repo_hourly_limit : "10"
      DEBOUNCE_WINDOW_SECONDS = var.debounce_window_seconds != "" ? var.debounce_window_seconds : "120"

      CONTACT_EMAIL = var.contact_email
    }
  }
}
