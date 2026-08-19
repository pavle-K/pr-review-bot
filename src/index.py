import base64
import hashlib
import hmac
import json
import os

from github_client import post_comment

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

    comment_body = (
        "PR Review Bot: signature verified.\n\n"
        f"PR #{pr_number}: {pr_title}\n\n"
        "Static checks and LLM review land in later stages."
    )
    post_comment(repo_full_name, pr_number, comment_body)

    return {"statusCode": 200, "body": "ok"}
