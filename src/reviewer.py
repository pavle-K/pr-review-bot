import json
import os
import urllib.request

MAX_DIFF_CHARS = 15000
MAX_OUTPUT_TOKENS = 700
REQUEST_TIMEOUT = 15

ANTHROPIC_MODEL_DEFAULT = "claude-haiku-4-5"
OPENROUTER_MODEL_DEFAULT = "deepseek/deepseek-chat"

SYSTEM_PROMPT = (
    "You are reviewing a GitHub pull request diff. In under 200 words, cover: "
    "(1) a plain-English summary of what changed, (2) any risks or edge cases worth "
    "a human's attention, (3) whether the diff matches what the PR description "
    "claims. Be specific to this diff; do not restate the file list."
)


def _diff_text(files: list) -> str:
    parts = []
    for f in files:
        patch = f.get("patch")
        if patch:
            parts.append(f"--- {f['filename']} ---\n{patch}")
        else:
            parts.append(f"--- {f['filename']} --- (no diff shown: binary or too large)")
    text = "\n\n".join(parts)
    if len(text) > MAX_DIFF_CHARS:
        text = text[:MAX_DIFF_CHARS] + "\n\n[diff truncated for length]"
    return text


def _build_prompt(files: list, pr_title: str, pr_body: str) -> str:
    return (
        f"PR title: {pr_title}\n"
        f"PR description: {pr_body or '(none)'}\n\n"
        f"Diff:\n{_diff_text(files)}"
    )


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
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        method="POST",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        payload = json.loads(resp.read())
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
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        payload = json.loads(resp.read())
    return payload["choices"][0]["message"]["content"]


def _select_provider():
    # First matching key wins; only one provider needs to be configured.
    if os.environ.get("ANTHROPIC_API_KEY"):
        return _call_anthropic
    if os.environ.get("OPENROUTER_API_KEY"):
        return _call_openrouter
    return None


def review_diff(files: list, pr_title: str, pr_body: str):
    """LLM review summary, or None if no provider is configured or the call fails.
    Callers must treat None as 'omit the summary section', never as fatal."""
    call = _select_provider()
    if call is None:
        return None
    prompt = _build_prompt(files, pr_title, pr_body)
    try:
        return call(prompt).strip()
    except (OSError, ValueError, KeyError, IndexError):
        return None
