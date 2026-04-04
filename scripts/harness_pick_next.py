#!/usr/bin/env python3
"""Select the next eligible harness feature without mutating state."""

from __future__ import annotations

import argparse
import json

from harness_lib import eligible_features, get_feature, load_state, project_root_arg


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".", help="Project root containing .harness/")
    parser.add_argument("--focus", help="Specific feature id to inspect")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = project_root_arg(args.project_root)
    campaign, features = load_state(project_root)
    selected = None
    reason = None
    if args.focus:
        feature = get_feature(features, args.focus)
        status = feature.get("status")
        if status == "blocked":
            raise SystemExit(f"{args.focus} is blocked. Resolve it with harness_transition.py before focusing it.")
        if status not in {"pending", "in_progress"}:
            raise SystemExit(f"{args.focus} is not selectable because it is {status}.")
        if status == "pending":
            done = {item["id"] for item in features if item.get("status") == "done"}
            missing = [dep for dep in feature.get("dependencies", []) if dep not in done]
            if missing:
                raise SystemExit(f"{args.focus} is still waiting on dependencies: {', '.join(missing)}")
        selected = feature
        reason = "explicit focus"
    elif campaign.get("current_feature"):
        selected = get_feature(features, campaign["current_feature"])
        reason = "current in-progress feature"
    else:
        candidates = eligible_features(features)
        if candidates:
            selected = candidates[0]
            reason = "highest-priority eligible pending feature"
    payload = {
        "selected": selected,
        "reason": reason,
        "remaining_candidates": eligible_features(features),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        if selected:
            print(f"{selected['id']} - {selected['name']} ({reason})")
        else:
            print("No eligible feature found.")
    return 0 if selected else 1


if __name__ == "__main__":
    raise SystemExit(main())
