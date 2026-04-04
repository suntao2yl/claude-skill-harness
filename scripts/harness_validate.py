#!/usr/bin/env python3
"""Validate harness v2 machine state and report migration issues clearly."""

from __future__ import annotations

import argparse
import json

from harness_lib import (
    check_git_drift,
    load_contract,
    load_session_summary,
    load_state,
    project_root_arg,
    validate_campaign,
    validate_contract,
    validate_dependencies,
    validate_feature,
    validate_session_summary,
    validate_state_links,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".", help="Project root containing .harness/")
    parser.add_argument("--json", action="store_true", help="Print validation report as JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = project_root_arg(args.project_root)
    campaign, features = load_state(project_root)
    contract = load_contract(project_root, required=False)
    summary = load_session_summary(project_root, required=False)
    errors = []
    errors.extend(validate_campaign(campaign))
    for feature in features:
        errors.extend(validate_feature(feature))
    errors.extend(validate_dependencies(features))
    if contract is not None:
        errors.extend(validate_contract(contract, features))
    if summary is not None:
        errors.extend(validate_session_summary(summary, [feature["id"] for feature in features]))
    errors.extend(validate_state_links(campaign, features, contract, summary))
    warnings = []
    current_id = campaign.get("current_feature")
    if current_id:
        current_feature = next((f for f in features if f.get("id") == current_id), None)
        if current_feature:
            checkpoint = current_feature.get("checkpoint") or {}
            drift = check_git_drift(project_root, checkpoint.get("last_verified_commit"))
            if drift["drifted"]:
                changed = drift.get("changed_files", [])
                count = len(changed)
                last = (drift.get("last_verified") or "")[:8]
                head = (drift.get("current_head") or "")[:8]
                warnings.append(
                    f"Git drift detected: {count} file(s) changed between "
                    f"{last} and {head}. Re-verify before continuing."
                )
    report = {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "files_checked": [
            ".harness/campaign.json",
            ".harness/features.json",
            ".harness/current-contract.json",
            ".harness/session-summary.json",
        ],
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        if errors:
            print("Harness state is invalid:")
            for item in errors:
                print(f"- {item}")
        else:
            print("Harness state is valid.")
        if warnings:
            print("Warnings:")
            for item in warnings:
                print(f"  ! {item}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
