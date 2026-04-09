#!/usr/bin/env python3
"""Apply an allowed state transition to a harness feature."""

from __future__ import annotations

import argparse
import json

from harness_lib import (
    TRANSITIONS,
    archive_contract,
    build_session_summary,
    get_feature,
    infer_git_commit,
    load_contract,
    load_session_summary,
    load_state,
    project_root_arg,
    remove_contract,
    require_harness,
    save_state,
    utc_now,
    write_session_summary,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".", help="Project root containing .harness/")
    parser.add_argument("--feature-id", help="Feature id to transition; defaults to campaign.current_feature")
    parser.add_argument("--to", required=True, help="Target status")
    parser.add_argument("--session-note", action="append", default=[], help="Session note to append to feature.sessions")
    parser.add_argument("--blocked-reason", help="Required when transitioning to blocked")
    parser.add_argument("--last-session-date", help="Optional YYYY-MM-DD override")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = project_root_arg(args.project_root)
    require_harness(project_root)
    campaign, features = load_state(project_root)
    feature_id = args.feature_id or campaign.get("current_feature")
    if not feature_id:
        raise SystemExit("No feature id supplied and campaign.current_feature is empty.")
    feature = get_feature(features, feature_id)
    current_status = feature.get("status")
    target_status = args.to
    if target_status not in TRANSITIONS.get(current_status, set()):
        raise SystemExit(f"Invalid transition: {current_status} -> {target_status}")
    active_feature_id = campaign.get("current_feature")
    if current_status == "blocked" and target_status != "pending":
        raise SystemExit("Blocked features may only transition back to pending.")
    if target_status == "in_progress":
        if current_status != "pending":
            raise SystemExit(f"Only pending features may transition to in_progress, not {current_status}.")
        if active_feature_id and active_feature_id != feature_id:
            raise SystemExit(
                f"Cannot start {feature_id} because {active_feature_id} is already in progress. "
                "Transition the active feature out of in_progress first."
            )
    if target_status == "blocked" and not args.blocked_reason:
        raise SystemExit("--blocked-reason is required when transitioning to blocked")
    head_commit = infer_git_commit(project_root)
    for note in args.session_note:
        if note.strip():
            feature.setdefault("sessions", []).append(
                {"note": note.strip(), "timestamp": utc_now()}
            )
    feature["sessions"] = feature.get("sessions", [])[-20:]
    feature["status"] = target_status
    if target_status == "blocked":
        feature["blocked_reason"] = args.blocked_reason.strip()
        feature.setdefault("blocked_history", []).append(
            {"reason": args.blocked_reason.strip(), "timestamp": utc_now()}
        )
        feature["blocked_history"] = feature["blocked_history"][-10:]
    else:
        feature["blocked_reason"] = None
    if target_status == "in_progress":
        campaign["current_feature"] = feature_id
        campaign["current_feature_started"] = utc_now()
        campaign["session_count"] = campaign.get("session_count", 0) + 1
        if feature.get("checkpoint") is None:
            feature["checkpoint"] = {
                "completed_steps": [],
                "next_step": f"Implement {feature_id} and refresh this checkpoint before handing off.",
                "open_issues": [],
                "files_touched": [],
                "tests_run": [],
                "last_updated": utc_now(),
                "last_verified_commit": head_commit,
                "selftest_retries": 0,
                "checkpoint_writes": 0,
            }
    else:
        if campaign.get("current_feature") == feature_id:
            campaign["current_feature"] = None
            campaign["current_feature_started"] = None
        if target_status in {"done", "blocked", "skipped"}:
            feature["checkpoint"] = None
            if target_status == "done":
                archive_contract(project_root, feature)
            else:
                remove_contract(project_root)
    if target_status == "done":
        feature["blocked_reason"] = None
    campaign["last_session_date"] = args.last_session_date or utc_now().split("T", 1)[0]
    campaign["last_session_commit"] = head_commit
    existing_summary = load_session_summary(project_root, required=False)
    contract = load_contract(project_root, required=False)
    summary = build_session_summary(campaign, features, contract, existing_summary)
    save_state(project_root, campaign, features)
    write_session_summary(project_root, summary)
    payload = {
        "feature_id": feature_id,
        "from": current_status,
        "to": target_status,
        "campaign_current_feature": campaign.get("current_feature"),
        "summary": summary,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"{feature_id}: {current_status} -> {target_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
