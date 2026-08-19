# PR Review Bot

An event-driven GitHub PR review bot running on AWS serverless infrastructure. GitHub
sends a webhook on pull request activity, the bot verifies it and acts on it, and the
result is posted back to the PR as a comment.

Deployed with Terraform, applied via GitHub Actions on every push to `main`.

## Architecture (current stage)

```
GitHub PR event -> webhook POST -> API Gateway (HTTP API) -> Lambda (Python 3.11)
  -> verify HMAC SHA-256 signature -> fetch PR files/diff via GitHub API
  -> run static checks + LLM review -> post combined comment back to the PR
```

GCP equivalents, for reference: Lambda ~ Cloud Functions, API Gateway v2 (HTTP API) ~
GCP API Gateway, the Lambda's IAM role ~ a GCP service account.

At this stage the bot verifies the webhook signature, fetches the PR's changed files,
runs deterministic checks against them (possible committed secrets, source files
changed with no corresponding test changes, oversized diffs), and sends a
relevance-ranked subset of the diff to an LLM for a plain-English summary, risk
callouts, and a check on whether the diff matches the PR description. Both sections
post as one comment. If the LLM call fails, times out, or no provider is configured,
the summary section says so and the static checks still post; the webhook never fails
outright because of the LLM.

**Diff selection, not truncation.** Large diffs aren't sent in file order until an
arbitrary cutoff (that silently dropped whatever came after it, including real code) -
each changed file is scored (path risk keywords like `auth`/`payment`/`migration`
score highest, then churn, discounted for whitespace/import-only changes) and files are
packed whole, highest-scoring first, into a fixed token budget. Lockfiles, `dist/`,
`build/`, `node_modules/`, minified, and binary/image files are filtered out entirely
before scoring. Files that don't fit are passed to the model as a filename-only list
(no content) alongside the ones it *was* shown, and the model itself groups them into a
few human-readable categories with counts for a `## Scope` section in its response
(e.g. "6 UI components, 3 pages, 2 tests") - it categorizes by whatever it actually
observes in the paths for that PR, not a hardcoded taxonomy, so this works the same way
whether the repo is a JS frontend, a Python backend, a Rust CLI, or anything else.

**LLM provider is picked automatically from whichever API key secret is set**, no code
change needed to switch:

- `ANTHROPIC_API_KEY` set -> calls Claude directly (model: `ANTHROPIC_MODEL`, default
  `claude-haiku-4-5`)
- otherwise, `OPENROUTER_API_KEY` set -> calls OpenRouter's OpenAI-compatible endpoint
  (model: `OPENROUTER_MODEL`, default `deepseek/deepseek-chat`); this is how you'd
  point it at Mistral, Qwen, GLM, or any other OpenRouter-hosted model, just by setting
  `OPENROUTER_MODEL` to that model's OpenRouter ID
- neither set -> the bot still posts, just without a summary section

Both calls are plain `urllib.request` HTTPS calls, no SDK, consistent with the rest of
the project's dependency-free approach.

**Volume/abuse guardrails on the LLM step.** The static checks always run and always
post; these guardrails only gate the optional LLM call, so a webhook never fails or
goes silent because of them. Backed by one DynamoDB table (`pr-review-bot-state`),
checked in this order, entirely before any provider is called:

1. **Kill switch** - a DynamoDB item (`pk = config#ai_reviews_enabled`, attribute
   `enabled` boolean). Flip it to instantly disable all LLM reviews without a
   redeploy: `aws dynamodb put-item --table-name pr-review-bot-state --item '{"pk":
   {"S":"config#ai_reviews_enabled"},"enabled":{"BOOL":false}}'`. Missing item means
   enabled (fail-open), so a fresh deploy isn't silently disabled.
2. **Daily global cap, per-repo hourly cap, and per-PR debounce** - checked and
   reserved together in a single atomic DynamoDB transaction (`claim_review_slot` in
   `src/guardrails.py`), so concurrent webhook deliveries can't race past a limit and
   budget is only ever spent on calls that actually proceed. Whichever guardrail blocks
   the call, the static checks still post with a one-line note instead of the summary
   (e.g. "AI review skipped: daily limit reached, will resume tomorrow.").

All three thresholds are named constants at the top of `src/guardrails.py`, and
env-overridable without touching code: `DAILY_CALL_LIMIT` (default 50/day),
`PER_REPO_HOURLY_LIMIT` (default 10/hour/repo), `DEBOUNCE_WINDOW_SECONDS` (default
120s - a burst of pushes to the same PR only triggers one review per window, not one
per push). Tune them via the `daily_call_limit` / `per_repo_hourly_limit` /
`debounce_window_seconds` Terraform variables, or the matching `DAILY_CALL_LIMIT` /
`PER_REPO_HOURLY_LIMIT` / `DEBOUNCE_WINDOW_SECONDS` GitHub Actions repository
*variables* (not secrets - these aren't sensitive). Counter items expire automatically
via DynamoDB TTL, so there's no cron/reset job; a new date or hour key just starts at
zero. Every successful LLM call also logs its estimated input token count, included/
excluded file counts, and the repo/PR to CloudWatch, so cost is traceable after the
fact even though nothing here enforces a dollar cap directly.

## Repository layout

```
.
├── .github/workflows/deploy.yml   CI: terraform init/plan/apply on push to main
├── src/
│   ├── index.py                   Lambda handler: verify signature, route event
│   ├── github_client.py           GitHub API: fetch PR files, post PR comment
│   ├── checks.py                  Static checks: secrets, missing tests, diff size
│   ├── reviewer.py                LLM review: Anthropic or OpenRouter, picked by env
│   └── guardrails.py              Volume/abuse guardrails: kill switch, budget caps
├── main.tf                        Provider + S3 backend config (state, native locking)
├── variables.tf                   aws_region, webhook_secret, github_token, LLM keys
├── lambda.tf                      Lambda function, IAM role, zipped from src/
├── dynamodb.tf                    Guardrails state table + scoped IAM policy
├── api.tf                         API Gateway v2 HTTP API, route, integration
├── outputs.tf                     webhook_url output
└── .gitignore
```

## Prerequisites

- AWS account and credentials with permission to create Lambda, API Gateway, and IAM
  resources
- An S3 bucket for Terraform remote state, created and versioned manually before the
  first `terraform init` (Terraform can't create the bucket it stores its own state
  in). State locking uses S3's native lockfile (`use_lockfile = true` in `main.tf`), so
  no DynamoDB table is needed for Terraform's own state; the bucket name is hardcoded
  in `main.tf`, update it there if you're using your own bucket. (Unrelated: the bot
  has its own DynamoDB table for guardrail state, `pr-review-bot-state` in
  `dynamodb.tf` - Terraform creates that one itself, nothing to set up by hand.)
- A GitHub PAT with `Pull requests: read and write` scoped to the test repo you'll use
  (this becomes `GITHUB_TOKEN` / the `BOT_GITHUB_TOKEN` secret)
- A webhook secret you generate yourself, e.g. `openssl rand -hex 32`
- An API key for **one** LLM provider: an Anthropic API key, or an OpenRouter API key
  (openrouter.ai) if you want a cheaper open-weight model instead. Neither is required
  for the bot to work; without one it just skips the summary section.
- Terraform >= 1.5.0 installed locally if you want to plan/apply by hand
  (`brew install terraform` on macOS)

## Deploying

### Locally

```
terraform init
terraform validate
terraform plan  -var="webhook_secret=<your secret>" -var="github_token=<your PAT>" \
  -var="anthropic_api_key=<your key>"    # or -var="openrouter_api_key=<your key>"
terraform apply -var="webhook_secret=<your secret>" -var="github_token=<your PAT>" \
  -var="anthropic_api_key=<your key>"    # or -var="openrouter_api_key=<your key>"
```

Note the `webhook_url` output at the end; that's the payload URL for the next step.

### Via GitHub Actions

Set these repository secrets:

- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
- `WEBHOOK_SECRET`
- `BOT_GITHUB_TOKEN`
- `ANTHROPIC_API_KEY` **or** `OPENROUTER_API_KEY` (only set one; leave the other repo
  secret unset). Optionally `ANTHROPIC_MODEL` / `OPENROUTER_MODEL` to override the
  default model for whichever provider you chose.

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
   Within a few seconds a comment should appear with a `## Summary` section (LLM
   review) followed by `## Static checks` (pass/warn per check).
2. To exercise each static check in isolation, open PRs designed to trip them
   individually: one that adds a line looking like a credential (e.g.
   `api_key = "sk_live_..."`), one that changes a source file with no corresponding
   test file change, and one with a diff over 500 changed lines. Confirm each posts
   the matching warning, and a small clean PR (source + matching test file) posts
   all-clear on every check.
3. Confirm the summary is accurate for PRs of varying size, and flags a case where the
   PR description doesn't match what the diff actually does.
4. Confirm the fallback path: temporarily set the configured provider's API key to
   something invalid in AWS (or unset it), open a PR, and confirm the comment still
   posts with the static checks intact and the summary section explaining it's
   unavailable, rather than the webhook failing outright.
5. In the repo's webhook settings, check the "Recent Deliveries" tab for a `200`
   response on that delivery.
6. To confirm the signature check actually works, temporarily change the webhook's
   secret in GitHub to something wrong (without touching `WEBHOOK_SECRET` in AWS), open
   another PR, and confirm: the delivery shows a `401`, CloudWatch Logs for the Lambda
   show `signature verification failed`, and no comment is posted. Then set the webhook
   secret back to the correct value.
7. Confirm the kill switch: `put-item` the `config#ai_reviews_enabled` flag to
   `false` (see above), open a PR, and confirm the comment posts with the static
   checks intact and the summary section says reviews are disabled. Set it back
   (`put-item` with `{"BOOL":true}` or just delete the item) afterward.
8. Confirm debounce: push two commits to the same open PR within
   `DEBOUNCE_WINDOW_SECONDS` (120s by default) of each other, and confirm the second
   `synchronize` event's comment shows the debounce note instead of a fresh summary.
9. Confirm the daily/per-repo caps if you want to exercise them: temporarily lower
   `DAILY_CALL_LIMIT` or `PER_REPO_HOURLY_LIMIT` in `src/guardrails.py` to something
   small, redeploy, trigger that many reviews, and confirm the next one is skipped
   with the matching note. Put the thresholds back afterward.
10. Check CloudWatch Logs for the `llm_review_call` line on a successful review -
    confirms cost visibility is working (repo, PR number, included/excluded file
    counts, approximate input tokens).

CloudWatch Logs group: `/aws/lambda/pr-review-bot`.

## Stage notes

- **Stage 1:** signature-verifying webhook receiver that posts an ack comment on
  `opened` / `reopened` / `synchronize` pull request events.
- **Stage 2:** fetches the PR's changed files and runs deterministic checks (secrets,
  missing tests, diff size), posting the results as a checklist comment.
- **Stage 3 (current):** adds an LLM-generated summary of the diff (provider picked
  automatically by which API key is configured), combined with the Stage 2 checklist
  into one comment. Degrades gracefully if the LLM call fails or isn't configured, and
  is gated by volume/abuse guardrails (kill switch, daily/per-repo/debounce limits) so
  the LLM step can't be run away with by a busy or hostile repo.
