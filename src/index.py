import base64
import hashlib
import hmac
import json
import os

from checks import format_checklist, run_checks
from github_client import get_pr_files, post_comment
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

    files = get_pr_files(repo_full_name, pr_number)
    results = run_checks(files)
    summary = review_diff(files, pr_title, pr.get("body") or "")

    lines = [f"PR Review Bot: review for #{pr_number} ({pr_title})", "", "## Summary"]
    lines.append(summary or "_LLM summary unavailable (no provider configured, or the request failed)._")
    lines.append("")
    lines.append(format_checklist(results))
    post_comment(repo_full_name, pr_number, "\n".join(lines))

    return {"statusCode": 200, "body": "ok"}
