#!/usr/bin/env python3
"""Archive the current campaign and reset .harness/ for a fresh INIT."""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path

from harness_lib import load_state, project_root_arg


PRESERVE_FILES = {"archive"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=".", help="Project root containing .harness/")
    parser.add_argument("--label", default=None, help="Optional label for the archive folder (e.g. 'phase-1')")
    parser.add_argument("--force", action="store_true", help="Skip confirmation prompt")
    return parser.parse_args()


def build_archive_name(campaign: dict, label: str | None) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    goal_slug = (campaign.get("goal") or "campaign")[:40]
    slug = goal_slug.strip().lower()
    slug = "".join(c if c.isalnum() or c in "-_ " else "" for c in slug)
    slug = slug.strip().replace(" ", "-")
    if label:
        label = label.strip().replace(" ", "-")
        return f"{ts}_{label}"
    return f"{ts}_{slug}" if slug else ts


def main() -> int:
    args = parse_args()
    project_root = project_root_arg(args.project_root)
    harness_dir = project_root / ".harness"

    if not harness_dir.exists():
        print("No .harness/ directory found. Nothing to archive.")
        return 0

    campaign, features = load_state(project_root)
    archive_name = build_archive_name(campaign, args.label)
    archive_dir = harness_dir / "archive" / archive_name

    in_progress = [f for f in features if f.get("status") == "in_progress"]
    done_count = sum(1 for f in features if f.get("status") == "done")
    total = len(features)

    print(f"Campaign: {campaign.get('goal', '(no goal)')}")
    print(f"Progress: {done_count}/{total} done, {len(in_progress)} in_progress")
    print(f"Archive to: .harness/archive/{archive_name}/")

    if in_progress and not args.force:
        names = ", ".join(f"{f['id']}" for f in in_progress)
        print(f"\nWARNING: Features still in progress: {names}")
        confirm = input("Archive anyway? [y/N] ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return 1

    archive_dir.mkdir(parents=True, exist_ok=True)

    for item in harness_dir.iterdir():
        if item.name in PRESERVE_FILES:
            continue
        dest = archive_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
            shutil.rmtree(item)
        else:
            shutil.copy2(item, dest)
            item.unlink()

    print(f"Archived. .harness/ is now clean (archive/ preserved).")
    print("Run /harness to start a new INIT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
