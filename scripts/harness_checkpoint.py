#!/usr/bin/env python3
"""Write a structured checkpoint for the active harness feature."""

from __future__ import annotations

import argparse
import json

from harness_lib import (
    build_session_summary,
    dedupe,
    get_feature,
    infer_git_changed_files,
    infer_git_commit,
    load_contract,
    load_session_summary,
    load_state,
    project_root_arg,
    save_state,
    utc_now,
    write_session_summary,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".", help="Project root containing .harness/")
    parser.add_argument("--feature-id", help="Feature id to checkpoint; defaults to campaign.current_feature")
    parser.add_argument("--completed-step", action="append", default=[], help="Completed step entry")
    parser.add_argument("--next-step", required=True, help="Single next step to resume from")
    parser.add_argument("--open-issue", action="append", default=[], help="Open issue entry")
    parser.add_argument("--file-touched", action="append", default=[], help="File touched entry")
    parser.add_argument("--test-run", action="append", default=[], help="Executed test or verification command")
    parser.add_argument("--last-verified-commit", help="Commit hash associated with this checkpoint")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = project_root_arg(args.project_root)
    campaign, features = load_state(project_root)
    feature_id = args.feature_id or campaign.get("current_feature")
    if not feature_id:
        raise SystemExit("No feature id supplied and campaign.current_feature is empty.")
    active_feature_id = campaign.get("current_feature")
    if not active_feature_id:
        raise SystemExit("campaign.current_feature is empty. Only the active in_progress feature can be checkpointed.")
    if feature_id != active_feature_id:
        raise SystemExit(
            f"Cannot checkpoint {feature_id}. The active feature is {active_feature_id}."
        )
    feature = get_feature(features, feature_id)
    if feature.get("status") != "in_progress":
        raise SystemExit(
            f"Cannot checkpoint {feature_id} because its status is {feature.get('status')}."
        )
    files_touched = args.file_touched
    if not files_touched:
        existing_checkpoint = feature.get("checkpoint") or {}
        since = existing_checkpoint.get("last_verified_commit")
        files_touched = infer_git_changed_files(project_root, since)
    feature["checkpoint"] = {
        "completed_steps": dedupe(args.completed_step),
        "next_step": args.next_step.strip(),
        "open_issues": dedupe(args.open_issue),
        "files_touched": files_touched,
        "tests_run": args.test_run,
        "last_updated": utc_now(),
        "last_verified_commit": args.last_verified_commit or infer_git_commit(project_root),
    }
    existing_summary = load_session_summary(project_root, required=False)
    contract = load_contract(project_root, required=False)
    campaign["last_session_commit"] = feature["checkpoint"]["last_verified_commit"]
    summary = build_session_summary(
        campaign,
        features,
        contract,
        existing_summary,
        resume_steps=[feature["checkpoint"]["next_step"]],
    )
    save_state(project_root, campaign, features)
    write_session_summary(project_root, summary)
    payload = {"feature_id": feature_id, "checkpoint": feature["checkpoint"], "summary": summary}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Checkpoint updated for {feature_id}. Next: {feature['checkpoint']['next_step']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
