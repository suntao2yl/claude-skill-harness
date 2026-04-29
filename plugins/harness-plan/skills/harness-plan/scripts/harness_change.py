#!/usr/bin/env python3
"""Change-unit (CHG-NNN) state machine for harness-plan campaigns.

Phase 4 addition. Each feature in standard/deep mode can be subdivided into
change units, each with its own propose -> spec -> verify -> archive lifecycle.
This enables reviewable, finer-grained work tracking inside large features
without breaking flat-feature compatibility.

State machine:
  proposed --to-spec--> speccing --to-verify--> verifying --archive--> archived
     |                     |                      |
     +-cancel->archived  +-cancel->archived    +-reopen->speccing

The feature is `done` only when all its change_units are `archived`.

Files written:
  .harness/changes/CHG-NNN/proposal.md  (on propose)
  .harness/changes/CHG-NNN/spec.md      (on to-spec, via /change-spec)
  .harness/changes/CHG-NNN/verify.json  (on to-verify, via /completion-verify)
  .harness/changes/CHG-NNN/archive.md   (on archive)

The truth-of-state lives in features.json under the parent feature's
`change_units[]` array. This script never reads/writes the markdown files
beyond proposal.md and archive.md (paths in spec.md / verify.json are
populated by the caller / sibling skills).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add scripts dir to path so we can reuse harness_lib
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from harness_lib import (  # type: ignore  # noqa: E402
    ensure_harness_dir,
    harness_dir,
    load_state,
    project_root_arg,
    require_harness,
    save_state,
    utc_now,
)

# Allowed transitions
ALLOWED_TRANSITIONS = {
    ("proposed",  "speccing"),
    ("proposed",  "archived"),  # cancel
    ("speccing",  "verifying"),
    ("speccing",  "archived"),  # cancel
    ("verifying", "archived"),  # success path
    ("verifying", "speccing"),  # reopen on review
}

VALID_STATES = {"proposed", "speccing", "verifying", "archived"}
CHG_PATTERN = re.compile(r"^CHG-\d{3,}$")


def changes_dir(project_root: Path) -> Path:
    return harness_dir(project_root) / "changes"


def next_chg_id(project_root: Path) -> str:
    """Return the next unused CHG-NNN id by scanning .harness/changes/.

    Reuses skipped numbers: a deleted CHG-002 is NOT re-issued (per the ID
    convention's "no skipping" rule). We track max-seen and increment.
    """
    cd = changes_dir(project_root)
    if not cd.exists():
        return "CHG-001"
    nums = []
    for child in cd.iterdir():
        m = CHG_PATTERN.match(child.name)
        if m:
            nums.append(int(child.name.split("-")[1]))
    n = (max(nums) + 1) if nums else 1
    return f"CHG-{n:03d}"


def find_feature(features: list, feature_id: str) -> dict | None:
    for f in features:
        if f.get("id") == feature_id:
            return f
    return None


def find_change_unit(feature: dict, change_id: str) -> dict | None:
    for c in (feature.get("change_units") or []):
        if c.get("id") == change_id:
            return c
    return None


def find_owning_feature(features: list, change_id: str) -> dict | None:
    for f in features:
        for c in (f.get("change_units") or []):
            if c.get("id") == change_id:
                return f
    return None


def cmd_propose(args, project_root: Path) -> int:
    campaign, features = load_state(project_root)
    feature = find_feature(features, args.feature_id)
    if feature is None:
        print(json.dumps({"error": f"feature {args.feature_id} not found"}))
        return 2

    chg_id = next_chg_id(project_root)
    cd = changes_dir(project_root) / chg_id
    cd.mkdir(parents=True, exist_ok=True)
    proposal_path = cd / "proposal.md"
    proposal_path.write_text(
        f"# {chg_id}: {args.title}\n\n"
        f"_proposed: {utc_now()}_\n\n"
        f"_parent feature: {args.feature_id}_\n\n"
        f"## Why\n\n{args.reason or '(no rationale supplied)'}\n",
        encoding="utf-8",
    )

    feature.setdefault("change_units", []).append({
        "id": chg_id,
        "title": args.title,
        "state": "proposed",
        "proposed_at": utc_now(),
        "spec_path": None,
        "verification_evidence": None,
        "files_touched": [],
    })
    save_state(project_root, campaign, features)
    print(json.dumps({
        "id": chg_id,
        "feature_id": args.feature_id,
        "state": "proposed",
        "proposal_path": str(proposal_path.relative_to(project_root)),
    }, indent=2))
    return 0


def transition(args, project_root: Path, target_state: str) -> int:
    campaign, features = load_state(project_root)
    feature = find_owning_feature(features, args.change_id)
    if feature is None:
        print(json.dumps({"error": f"change_unit {args.change_id} not found"}))
        return 2
    cu = find_change_unit(feature, args.change_id)
    current = cu.get("state")
    if (current, target_state) not in ALLOWED_TRANSITIONS:
        print(json.dumps({
            "error": f"transition {current} -> {target_state} not allowed",
            "allowed_from_current": [t for f, t in ALLOWED_TRANSITIONS if f == current],
        }))
        return 2

    cu["state"] = target_state
    cu[f"{target_state}_at"] = utc_now()
    if target_state == "speccing" and args.spec_path:
        cu["spec_path"] = args.spec_path
    if target_state == "verifying" and args.verify_evidence:
        cu["verification_evidence"] = args.verify_evidence
    if args.files_touched:
        # files_touched accumulates across transitions
        existing = set(cu.get("files_touched") or [])
        existing.update(args.files_touched)
        cu["files_touched"] = sorted(existing)

    save_state(project_root, campaign, features)

    # On archive, write a small archive note for human-readable trail
    if target_state == "archived":
        archive_path = changes_dir(project_root) / cu["id"] / "archive.md"
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_text(
            f"# {cu['id']} archived\n\n"
            f"_archived: {cu['archived_at']}_\n\n"
            f"_parent feature: {feature.get('id')}_\n\n"
            f"## Title\n\n{cu.get('title', '')}\n\n"
            f"## Files touched\n\n"
            + ("".join(f"- `{f}`\n" for f in (cu.get("files_touched") or [])) or "_(none)_\n")
            + "\n",
            encoding="utf-8",
        )

    print(json.dumps({
        "id": cu["id"],
        "feature_id": feature.get("id"),
        "from": current,
        "to": target_state,
    }, indent=2))
    return 0


def cmd_status(args, project_root: Path) -> int:
    campaign, features = load_state(project_root)
    if args.feature_id:
        feature = find_feature(features, args.feature_id)
        if feature is None:
            print(json.dumps({"error": f"feature {args.feature_id} not found"}))
            return 2
        units = feature.get("change_units") or []
        print(json.dumps({
            "feature_id": args.feature_id,
            "change_units": [
                {"id": c["id"], "state": c["state"], "title": c.get("title")}
                for c in units
            ],
            "summary": _summarize(units),
        }, indent=2))
        return 0
    # No feature filter: cross-feature summary
    out = []
    for f in features:
        units = f.get("change_units") or []
        if not units:
            continue
        out.append({
            "feature_id": f.get("id"),
            "summary": _summarize(units),
        })
    print(json.dumps({"features": out}, indent=2))
    return 0


def _summarize(units: list) -> dict:
    counts = {s: 0 for s in VALID_STATES}
    for u in units:
        s = u.get("state", "unknown")
        if s in counts:
            counts[s] += 1
    counts["total"] = len(units)
    return counts


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root", default=".")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("propose", help="Create a new CHG-NNN under a feature.")
    sp.add_argument("--feature-id", required=True)
    sp.add_argument("--title", required=True, help="Imperative, <= 60 chars.")
    sp.add_argument("--reason", help="Optional rationale paragraph.")

    for state, name in [
        ("speccing",  "to-spec"),
        ("verifying", "to-verify"),
        ("archived",  "archive"),
        ("speccing",  "reopen"),  # verifying -> speccing
    ]:
        sx = sub.add_parser(name, help=f"Transition CHG to {state}")
        sx.add_argument("--change-id", required=True)
        sx.add_argument("--spec-path", help="Used by to-spec to record /change-spec output path.")
        sx.add_argument("--verify-evidence", help="Used by to-verify to record /completion-verify result path.")
        sx.add_argument("--files-touched", nargs="*", help="Append to files_touched.")
        sx.set_defaults(_target=state)

    sx = sub.add_parser("cancel", help="Cancel a CHG (transition to archived from proposed/speccing).")
    sx.add_argument("--change-id", required=True)
    sx.set_defaults(_target="archived")

    ss = sub.add_parser("status", help="Print change-unit status.")
    ss.add_argument("--feature-id", help="If given, list units of that feature; else summary across all.")

    return p.parse_args()


def main() -> int:
    args = parse_args()
    root = project_root_arg(args.project_root)
    require_harness(root)
    ensure_harness_dir(root)

    if args.cmd == "propose":
        return cmd_propose(args, root)
    if args.cmd == "status":
        return cmd_status(args, root)
    target = getattr(args, "_target", None)
    if target is None:
        print(json.dumps({"error": f"unknown command {args.cmd}"}))
        return 2
    if not hasattr(args, "spec_path"):
        args.spec_path = None
    if not hasattr(args, "verify_evidence"):
        args.verify_evidence = None
    if not hasattr(args, "files_touched"):
        args.files_touched = []
    return transition(args, root, target)


if __name__ == "__main__":
    raise SystemExit(main())
