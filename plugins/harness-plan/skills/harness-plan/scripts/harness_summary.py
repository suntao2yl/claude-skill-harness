#!/usr/bin/env python3
"""Print and refresh a compact harness session summary."""

from __future__ import annotations

import argparse
import json

from harness_lib import (
    ENVIRONMENT_STATUSES,
    build_session_summary,
    format_summary_lines,
    load_contract,
    load_session_summary,
    load_state,
    project_root_arg,
    require_harness,
    write_session_summary,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", help="Project root containing .harness/", default=".")
    parser.add_argument("--environment-status", choices=sorted(ENVIRONMENT_STATUSES))
    parser.add_argument("--resume-step", action="append", default=[], help="Override or prepend resume step")
    parser.add_argument("--known-failure", action="append", default=[], help="Add known failure entry")
    parser.add_argument("--handoff-reason", choices=["freshness", "blocked", "completed", "interrupted"],
                        help="Why the session is ending")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = project_root_arg(args.project_root)
    require_harness(project_root)
    campaign, features = load_state(project_root)
    contract = load_contract(project_root, required=False)
    existing_summary = load_session_summary(project_root, required=False)
    resume_steps = args.resume_step or None
    known_failures = None
    if args.known_failure:
        known_failures = list((existing_summary or {}).get("known_failures", [])) + args.known_failure
    summary = build_session_summary(
        campaign,
        features,
        contract,
        existing_summary,
        environment_status=args.environment_status,
        resume_steps=resume_steps,
        known_failures=known_failures,
        handoff_reason=args.handoff_reason,
    )
    review_policy = (contract or {}).get("review_policy", campaign.get("default_review_policy", "selftest"))
    write_session_summary(project_root, summary)
    if args.json:
        print(json.dumps({"summary": summary, "review_policy": review_policy, "counts": summary["progress_counts"]}, indent=2))
    else:
        print("\n".join(format_summary_lines(summary, review_policy)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
