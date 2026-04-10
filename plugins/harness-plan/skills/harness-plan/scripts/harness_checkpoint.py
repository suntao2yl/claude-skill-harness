#!/usr/bin/env python3
"""Write a structured checkpoint for the active harness feature."""

from __future__ import annotations

import argparse
import json

from harness_lib import (
    build_session_summary,
    dedupe,
    detect_scope_drift,
    infer_git_changed_files,
    infer_git_commit,
    load_contract,
    load_session_summary,
    load_state,
    project_root_arg,
    require_active_feature,
    require_harness,
    run_quick_verify,
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
    parser.add_argument("--selftest-retry", action="store_true", help="Increment selftest retry counter")
    parser.add_argument("--failure-command", help="Command that failed during selftest")
    parser.add_argument("--failure-summary", help="Short description of the selftest failure")
    parser.add_argument("--quick-verify", action="store_true",
                        help="Run campaign test_command before writing checkpoint")
    parser.add_argument("--manual-check-done", action="append", default=[],
                        help="Record a completed manual check")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = project_root_arg(args.project_root)
    require_harness(project_root)
    campaign, features = load_state(project_root)
    feature_id, feature = require_active_feature(campaign, features, args.feature_id, verb="checkpoint")
    existing_checkpoint = feature.get("checkpoint") or {}
    files_touched = args.file_touched
    if not files_touched:
        since = existing_checkpoint.get("last_verified_commit")
        files_touched = infer_git_changed_files(project_root, since)
    selftest_retries = int(existing_checkpoint.get("selftest_retries") or 0)
    if args.selftest_retry:
        selftest_retries += 1
    checkpoint_writes = int(existing_checkpoint.get("checkpoint_writes") or 0) + 1
    last_failure = existing_checkpoint.get("last_failure")
    if args.selftest_retry and (args.failure_command or args.failure_summary):
        last_failure = {
            "command": args.failure_command or "",
            "error_summary": args.failure_summary or "",
            "affected_files": files_touched,
            "timestamp": utc_now(),
        }
    elif not args.selftest_retry and selftest_retries == 0:
        last_failure = None
    scope_drift_warnings = []
    contract = load_contract(project_root, required=False)
    if contract and files_touched:
        scope_drift_warnings = detect_scope_drift(contract, files_touched)
    # Incremental back-pressure: quick verify before checkpoint
    verification_runs = int(existing_checkpoint.get("verification_runs") or 0)
    if args.quick_verify:
        verification_runs += 1
        quick_verify_passed = run_quick_verify(campaign, project_root)
        if quick_verify_passed is False:
            print("  ! Quick verify FAILED")
    # Manual check tracking
    manual_checks_completed = dedupe(
        list(existing_checkpoint.get("manual_checks_completed", [])) + args.manual_check_done
    )
    feature["checkpoint"] = {
        "completed_steps": dedupe(args.completed_step),
        "next_step": args.next_step.strip(),
        "open_issues": dedupe(args.open_issue),
        "files_touched": files_touched,
        "tests_run": args.test_run,
        "last_updated": utc_now(),
        "last_verified_commit": args.last_verified_commit or infer_git_commit(project_root),
        "selftest_retries": selftest_retries,
        "checkpoint_writes": checkpoint_writes,
        "last_failure": last_failure,
        "scope_drift_warnings": scope_drift_warnings,
        "verification_runs": verification_runs,
        "manual_checks_completed": manual_checks_completed,
    }
    existing_summary = load_session_summary(project_root, required=False)
    campaign["last_session_commit"] = feature["checkpoint"]["last_verified_commit"]
    summary = build_session_summary(
        campaign,
        features,
        contract,
        existing_summary,
        resume_steps=[feature["checkpoint"]["next_step"]],
    )
    summary["session_step_count"] = summary.get("session_step_count", 0) + 1
    save_state(project_root, campaign, features)
    write_session_summary(project_root, summary)
    payload = {"feature_id": feature_id, "checkpoint": feature["checkpoint"], "summary": summary}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Checkpoint updated for {feature_id}. Next: {feature['checkpoint']['next_step']}")
        if scope_drift_warnings:
            for w in scope_drift_warnings:
                print(f"  ! Scope drift: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
