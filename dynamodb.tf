resource "aws_dynamodb_table" "guardrails" {
  name         = "pr-review-bot-state"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
}

resource "aws_iam_role_policy" "guardrails_dynamodb" {
  name = "pr-review-bot-guardrails-dynamodb"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:UpdateItem", "dynamodb:TransactWriteItems"]
        Resource = aws_dynamodb_table.guardrails.arn
      }
    ]
  })
}
