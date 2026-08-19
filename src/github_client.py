import json
import os
import urllib.request

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_API = "https://api.github.com"


def _headers(extra=None):
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "pr-review-bot",
    }
    if extra:
        headers.update(extra)
    return headers


def post_comment(repo_full_name: str, pr_number: int, body: str) -> None:
    url = f"{GITHUB_API}/repos/{repo_full_name}/issues/{pr_number}/comments"
    data = json.dumps({"body": body}).encode()
    req = urllib.request.Request(
        url, data=data, method="POST", headers=_headers({"Content-Type": "application/json"})
    )
    with urllib.request.urlopen(req) as resp:
        resp.read()


def get_pr_files(repo_full_name: str, pr_number: int) -> list:
    files = []
    page = 1
    while True:
        url = f"{GITHUB_API}/repos/{repo_full_name}/pulls/{pr_number}/files?per_page=100&page={page}"
        req = urllib.request.Request(url, headers=_headers())
        with urllib.request.urlopen(req) as resp:
            batch = json.loads(resp.read())
        files.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return files
