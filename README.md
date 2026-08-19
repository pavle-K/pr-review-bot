# PR Review Bot

An event-driven GitHub PR review bot running on AWS serverless infrastructure. GitHub
sends a webhook on pull request activity, the bot verifies it and acts on it, and the
result is posted back to the PR as a comment.

Deployed with Terraform, applied via GitHub Actions on every push to `main`.

## Architecture (current stage)

```
GitHub PR event -> webhook POST -> API Gateway (HTTP API) -> Lambda (Python 3.11)
  -> verify HMAC SHA-256 signature -> fetch PR files/diff via GitHub API
  -> run static checks -> post checklist comment back to the PR
```

GCP equivalents, for reference: Lambda ~ Cloud Functions, API Gateway v2 (HTTP API) ~
GCP API Gateway, the Lambda's IAM role ~ a GCP service account.

At this stage the bot verifies the webhook signature, fetches the PR's changed files,
and runs a small set of deterministic checks against them: possible committed secrets,
source files changed with no corresponding test changes, and oversized diffs. Results
post as a checklist comment. No LLM involvement yet; that lands in a later stage.

## Repository layout

```
.
├── .github/workflows/deploy.yml   CI: terraform init/plan/apply on push to main
├── src/
│   ├── index.py                   Lambda handler: verify signature, route event
│   ├── github_client.py           GitHub API: fetch PR files, post PR comment
│   └── checks.py                  Static checks: secrets, missing tests, diff size
├── main.tf                        Provider + S3 backend config (state, native locking)
├── variables.tf                   aws_region, webhook_secret, github_token
├── lambda.tf                      Lambda function, IAM role, zipped from src/
├── api.tf                         API Gateway v2 HTTP API, route, integration
├── outputs.tf                     webhook_url output
└── .gitignore
```

## Prerequisites

- AWS account and credentials with permission to create Lambda, API Gateway, and IAM
  resources
- An S3 bucket for Terraform remote state, created and versioned manually before the
  first `terraform init` (Terraform can't create the bucket it stores its own state
  in). State locking uses S3's native lockfile (`use_lockfile = true` in `main.tf`),
  so no separate DynamoDB table is needed. The bucket name is hardcoded in `main.tf`;
  update it there if you're using your own bucket.
- A GitHub PAT with `Pull requests: read and write` scoped to the test repo you'll use
  (this becomes `GITHUB_TOKEN` / the `BOT_GITHUB_TOKEN` secret)
- A webhook secret you generate yourself, e.g. `openssl rand -hex 32`
- Terraform >= 1.5.0 installed locally if you want to plan/apply by hand
  (`brew install terraform` on macOS)

## Deploying

### Locally

```
terraform init
terraform validate
terraform plan  -var="webhook_secret=<your secret>" -var="github_token=<your PAT>"
terraform apply -var="webhook_secret=<your secret>" -var="github_token=<your PAT>"
```

Note the `webhook_url` output at the end; that's the payload URL for the next step.

### Via GitHub Actions

Set these repository secrets:

- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
- `WEBHOOK_SECRET`
- `BOT_GITHUB_TOKEN`

Push to `main` and the workflow runs `terraform init/plan/apply` automatically, reading
the S3 backend bucket/region hardcoded in `main.tf`.

## Registering the webhook

In the scratch/test repo you're using: Settings -> Webhooks -> Add webhook.

- Payload URL: the `webhook_url` output (ends in `/webhook`)
- Content type: `application/json`
- Secret: the same value as `webhook_secret` / `WEBHOOK_SECRET`
- Events: "Let me select individual events" -> Pull requests

## Testing it

1. Open a PR on the test repo (or reopen one, or push a new commit to an open PR).
   Within a few seconds a checklist comment should appear, one line per check
   (secrets, tests, diff size), each marked pass or warn.
2. To exercise each check in isolation, open PRs designed to trip them individually:
   one that adds a line looking like a credential (e.g. `api_key = "sk_live_..."`),
   one that changes a source file with no corresponding test file change, and one with
   a diff over 500 changed lines. Confirm each posts the matching warning, and a small
   clean PR (source + matching test file) posts all-clear on every check.
3. In the repo's webhook settings, check the "Recent Deliveries" tab for a `200`
   response on that delivery.
4. To confirm the signature check actually works, temporarily change the webhook's
   secret in GitHub to something wrong (without touching `WEBHOOK_SECRET` in AWS), open
   another PR, and confirm: the delivery shows a `401`, CloudWatch Logs for the Lambda
   show `signature verification failed`, and no comment is posted. Then set the webhook
   secret back to the correct value.

CloudWatch Logs group: `/aws/lambda/pr-review-bot`.

## Stage notes

- **Stage 1:** signature-verifying webhook receiver that posts an ack comment on
  `opened` / `reopened` / `synchronize` pull request events.
- **Stage 2 (current):** fetches the PR's changed files and runs deterministic checks
  (secrets, missing tests, diff size), posting the results as a checklist comment.
