import json
import os
import urllib.request

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_API = "https://api.github.com"


def post_comment(repo_full_name: str, pr_number: int, body: str) -> None:
    url = f"{GITHUB_API}/repos/{repo_full_name}/issues/{pr_number}/comments"
    data = json.dumps({"body": body}).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "pr-review-bot",
        },
    )
    with urllib.request.urlopen(req) as resp:
        resp.read()
