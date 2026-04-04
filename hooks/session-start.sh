#!/usr/bin/env bash
# Harness v2 SessionStart hook.
# Injects a compact summary from .harness/session-summary.json and .harness/current-contract.json.

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-.}"
CAMPAIGN_FILE="${PROJECT_DIR}/.harness/campaign.json"
SUMMARY_FILE="${PROJECT_DIR}/.harness/session-summary.json"
CONTRACT_FILE="${PROJECT_DIR}/.harness/current-contract.json"

if [ ! -f "$CAMPAIGN_FILE" ]; then
  exit 0
fi

python3 - "$CAMPAIGN_FILE" "$SUMMARY_FILE" "$CONTRACT_FILE" <<'PY'
import json
import sys
from pathlib import Path

campaign_path = Path(sys.argv[1])
summary_path = Path(sys.argv[2])
contract_path = Path(sys.argv[3])

def load_json(path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

campaign = load_json(campaign_path)
if not campaign or not campaign.get("goal"):
    raise SystemExit(0)

summary = load_json(summary_path) or {}
contract = load_json(contract_path) or {}
counts = summary.get("progress_counts") or {}
review_policy = contract.get("review_policy") or campaign.get("default_review_policy", "selftest")
resume_steps = summary.get("resume_steps") or []
next_step = resume_steps[0] if resume_steps else "Run python3 scripts/harness_summary.py for the latest resume step."
known_failures = summary.get("known_failures") or []
env_status = summary.get("environment_status") or campaign.get("baseline_status", "unknown")

lines = [
    "[harness] Active campaign detected.",
    f"Goal: {summary.get('campaign_goal') or campaign.get('goal', '')}",
    (
        "Progress: "
        f"{counts.get('completed', campaign.get('completed_features', 0))}/"
        f"{counts.get('total', campaign.get('total_features', 0))} done"
    ),
    f"Current feature: {summary.get('current_feature') or campaign.get('current_feature') or 'none'}",
    f"Review policy: {review_policy}",
    f"Environment: {env_status}",
    f"Last session: {summary.get('last_session_date') or campaign.get('last_session_date') or 'unknown'}",
    f"Next: {next_step}",
]

if env_status == "failing":
    lines.append("WARNING: Baseline environment is FAILING. Run bootstrap/setup before continuing.")

if known_failures:
    lines.append("Known failures:")
    for failure in known_failures[:5]:
        lines.append(f"  - {failure}")

# Inject open_issues from current feature checkpoint if available
features_path = campaign_path.parent / "features.json"
current_id = summary.get("current_feature") or campaign.get("current_feature")
if current_id:
    features_data = load_json(features_path)
    if features_data and isinstance(features_data, dict):
        for f in features_data.get("features", []):
            if f.get("id") == current_id:
                cp = f.get("checkpoint") or {}
                open_issues = cp.get("open_issues") or []
                if open_issues:
                    lines.append("Open issues from last checkpoint:")
                    for issue in open_issues[:5]:
                        lines.append(f"  - {issue}")
                break

context = "\n".join(lines)

print(json.dumps({"additionalContext": context}))
PY
