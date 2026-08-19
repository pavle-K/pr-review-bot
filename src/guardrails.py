import os
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

# Volume/abuse guardrails for the LLM review step only - static checks always run
# regardless. Every threshold lives here so tuning never means hunting through logic;
# each is env-overridable (wired from Terraform vars) so tuning doesn't require a code
# change either, just a redeploy with a new value.
DAILY_CALL_LIMIT = int(os.environ.get("DAILY_CALL_LIMIT", "50"))
PER_REPO_HOURLY_LIMIT = int(os.environ.get("PER_REPO_HOURLY_LIMIT", "10"))
DEBOUNCE_WINDOW_SECONDS = int(os.environ.get("DEBOUNCE_WINDOW_SECONDS", "120"))

COUNTER_TTL_SECONDS = 2 * 24 * 3600
DEBOUNCE_TTL_SECONDS = 7 * 24 * 3600

TABLE_NAME = os.environ.get("GUARDRAILS_TABLE", "pr-review-bot-state")
KILL_SWITCH_PK = "config#ai_reviews_enabled"

DAILY_LIMIT_MESSAGE = "AI review skipped: daily limit reached, will resume tomorrow."
REPO_LIMIT_MESSAGE = "AI review skipped: this repo's hourly review limit reached, will resume next hour."
DEBOUNCE_MESSAGE = "AI review skipped: reviewed recently, will re-run on a later push if changes continue."
INFRA_FAILURE_MESSAGE = "AI review skipped: budget check unavailable, skipping this run."
DISABLED_MESSAGE = "AI review skipped: reviews are currently disabled."

_dynamodb = boto3.client("dynamodb")


def reviews_enabled() -> bool:
    """Kill switch, checked before anything else - including before the budget
    transaction, so a disabled bot never touches DynamoDB at all. Fails open (missing
    flag item = enabled) so a fresh deploy isn't silently disabled, and fails open on
    infra errors too, since a broken guardrail check must never block static checks
    from posting - it only ever gates the optional LLM step."""
    try:
        resp = _dynamodb.get_item(TableName=TABLE_NAME, Key={"pk": {"S": KILL_SWITCH_PK}})
    except ClientError:
        return True
    item = resp.get("Item")
    if not item:
        return True
    return item.get("enabled", {}).get("BOOL", True)


def claim_review_slot(repo_full_name: str, pr_number: int, commit_sha: str):
    """Atomically check AND reserve budget for one LLM call - daily global cap,
    per-repo hourly cap, and per-PR debounce - in a single DynamoDB transaction, so
    concurrent webhook deliveries can't race past a limit, and budget is only ever
    spent on calls that actually proceed. Returns None if the call may proceed
    (state is now claimed); returns a human-readable skip reason otherwise."""
    now = time.time()
    date_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    hour_key = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")

    daily_pk = f"daily#{date_key}"
    repo_hour_pk = f"repohour#{repo_full_name}#{hour_key}"
    pr_pk = f"pr#{repo_full_name}#{pr_number}"
    cutoff = now - DEBOUNCE_WINDOW_SECONDS

    # Order matters: this list's index lines up with `reasons` below to identify
    # which guardrail blocked the call from DynamoDB's CancellationReasons.
    try:
        _dynamodb.transact_write_items(
            TransactItems=[
                {
                    "Update": {
                        "TableName": TABLE_NAME,
                        "Key": {"pk": {"S": daily_pk}},
                        "UpdateExpression": "ADD #c :one SET #ttl = :ttl",
                        "ConditionExpression": "attribute_not_exists(pk) OR #c < :limit",
                        "ExpressionAttributeNames": {"#c": "count", "#ttl": "ttl"},
                        "ExpressionAttributeValues": {
                            ":one": {"N": "1"},
                            ":limit": {"N": str(DAILY_CALL_LIMIT)},
                            ":ttl": {"N": str(int(now + COUNTER_TTL_SECONDS))},
                        },
                    }
                },
                {
                    "Update": {
                        "TableName": TABLE_NAME,
                        "Key": {"pk": {"S": repo_hour_pk}},
                        "UpdateExpression": "ADD #c :one SET #ttl = :ttl",
                        "ConditionExpression": "attribute_not_exists(pk) OR #c < :limit",
                        "ExpressionAttributeNames": {"#c": "count", "#ttl": "ttl"},
                        "ExpressionAttributeValues": {
                            ":one": {"N": "1"},
                            ":limit": {"N": str(PER_REPO_HOURLY_LIMIT)},
                            ":ttl": {"N": str(int(now + COUNTER_TTL_SECONDS))},
                        },
                    }
                },
                {
                    "Update": {
                        "TableName": TABLE_NAME,
                        "Key": {"pk": {"S": pr_pk}},
                        "UpdateExpression": "SET last_sha = :sha, last_reviewed_at = :now, #ttl = :ttl",
                        "ConditionExpression": "attribute_not_exists(pk) OR last_reviewed_at < :cutoff",
                        "ExpressionAttributeNames": {"#ttl": "ttl"},
                        "ExpressionAttributeValues": {
                            ":sha": {"S": commit_sha},
                            ":now": {"N": str(now)},
                            ":cutoff": {"N": str(cutoff)},
                            ":ttl": {"N": str(int(now + DEBOUNCE_TTL_SECONDS))},
                        },
                    }
                },
            ]
        )
        return None
    except ClientError as e:
        if e.response["Error"]["Code"] != "TransactionCanceledException":
            return INFRA_FAILURE_MESSAGE
        reasons = e.response.get("CancellationReasons", [])
        labels = [DAILY_LIMIT_MESSAGE, REPO_LIMIT_MESSAGE, DEBOUNCE_MESSAGE]
        for reason, label in zip(reasons, labels):
            if reason.get("Code") == "ConditionalCheckFailed":
                return label
        return INFRA_FAILURE_MESSAGE
