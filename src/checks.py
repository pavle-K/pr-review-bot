import re

SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key ID"),
    (re.compile(r"aws_secret_access_key\s*=\s*['\"][A-Za-z0-9/+=]{40}['\"]", re.I), "AWS secret access key"),
    (re.compile(r"(api[_-]?key|apikey)\s*[:=]\s*['\"][A-Za-z0-9\-_]{16,}['\"]", re.I), "API key"),
    (re.compile(r"password\s*[:=]\s*['\"][^'\"]{4,}['\"]", re.I), "hardcoded password"),
    (re.compile(r"-----BEGIN (RSA|EC|OPENSSH|PGP|DSA)? ?PRIVATE KEY-----"), "private key"),
]

TEST_PATH_HINTS = ("test_", "_test.", "/test/", "/tests/", "spec.", "_spec.")
SOURCE_EXTENSIONS = (".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".java", ".rb")
LARGE_DIFF_THRESHOLD = 500


def _is_test_file(filename: str) -> bool:
    lower = filename.lower()
    return any(hint in lower for hint in TEST_PATH_HINTS)


def _is_source_file(filename: str) -> bool:
    lower = filename.lower()
    return lower.endswith(SOURCE_EXTENSIONS) and not _is_test_file(lower)


def check_secrets(files: list) -> dict:
    findings = []
    for f in files:
        patch = f.get("patch")
        if not patch:
            continue
        for line in patch.splitlines():
            if not line.startswith("+") or line.startswith("+++"):
                continue
            for pattern, label in SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append(f"{f['filename']}: possible {label}")
                    break
    passed = not findings
    detail = "no likely secrets found in added lines" if passed else "; ".join(findings)
    return {"name": "Secrets", "passed": passed, "detail": detail}


def check_tests(files: list) -> dict:
    source_touched = [f["filename"] for f in files if _is_source_file(f["filename"])]
    test_touched = [f["filename"] for f in files if _is_test_file(f["filename"])]
    if not source_touched:
        return {"name": "Tests", "passed": True, "detail": "no source files changed"}
    passed = bool(test_touched)
    detail = (
        "test files updated alongside source changes"
        if passed
        else f"source changed with no corresponding test changes: {', '.join(source_touched)}"
    )
    return {"name": "Tests", "passed": passed, "detail": detail}


def check_diff_size(files: list) -> dict:
    total_changes = sum(f.get("changes", 0) for f in files)
    passed = total_changes <= LARGE_DIFF_THRESHOLD
    detail = (
        f"{total_changes} changed lines"
        if passed
        else f"{total_changes} changed lines, consider splitting this PR"
    )
    return {"name": "Diff size", "passed": passed, "detail": detail}


def run_checks(files: list) -> list:
    return [check_secrets(files), check_tests(files), check_diff_size(files)]


def format_comment(results: list, pr_number: int, pr_title: str) -> str:
    lines = [f"PR Review Bot: static checks for #{pr_number} ({pr_title})", ""]
    for r in results:
        mark = "✅" if r["passed"] else "⚠️"
        lines.append(f"{mark} {r['name']}: {r['detail']}")
    return "\n".join(lines)
