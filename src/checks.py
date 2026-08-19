import re

SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key ID"),
    (re.compile(r"aws_secret_access_key\s*=\s*['\"][A-Za-z0-9/+=]{40}['\"]", re.I), "AWS secret access key"),
    (re.compile(r"(api[_-]?key|apikey)\s*[:=]\s*['\"][A-Za-z0-9\-_]{16,}['\"]", re.I), "API key"),
    (re.compile(r"password\s*[:=]\s*['\"][^'\"]{4,}['\"]", re.I), "hardcoded password"),
    (re.compile(r"-----BEGIN (RSA|EC|OPENSSH|PGP|DSA)? ?PRIVATE KEY-----"), "private key"),
]

TEST_DIR_RE = re.compile(r"(^|/)(tests?|spec)/", re.I)
TEST_FILE_RE = re.compile(r"(^|/)(test_[^/]+|[^/]+_test|[^/]+\.test|[^/]+\.spec|[^/]+_spec)\.[a-zA-Z]+$", re.I)
CONFIG_FILE_RE = re.compile(r"\.config\.(ts|js|mjs|cjs)$", re.I)
TYPE_DECL_RE = re.compile(r"\.d\.ts$", re.I)
ENTRYPOINT_BASENAMES = {"main.ts", "main.tsx", "main.js", "main.jsx"}

SOURCE_EXTENSIONS = (".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".java", ".rb")
LARGE_DIFF_THRESHOLD = 500


def _is_test_file(filename: str) -> bool:
    return bool(TEST_DIR_RE.search(filename) or TEST_FILE_RE.search(filename))


def _is_source_file(filename: str) -> bool:
    lower = filename.lower()
    return lower.endswith(SOURCE_EXTENSIONS) and not _is_test_file(lower)


def _requires_test(filename: str) -> bool:
    """Excludes build config, type declarations, and bare app entrypoints."""
    if not _is_source_file(filename):
        return False
    lower = filename.lower()
    if CONFIG_FILE_RE.search(lower) or TYPE_DECL_RE.search(lower):
        return False
    return lower.rsplit("/", 1)[-1] not in ENTRYPOINT_BASENAMES


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
    """PR-level: passes if any test file was touched anywhere in the PR."""
    source_touched = [f["filename"] for f in files if _requires_test(f["filename"])]
    test_touched = [f["filename"] for f in files if _is_test_file(f["filename"])]
    if not source_touched:
        return {"name": "Tests", "passed": True, "detail": "no source files changed"}
    if test_touched:
        detail = f"{len(test_touched)} test files updated alongside source changes"
        return {"name": "Tests", "passed": True, "detail": detail}
    detail = f"{len(source_touched)} source files changed, no test files touched"
    return {"name": "Tests", "passed": False, "detail": detail}


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


def format_checklist(results: list) -> str:
    lines = ["## Static checks"]
    for r in results:
        mark = "✅" if r["passed"] else "⚠️"
        lines.append(f"{mark} {r['name']}: {r['detail']}")
    return "\n".join(lines)
