# PR Review Bot

An event-driven GitHub PR review bot running on AWS serverless infrastructure. GitHub
sends a webhook on pull request activity, the bot verifies it and acts on it, and the
result is posted back to the PR as a comment.

Deployed with Terraform, applied via GitHub Actions on every push to `main`.

## Architecture (current stage)

```
GitHub PR event -> webhook POST -> API Gateway (HTTP API) -> Lambda (Python 3.11)
  -> verify HMAC SHA-256 signature -> post ack comment back to the PR
```

GCP equivalents, for reference: Lambda ~ Cloud Functions, API Gateway v2 (HTTP API) ~
GCP API Gateway, the Lambda's IAM role ~ a GCP service account.

At this stage the bot only verifies the webhook signature and posts an acknowledgement
comment confirming the PR number, title, and that the signature checked out. It does not
yet fetch diffs, run checks, or call an LLM; that lands in later stages.

## Repository layout

```
.
├── .github/workflows/deploy.yml   CI: terraform init/plan/apply on push to main
├── src/
│   ├── index.py                   Lambda handler: verify signature, route event
│   └── github_client.py           GitHub API: post PR comment
├── main.tf                        Provider + partial S3 backend config
├── variables.tf                   aws_region, webhook_secret, github_token
├── lambda.tf                      Lambda function, IAM role, zipped from src/
├── api.tf                         API Gateway v2 HTTP API, route, integration
├── outputs.tf                     webhook_url output
├── backend.hcl.example             Template for local backend config
└── .gitignore
```

## Prerequisites

- AWS account and credentials with permission to create Lambda, API Gateway, and IAM
  resources
- An S3 bucket and a DynamoDB table for Terraform remote state, created before the
  first `terraform init` (Terraform will not create its own backend). Copy
  `backend.hcl.example` to `backend.hcl` and fill in real names; `backend.hcl` is
  gitignored since bucket/table names are account-specific.
- A GitHub PAT with `Pull requests: read and write` scoped to the test repo you'll use
  (this becomes `GITHUB_TOKEN` / the `BOT_GITHUB_TOKEN` secret)
- A webhook secret you generate yourself, e.g. `openssl rand -hex 32`
- Terraform >= 1.5.0 installed locally if you want to plan/apply by hand
  (`brew install terraform` on macOS)

## Deploying

### Locally

```
cp backend.hcl.example backend.hcl   # then edit bucket/dynamodb_table to real names
terraform init -backend-config=backend.hcl
terraform validate
terraform plan  -var="webhook_secret=<your secret>" -var="github_token=<your PAT>"
terraform apply -var="webhook_secret=<your secret>" -var="github_token=<your PAT>"
```

Note the `webhook_url` output at the end; that's the payload URL for the next step.

### Via GitHub Actions

Set these repository secrets:

- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
- `TF_STATE_BUCKET`, `TF_STATE_LOCK_TABLE` (the backend resources from Prerequisites)
- `WEBHOOK_SECRET`
- `BOT_GITHUB_TOKEN`

Optionally set the repository variable `AWS_REGION` (defaults to `us-east-1`).

Push to `main` and the workflow runs `terraform init/plan/apply` automatically.

## Registering the webhook

In the scratch/test repo you're using: Settings -> Webhooks -> Add webhook.

- Payload URL: the `webhook_url` output (ends in `/webhook`)
- Content type: `application/json`
- Secret: the same value as `webhook_secret` / `WEBHOOK_SECRET`
- Events: "Let me select individual events" -> Pull requests

## Testing it

1. Open a PR on the test repo (or reopen one, or push a new commit to an open PR).
   Within a few seconds a comment should appear: `PR Review Bot: signature verified.`
   followed by the PR number and title.
2. In the repo's webhook settings, check the "Recent Deliveries" tab for a `200`
   response on that delivery.
3. To confirm the signature check actually works, temporarily change the webhook's
   secret in GitHub to something wrong (without touching `WEBHOOK_SECRET` in AWS), open
   another PR, and confirm: the delivery shows a `401`, CloudWatch Logs for the Lambda
   show `signature verification failed`, and no comment is posted. Then set the webhook
   secret back to the correct value.

CloudWatch Logs group: `/aws/lambda/pr-review-bot`.

## Stage notes

- **Stage 1 (current):** signature-verifying webhook receiver that posts an ack
  comment on `opened` / `reopened` / `synchronize` pull request events.
