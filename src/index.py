import base64
import hashlib
import hmac
import json
import os

from checks import format_checklist, run_checks
from github_client import get_pr_files, post_comment
from guardrails import DISABLED_MESSAGE, claim_review_slot, reviews_enabled
from reviewer import review_diff

WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]
RELEVANT_ACTIONS = {"opened", "reopened", "synchronize"}


def _verify_signature(body: bytes, signature: str) -> bool:
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def handler(event, context):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    raw_body = event.get("body") or ""
    body_bytes = base64.b64decode(raw_body) if event.get("isBase64Encoded") else raw_body.encode()

    signature = headers.get("x-hub-signature-256", "")
    if not _verify_signature(body_bytes, signature):
        return {"statusCode": 401, "body": "signature verification failed"}

    if headers.get("x-github-event") != "pull_request":
        return {"statusCode": 200, "body": "ignored"}

    payload = json.loads(body_bytes)
    if payload.get("action") not in RELEVANT_ACTIONS:
        return {"statusCode": 200, "body": "ignored"}

    pr = payload["pull_request"]
    repo_full_name = payload["repository"]["full_name"]
    pr_number = pr["number"]
    pr_title = pr["title"]
    commit_sha = pr["head"]["sha"]

    files = get_pr_files(repo_full_name, pr_number)
    results = run_checks(files)

    if not reviews_enabled():
        summary = f"## Summary\n_{DISABLED_MESSAGE}_"
    else:
        skip_reason = claim_review_slot(repo_full_name, pr_number, commit_sha)
        if skip_reason:
            summary = f"## Summary\n_{skip_reason}_"
        else:
            summary = review_diff(files, pr_title, pr.get("body") or "", repo_full_name, pr_number)

    lines = [f"PR Review Bot: review for #{pr_number} ({pr_title})", ""]
    lines.append(
        summary
        or "## Summary\n_LLM summary unavailable (no provider configured, or the request failed)._"
    )
    lines.append("")
    lines.append(format_checklist(results))
    post_comment(repo_full_name, pr_number, "\n".join(lines))

    return {"statusCode": 200, "body": "ok"}
