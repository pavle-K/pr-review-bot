import json
import os
import re
import urllib.error
import urllib.request

# No tokenizer available (stdlib only) - a flat chars-per-token ratio is a rough but
# workable estimate for packing decisions; it doesn't need to be exact, just consistent.
CHARS_PER_TOKEN = 4
TOKEN_BUDGET = 15000
MAX_OUTPUT_TOKENS = 900
REQUEST_TIMEOUT = 15

ANTHROPIC_MODEL_DEFAULT = "claude-haiku-4-5"
OPENROUTER_MODEL_DEFAULT = "deepseek/deepseek-chat"

AUTH_MESSAGE = "AI review unavailable: API key not configured."
BILLING_MESSAGE = "AI review unavailable: account balance/quota issue. Static checks below are still valid."
# Best-effort: providers don't all use the same status code for a billing/quota
# problem (OpenRouter documents 402; Anthropic has historically used 400 with a
# message about credit balance), so 400 responses are also keyword-sniffed rather
# than assumed to be a plain bad request.
BILLING_KEYWORDS = ("credit balance", "insufficient", "billing", "quota", "payment")


class ReviewUnavailable(Exception):
    """A classified AI-review failure. `message` is the exact, PR-comment-safe text
    to show - never raw error/exception text. `log_detail` is for CloudWatch only."""

    def __init__(self, message: str, log_detail: str = ""):
        self.message = message
        self.log_detail = log_detail
        super().__init__(message)

LOCKFILE_NAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Gemfile.lock",
    "composer.lock",
    "Cargo.lock",
}
NOISE_DIR_RE = re.compile(r"(^|/)(dist|build|node_modules|vendor)/", re.I)
MINIFIED_RE = re.compile(r"\.min\.(js|css)$", re.I)
BINARY_EXT_RE = re.compile(
    r"\.(png|jpe?g|gif|svg|ico|bmp|webp|pdf|woff2?|ttf|eot|otf"
    r"|mp4|mov|avi|zip|gz|tar|7z|jar|class|so|dylib|dll|exe|wasm)$",
    re.I,
)

RISK_KEYWORDS = (
    "auth", "session", "payment", "migration", "middleware",
    "security", "secret", ".env", "schema", "permission",
)
RISK_BONUS = 500

WHITESPACE_ONLY_RE = re.compile(r"^\s*$")
IMPORT_LINE_RE = re.compile(r"^\s*(import\s|from\s+\S+\s+import\s|require\()", re.I)

SYSTEM_PROMPT = (
    "You are reviewing a GitHub pull request diff. You may be shown only a "
    "relevance-ranked subset of the full diff, not every changed file - the request "
    "will tell you exactly which files are included (full diffs) and which were "
    "excluded for size (filenames only, no content). Never claim code is missing, "
    "absent, or unimplemented solely because a file wasn't shown to you; only comment "
    "on files you actually see, and note explicitly when a judgment can't be made "
    "because a relevant file was excluded.\n\n"
    "Respond using exactly these markdown sections, under 300 words total:\n"
    "## Summary\n<plain-English summary of what changed, in the files you were shown>\n"
    "## Risks & Edge Cases\n<risks or edge cases worth a human's attention>\n"
    "## Alignment with PR Description\n<whether the diff matches what the PR description claims>\n\n"
    "Include a ## Scope section only if the request lists excluded files; omit it "
    "entirely otherwise. When included, write exactly two lines:\n"
    "Reviewed the N highest-risk files (a short comma-separated description of what "
    "they are or do, based on the diffs you saw, a few words each).\n"
    "Not individually reviewed due to size: <count> <category>, <count> <category>, ...\n\n"
    "For that second line, group the excluded filenames into 2-4 categories based on "
    "what you actually observe in their paths and extensions in THIS diff - do not "
    "assume any particular language, framework, or project layout; it could be a JS "
    "frontend, a Python backend, a Rust CLI, mobile code, anything. If there are "
    "genuinely more than 4 natural categories, collapse the smallest into an \"other\" "
    "bucket. Report only a count per category, never individual filenames."
)


def _is_noise(filename: str) -> bool:
    basename = filename.rsplit("/", 1)[-1]
    if basename in LOCKFILE_NAMES:
        return True
    if NOISE_DIR_RE.search(filename):
        return True
    if MINIFIED_RE.search(filename):
        return True
    if BINARY_EXT_RE.search(filename):
        return True
    return False


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def _non_cosmetic_ratio(patch: str) -> float:
    changed = [
        line[1:]
        for line in patch.splitlines()
        if (line.startswith("+") or line.startswith("-")) and not line.startswith(("+++", "---"))
    ]
    if not changed:
        return 0.0
    cosmetic = sum(1 for line in changed if WHITESPACE_ONLY_RE.match(line) or IMPORT_LINE_RE.match(line))
    return 1 - (cosmetic / len(changed))


def _score_file(f: dict) -> float:
    lower = f["filename"].lower()
    risk = RISK_BONUS if any(k in lower for k in RISK_KEYWORDS) else 0
    churn = f.get("changes", 0)
    ratio = _non_cosmetic_ratio(f["patch"])
    return risk + churn * ratio


def _select_files(files: list):
    """Noise-filter, then greedily pack the highest-scoring files whole (never
    mid-file) into the token budget. Returns (included_files, excluded_filenames)."""
    reviewable = [f for f in files if not _is_noise(f["filename"])]
    scoreable = [f for f in reviewable if f.get("patch")]
    excluded = [f["filename"] for f in reviewable if not f.get("patch")]

    scored = sorted(scoreable, key=lambda f: (-_score_file(f), f["filename"]))

    included = []
    budget_left = TOKEN_BUDGET
    for f in scored:
        hunk_tokens = _estimate_tokens(f["patch"])
        if hunk_tokens <= budget_left:
            included.append(f)
            budget_left -= hunk_tokens
        else:
            excluded.append(f["filename"])
    return included, excluded


def _build_prompt(included: list, excluded: list, pr_title: str, pr_body: str) -> str:
    included_names = ", ".join(f["filename"] for f in included)
    total = len(included) + len(excluded)
    diff_text = "\n\n".join(f"--- {f['filename']} ---\n{f['patch']}" for f in included)

    excluded_block = ""
    if excluded:
        excluded_block = (
            f"\n\nThe following {len(excluded)} files were excluded from review for size "
            f"(filenames only, no diff content - use these only to write the Scope "
            f"section, never describe them as missing or unimplemented):\n"
            f"{', '.join(excluded)}"
        )

    return (
        f"PR title: {pr_title}\n"
        f"PR description: {pr_body or '(none)'}\n\n"
        f"You are shown {len(included)} of {total} changed files, selected by risk "
        f"and churn (full diffs below).\n"
        f"Files shown: {included_names}\n\n"
        f"Diff:\n{diff_text}"
        f"{excluded_block}"
    )


def _classify_http_error(e: urllib.error.HTTPError):
    """Returns a ReviewUnavailable for the failure modes we distinguish (auth, rate
    limit, billing), or None if the error doesn't match one - callers re-raise the
    original HTTPError as-is in that case, to be handled as an unexpected failure."""
    try:
        body = e.read().decode(errors="replace")
    except Exception:
        body = ""
    log_detail = f"http {e.code}: {body[:500]}"

    if e.code == 401:
        return ReviewUnavailable(AUTH_MESSAGE, log_detail)
    if e.code == 429:
        retry_after = e.headers.get("Retry-After") if e.headers else None
        message = (
            f"AI review skipped: rate limit reached. Will retry after {retry_after}s, or on next push."
            if retry_after
            else "AI review skipped: rate limit reached. Will retry on next push."
        )
        return ReviewUnavailable(message, log_detail)
    if e.code == 402 or (e.code == 400 and any(k in body.lower() for k in BILLING_KEYWORDS)):
        return ReviewUnavailable(BILLING_MESSAGE, log_detail)
    return None


def _post_json(url: str, body: bytes, headers: dict) -> dict:
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        classified = _classify_http_error(e)
        if classified:
            raise classified from e
        raise


def _call_anthropic(prompt: str) -> str:
    api_key = os.environ["ANTHROPIC_API_KEY"]
    model = os.environ.get("ANTHROPIC_MODEL", ANTHROPIC_MODEL_DEFAULT)
    body = json.dumps(
        {
            "model": model,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()
    payload = _post_json(
        "https://api.anthropic.com/v1/messages",
        body,
        {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    return "".join(block.get("text", "") for block in payload["content"])


def _call_openrouter(prompt: str) -> str:
    api_key = os.environ["OPENROUTER_API_KEY"]
    model = os.environ.get("OPENROUTER_MODEL", OPENROUTER_MODEL_DEFAULT)
    body = json.dumps(
        {
            "model": model,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }
    ).encode()
    payload = _post_json(
        "https://openrouter.ai/api/v1/chat/completions",
        body,
        {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        },
    )
    return payload["choices"][0]["message"]["content"]


def _select_provider():
    # First matching key wins; only one provider needs to be configured.
    if os.environ.get("ANTHROPIC_API_KEY"):
        return _call_anthropic
    if os.environ.get("OPENROUTER_API_KEY"):
        return _call_openrouter
    return None


def review_diff(files: list, pr_title: str, pr_body: str, repo_full_name: str, pr_number: int):
    """LLM review summary, or None if there's nothing reviewable in the diff at all
    (not an error - just nothing to say). Raises ReviewUnavailable for a classified
    failure (missing key, rate limit, billing) with a PR-comment-safe message; any
    other exception (timeout, malformed response, etc.) propagates as-is and is the
    caller's responsibility to turn into a generic "unexpected failure" message -
    this function never silently swallows a real failure into a fake result.
    repo_full_name/pr_number are only used for the cost-visibility log line, not sent
    to the provider."""
    included, excluded = _select_files(files)
    if not included:
        if excluded:
            return (
                "## Summary\nNo reviewable source changes in this diff "
                "(only lockfiles, build artifacts, or binaries changed)."
            )
        return None

    call = _select_provider()
    if call is None:
        raise ReviewUnavailable(AUTH_MESSAGE, "no ANTHROPIC_API_KEY or OPENROUTER_API_KEY configured")

    prompt = _build_prompt(included, excluded, pr_title, pr_body)
    print(
        f"llm_review_call repo={repo_full_name} pr={pr_number} "
        f"files_included={len(included)} files_excluded={len(excluded)} "
        f"approx_input_tokens={_estimate_tokens(prompt)}"
    )
    return call(prompt).strip()
