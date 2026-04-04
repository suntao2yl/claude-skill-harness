#!/usr/bin/env python3
"""Create or refresh the active feature contract for harness v2."""

from __future__ import annotations

import argparse
import json

from harness_lib import (
    VALID_REVIEW_POLICIES,
    build_contract,
    build_session_summary,
    load_session_summary,
    load_state,
    project_root_arg,
    require_active_feature,
    save_state,
    write_contract,
    write_session_summary,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".", help="Project root containing .harness/")
    parser.add_argument("--feature-id", help="Feature id to contract; defaults to campaign.current_feature")
    parser.add_argument("--review-policy", choices=sorted(VALID_REVIEW_POLICIES))
    parser.add_argument("--scope-in", action="append", default=[])
    parser.add_argument("--scope-out", action="append", default=[])
    parser.add_argument("--claim", action="append", default=[])
    parser.add_argument("--command", action="append", default=[])
    parser.add_argument("--manual-check", action="append", default=[])
    parser.add_argument("--checklist-item", action="append", default=[])
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = project_root_arg(args.project_root)
    campaign, features = load_state(project_root)
    feature_id, feature = require_active_feature(campaign, features, args.feature_id, verb="create a contract for")
    contract = build_contract(
        feature,
        campaign,
        review_policy=args.review_policy,
        scope_in=args.scope_in or None,
        scope_out=args.scope_out or None,
        claims=args.claim or None,
        commands=args.command or None,
        manual_checks=args.manual_check or None,
        checklist_items=args.checklist_item or None,
    )
    write_contract(project_root, contract)
    existing_summary = load_session_summary(project_root, required=False)
    summary = build_session_summary(campaign, features, contract, existing_summary)
    save_state(project_root, campaign, features)
    write_session_summary(project_root, summary)
    payload = {"contract": contract, "summary": summary}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Contract refreshed for {feature_id} with review policy {contract['review_policy']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
