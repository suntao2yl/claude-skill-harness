#!/usr/bin/env python3
"""Build or verify the lightweight Codex distribution from canonical sources."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
SOURCE_SKILLS_ROOT = REPO / "skills"
MANIFEST_TEMPLATE = REPO / "codex" / "plugin-manifest.json"
PLUGIN_ROOT = REPO / "plugins" / "harness"

IGNORED_NAMES = {".DS_Store", "__pycache__"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
FORBIDDEN_COMPONENTS = {
    ".claude-plugin",
    ".engineering",
    ".engineering-archive",
    ".git",
    "docs",
    "validation",
}
EXPECTED_SKILL_FILES = {
    "harness": {
        "SKILL.md",
        "agents/openai.yaml",
        "scripts/harness_ledger.py",
        "templates/agents/harness_planner.toml",
        "templates/agents/harness_implementer.toml",
        "templates/agents/harness_checker.toml",
    },
}


def included_file(path: Path, source_skill: Path) -> bool:
    relative = path.relative_to(source_skill)
    return not (
        any(part in IGNORED_NAMES for part in relative.parts)
        or path.suffix in IGNORED_SUFFIXES
    )


def source_files() -> list[Path]:
    files: list[Path] = []
    for skill_name in sorted(EXPECTED_SKILL_FILES):
        source_skill = SOURCE_SKILLS_ROOT / skill_name
        files.extend(
            path
            for path in source_skill.rglob("*")
            if path.is_file() and included_file(path, source_skill)
        )
    return sorted(files, key=lambda path: path.relative_to(SOURCE_SKILLS_ROOT).as_posix())


def source_inventory_errors() -> list[str]:
    errors: list[str] = []
    actual_files = source_files()
    for skill_name, expected in EXPECTED_SKILL_FILES.items():
        source_skill = SOURCE_SKILLS_ROOT / skill_name
        actual = {
            path.relative_to(source_skill).as_posix()
            for path in actual_files
            if path.is_relative_to(source_skill)
        }
        for relative in sorted(expected - actual):
            errors.append(f"missing canonical {skill_name} file: {relative}")
        for relative in sorted(actual - expected):
            errors.append(f"unexpected canonical {skill_name} file: {relative}")
    return errors


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_inventory() -> dict[str, str]:
    inventory = {".codex-plugin/plugin.json": sha256(MANIFEST_TEMPLATE)}
    for source in source_files():
        relative = source.relative_to(SOURCE_SKILLS_ROOT).as_posix()
        inventory[f"skills/{relative}"] = sha256(source)
    return inventory


def actual_inventory() -> dict[str, str]:
    if not PLUGIN_ROOT.exists():
        return {}
    return {
        path.relative_to(PLUGIN_ROOT).as_posix(): sha256(path)
        for path in sorted(PLUGIN_ROOT.rglob("*"))
        if path.is_file()
    }


def verify() -> list[str]:
    expected = expected_inventory()
    actual = actual_inventory()
    errors: list[str] = []
    for relative in sorted(set(expected) - set(actual)):
        errors.append(f"missing distribution file: {relative}")
    for relative in sorted(set(actual) - set(expected)):
        errors.append(f"unexpected distribution file: {relative}")
    for relative in sorted(set(expected) & set(actual)):
        if expected[relative] != actual[relative]:
            errors.append(f"distribution file differs from canonical source: {relative}")
    for relative in actual:
        parts = Path(relative).parts
        if any(part in FORBIDDEN_COMPONENTS for part in parts):
            errors.append(f"forbidden distribution component: {relative}")
        if any(part in IGNORED_NAMES for part in parts) or Path(relative).suffix in IGNORED_SUFFIXES:
            errors.append(f"generated/cache file leaked into distribution: {relative}")
    return errors


def sync() -> None:
    parent = PLUGIN_ROOT.parent
    parent.mkdir(parents=True, exist_ok=True)
    staged = parent / f".{PLUGIN_ROOT.name}.staged-{os.getpid()}"
    backup = parent / f".{PLUGIN_ROOT.name}.backup-{os.getpid()}"
    if staged.exists() or backup.exists():
        raise RuntimeError("refusing to overwrite an existing sync staging directory")

    try:
        (staged / ".codex-plugin").mkdir(parents=True)
        shutil.copy2(MANIFEST_TEMPLATE, staged / ".codex-plugin" / "plugin.json")
        for skill_name in sorted(EXPECTED_SKILL_FILES):
            shutil.copytree(
                SOURCE_SKILLS_ROOT / skill_name,
                staged / "skills" / skill_name,
                ignore=shutil.ignore_patterns(".DS_Store", "__pycache__", "*.pyc", "*.pyo"),
            )
        if PLUGIN_ROOT.exists():
            PLUGIN_ROOT.rename(backup)
        staged.rename(PLUGIN_ROOT)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if not PLUGIN_ROOT.exists() and backup.exists():
            backup.rename(PLUGIN_ROOT)
        raise
    finally:
        if staged.exists():
            shutil.rmtree(staged)
        if backup.exists():
            shutil.rmtree(backup)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed distribution without modifying it",
    )
    args = parser.parse_args()

    source_errors = source_inventory_errors()
    if source_errors:
        for error in source_errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if not args.check:
        sync()
    errors = verify()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    file_count = len(actual_inventory())
    byte_count = sum(path.stat().st_size for path in PLUGIN_ROOT.rglob("*") if path.is_file())
    action = "Verified" if args.check else "Synchronized"
    print(f"{action} {PLUGIN_ROOT}: {file_count} files, {byte_count} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
