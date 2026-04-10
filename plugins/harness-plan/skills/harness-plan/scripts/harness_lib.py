#!/usr/bin/env python3
"""Shared helpers for harness v2 state management scripts."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


VALID_MODES = {"lite", "standard", "heavy"}
VALID_STATUSES = {"backlog", "pending", "in_progress", "done", "blocked", "skipped"}
VALID_REVIEW_POLICIES = {"selftest", "qa"}
ENVIRONMENT_STATUSES = {"unknown", "passing", "failing", "bootstrapped"}
TRANSITIONS = {
    "backlog": {"pending", "in_progress", "skipped"},
    "pending": {"in_progress", "skipped"},
    "in_progress": {"done", "blocked"},
    "blocked": {"pending"},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _find_harness_root(start: Path) -> Optional[Path]:
    """Walk up from *start* looking for a directory that contains .harness/."""
    current = start.resolve()
    for _ in range(current.parts.__len__()):
        if (current / ".harness").is_dir():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def project_root_arg(value: Optional[str]) -> Path:
    if value and value != ".":
        return Path(value).resolve()
    # No explicit root: walk up from cwd to find .harness/
    found = _find_harness_root(Path.cwd())
    return found if found else Path(".").resolve()


def harness_dir(project_root: Path) -> Path:
    return project_root / ".harness"


def require_harness(project_root: Path) -> None:
    """Exit with a clear message if no .harness/ directory exists."""
    d = harness_dir(project_root)
    if not d.is_dir():
        print(
            f"No .harness/ directory at {d}.\n"
            f"Resolved project root: {project_root}\n"
            f"Working directory: {Path.cwd()}\n"
            f"Hint: pass --project-root <path> if the working directory is not the project root.",
            file=sys.stderr,
        )
        sys.exit(1)


def harness_file(project_root: Path, name: str) -> Path:
    path = (harness_dir(project_root) / name).resolve()
    root = harness_dir(project_root).resolve()
    if root not in path.parents and path != root:
        raise ValueError(f"Refusing to access path outside .harness: {path}")
    return path


def ensure_harness_dir(project_root: Path) -> Path:
    path = harness_dir(project_root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_json(path: Path, required: bool = True, hint: Optional[str] = None) -> Optional[Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        if required:
            msg = f"Missing required file: {path}"
            if hint:
                msg += f"\n{hint}"
            raise SystemExit(msg)
        return None
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def write_json(path: Path, payload: Any) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")


def ensure_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def dedupe(items: Iterable[str]) -> List[str]:
    seen = set()
    output = []
    for item in items:
        text = item.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def parse_legacy_checkpoint(notes: Optional[str]) -> Optional[Dict[str, Any]]:
    if not notes:
        return None
    completed_steps: List[str] = []
    next_step = ""
    open_issues: List[str] = []
    for raw_line in notes.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower = line.lower()
        if lower.startswith("completed:"):
            completed_steps.extend(split_inline_list(line.split(":", 1)[1]))
        elif lower.startswith("next:"):
            next_step = line.split(":", 1)[1].strip()
        elif lower.startswith("issues:"):
            open_issues.extend(split_inline_list(line.split(":", 1)[1]))
        else:
            completed_steps.append(line)
    return {
        "completed_steps": dedupe(completed_steps),
        "next_step": next_step,
        "open_issues": dedupe(open_issues),
        "files_touched": [],
        "tests_run": [],
        "last_updated": utc_now(),
        "last_verified_commit": None,
        "selftest_retries": 0,
        "checkpoint_writes": 0,
    }


def split_inline_list(value: str) -> List[str]:
    text = value.strip()
    if not text:
        return []
    parts = re.split(r"\s*[;,]\s*|\s+\|\s+|\s+/\s+", text)
    output = [part.strip(" -") for part in parts if part.strip(" -")]
    if output:
        return output
    return [text]


def normalize_checkpoint(value: Any) -> Optional[Dict[str, Any]]:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        return parse_legacy_checkpoint(value)
    if not isinstance(value, dict):
        raise ValueError("checkpoint must be an object or null")
    return {
        "completed_steps": dedupe([str(item) for item in ensure_list(value.get("completed_steps"))]),
        "next_step": str(value.get("next_step") or "").strip(),
        "open_issues": dedupe([str(item) for item in ensure_list(value.get("open_issues"))]),
        "files_touched": dedupe([str(item) for item in ensure_list(value.get("files_touched"))]),
        "tests_run": dedupe([str(item) for item in ensure_list(value.get("tests_run"))]),
        "last_updated": str(value.get("last_updated") or utc_now()),
        "last_verified_commit": value.get("last_verified_commit"),
        "selftest_retries": int(value.get("selftest_retries") or 0),
        "checkpoint_writes": int(value.get("checkpoint_writes") or 0),
    }


def normalize_feature(feature: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(feature)
    normalized.setdefault("dependencies", [])
    normalized.setdefault("sessions", [])
    normalized.setdefault("blocked_reason", None)
    normalized.setdefault("blocked_history", [])
    normalized.setdefault("archived_contract", None)
    normalized.setdefault("acceptance_checklist", None)
    checkpoint = normalized.get("checkpoint")
    if checkpoint is None and normalized.get("checkpoint_notes") is not None:
        checkpoint = parse_legacy_checkpoint(normalized.get("checkpoint_notes"))
    normalized["checkpoint"] = normalize_checkpoint(checkpoint)
    normalized.pop("checkpoint_notes", None)
    return normalized


def normalize_campaign(campaign: Dict[str, Any], features: List[Dict[str, Any]], project_root: Path) -> Dict[str, Any]:
    normalized = dict(campaign)
    normalized.setdefault("goal", "")
    normalized.setdefault("created", utc_now())
    normalized.setdefault("test_command", "")
    normalized.setdefault("setup_command", None)
    normalized.setdefault("bootstrap_command", None)
    normalized.setdefault("project_root", str(project_root))
    normalized.setdefault("current_feature", None)
    normalized.setdefault("current_feature_started", None)
    normalized.setdefault("last_session_date", "")
    normalized.setdefault("session_count", 0)
    normalized.setdefault("mode", "standard")
    normalized.setdefault("default_review_policy", "selftest")
    normalized.setdefault("last_session_commit", None)
    normalized.setdefault("baseline_status", "unknown")
    normalized["total_features"] = len(features)
    normalized["completed_features"] = sum(1 for feature in features if feature.get("status") == "done")
    return normalized


def load_state(project_root: Path) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    campaign_path = harness_file(project_root, "campaign.json")
    features_path = harness_file(project_root, "features.json")
    campaign = load_json(campaign_path, required=True, hint="Run /harness-plan to initialize the campaign first.")
    features_payload = load_json(features_path, required=True, hint="Run /harness-plan to initialize features first.")
    if not isinstance(campaign, dict):
        raise ValueError("campaign.json must contain an object")
    if not isinstance(features_payload, dict) or "features" not in features_payload:
        raise ValueError("features.json must contain an object with a features array")
    raw_features = features_payload["features"]
    if not isinstance(raw_features, list):
        raise ValueError("features must be an array")
    features = [normalize_feature(item) for item in raw_features]
    campaign = normalize_campaign(campaign, features, project_root)
    return campaign, features


def save_state(project_root: Path, campaign: Dict[str, Any], features: List[Dict[str, Any]]) -> None:
    ensure_harness_dir(project_root)
    campaign = normalize_campaign(campaign, features, project_root)
    write_json(harness_file(project_root, "campaign.json"), campaign)
    write_json(
        harness_file(project_root, "features.json"),
        {
            "$schema": ".harness/features-schema.json",
            "features": features,
        },
    )


def load_contract(project_root: Path, required: bool = False) -> Optional[Dict[str, Any]]:
    payload = load_json(harness_file(project_root, "current-contract.json"), required=required)
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("current-contract.json must contain an object")
    return payload


def write_contract(project_root: Path, payload: Dict[str, Any]) -> None:
    ensure_harness_dir(project_root)
    write_json(harness_file(project_root, "current-contract.json"), payload)


def archive_contract(project_root: Path, feature: Dict[str, Any]) -> None:
    """Archive the current contract into the feature record before removing the file."""
    path = harness_file(project_root, "current-contract.json")
    if not path.exists():
        return
    contract = load_json(path, required=False)
    if contract and isinstance(contract, dict):
        feature["archived_contract"] = contract
    path.unlink()


def remove_contract(project_root: Path) -> None:
    path = harness_file(project_root, "current-contract.json")
    if path.exists():
        path.unlink()


def load_session_summary(project_root: Path, required: bool = False) -> Optional[Dict[str, Any]]:
    payload = load_json(harness_file(project_root, "session-summary.json"), required=required)
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("session-summary.json must contain an object")
    return payload


def write_session_summary(project_root: Path, payload: Dict[str, Any]) -> None:
    ensure_harness_dir(project_root)
    # freshness_warnings are runtime-only signals — never persist them,
    # otherwise a new session reads stale warnings from the previous session.
    cleaned = {k: v for k, v in payload.items() if k != "freshness_warnings"}
    write_json(harness_file(project_root, "session-summary.json"), cleaned)


def get_feature(features: List[Dict[str, Any]], feature_id: str) -> Dict[str, Any]:
    for feature in features:
        if feature.get("id") == feature_id:
            return feature
    raise ValueError(f"Unknown feature id: {feature_id}")


def require_active_feature(
    campaign: Dict[str, Any],
    features: List[Dict[str, Any]],
    feature_id: Optional[str],
    *,
    verb: str = "operate on",
) -> Tuple[str, Dict[str, Any]]:
    """Resolve and validate the active in_progress feature. Returns (feature_id, feature)."""
    feature_id = feature_id or campaign.get("current_feature")
    if not feature_id:
        raise SystemExit(f"No feature id supplied and campaign.current_feature is empty.")
    active_feature_id = campaign.get("current_feature")
    if not active_feature_id:
        raise SystemExit(f"campaign.current_feature is empty. Cannot {verb} without an active feature.")
    if feature_id != active_feature_id:
        raise SystemExit(f"Cannot {verb} {feature_id}. The active feature is {active_feature_id}.")
    feature = get_feature(features, feature_id)
    if feature.get("status") != "in_progress":
        raise SystemExit(f"Cannot {verb} {feature_id} because its status is {feature.get('status')}.")
    return feature_id, feature


def validate_dependencies(features: List[Dict[str, Any]]) -> List[str]:
    """Detect dangling references and circular dependencies."""
    errors: List[str] = []
    all_ids = {f.get("id") for f in features}
    for feature in features:
        for dep in feature.get("dependencies") or []:
            if dep not in all_ids:
                errors.append(f"Feature {feature.get('id')}: depends on unknown feature {dep}")
    # Cycle detection via DFS
    graph: Dict[str, List[str]] = {}
    for feature in features:
        fid = feature.get("id", "")
        graph[fid] = list(feature.get("dependencies") or [])
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {fid: WHITE for fid in graph}
    path: List[str] = []

    def dfs(node: str) -> bool:
        color[node] = GRAY
        path.append(node)
        for neighbor in graph.get(node, []):
            if neighbor not in color:
                continue
            if color[neighbor] == GRAY:
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                errors.append(f"Circular dependency detected: {' -> '.join(cycle)}")
                path.pop()
                return True
            if color[neighbor] == WHITE:
                if dfs(neighbor):
                    path.pop()
                    return True
        color[node] = BLACK
        path.pop()
        return False

    for fid in graph:
        if color[fid] == WHITE:
            dfs(fid)
    return errors


def eligible_features(features: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    done = {feature.get("id") for feature in features if feature.get("status") == "done"}
    output = []
    for feature in features:
        if feature.get("status") != "pending":
            continue
        deps = set(feature.get("dependencies") or [])
        if deps.issubset(done):
            output.append(feature)
    return sorted(output, key=lambda item: (item.get("priority", 99), item.get("id", "")))


def count_statuses(features: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {status: 0 for status in VALID_STATUSES}
    for feature in features:
        status = feature.get("status", "pending")
        counts.setdefault(status, 0)
        counts[status] += 1
    counts["total"] = len(features)
    counts["completed"] = counts.get("done", 0)
    return counts


def find_last_completed_feature(features: List[Dict[str, Any]]) -> Optional[str]:
    for feature in reversed(features):
        if feature.get("status") == "done":
            return feature.get("id")
    return None


def _git(project_root: Path, *args: str) -> Optional[str]:
    """Run a git command and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _git_lines(project_root: Path, *args: str) -> List[str]:
    output = _git(project_root, *args)
    if not output:
        return []
    return [line.strip() for line in output.splitlines() if line.strip()]


def infer_git_commit(project_root: Path) -> Optional[str]:
    output = _git(project_root, "rev-parse", "HEAD")
    return output.strip() if output and output.strip() else None


def infer_git_changed_files(project_root: Path, since_commit: Optional[str] = None) -> List[str]:
    """Return files changed since a commit (or uncommitted changes if None)."""
    if since_commit:
        files = _git_lines(project_root, "diff", "--name-only", since_commit, "HEAD")
    else:
        files = _git_lines(project_root, "diff", "--name-only", "HEAD")
    files.extend(_git_lines(project_root, "diff", "--name-only", "--cached"))
    return dedupe(files)


def check_git_drift(project_root: Path, last_verified_commit: Optional[str]) -> Dict[str, Any]:
    """Compare current HEAD against last_verified_commit and report drift."""
    current = infer_git_commit(project_root)
    result: Dict[str, Any] = {"drifted": False, "current_head": current, "last_verified": last_verified_commit, "changed_files": []}
    if not current or not last_verified_commit or current == last_verified_commit:
        return result
    result["drifted"] = True
    result["changed_files"] = infer_git_changed_files(project_root, last_verified_commit)
    return result


def stringify_verification(verification: Any) -> str:
    if isinstance(verification, str):
        return verification
    if isinstance(verification, dict):
        parts = []
        for key in ("command", "manual_check", "expected"):
            value = verification.get(key)
            if value:
                parts.append(f"{key}: {value}")
        return " | ".join(parts)
    return ""


COMMAND_PATTERN = re.compile(
    r"`([^`]+)`|((?:npm|pnpm|yarn|npx|pytest|python3?|uv|go|cargo|make|docker|bash|sh)\s+[^\n]+)",
    re.IGNORECASE,
)


def extract_commands(text: str) -> List[str]:
    commands = []
    for match in COMMAND_PATTERN.finditer(text):
        command = match.group(1) or match.group(2) or ""
        command = command.strip().rstrip(".")
        if command:
            commands.append(command)
    return dedupe(commands)


def extract_manual_checks(text: str) -> List[str]:
    lowered = text.lower()
    triggers = ("navigate", "click", "open ", "visit ", "render", "verify ", "browser", "ui", "screen", "page")
    if any(token in lowered for token in triggers):
        return [text.strip()]
    return []


def parse_verification(feature: Dict[str, Any]) -> Tuple[List[str], List[str], List[str]]:
    verification = feature.get("verification")
    claims: List[str] = []
    commands: List[str] = []
    manual_checks: List[str] = []
    if isinstance(verification, str):
        text = verification.strip()
        if text:
            claims.append(text)
            commands.extend(extract_commands(text))
            manual_checks.extend(extract_manual_checks(text))
    elif isinstance(verification, dict):
        command = str(verification.get("command") or "").strip()
        manual = str(verification.get("manual_check") or "").strip()
        expected = str(verification.get("expected") or "").strip()
        if command:
            commands.append(command)
            claims.append(f"Run {command} successfully")
        if manual:
            manual_checks.append(manual)
            claims.append(manual)
        if expected:
            claims.append(expected)
    checklist = ensure_list(feature.get("acceptance_checklist"))
    claims.extend([str(item) for item in checklist if isinstance(item, str)])
    return dedupe(claims), dedupe(commands), dedupe(manual_checks)


def derive_review_policy(feature: Dict[str, Any], campaign: Optional[Dict[str, Any]] = None) -> str:
    default_policy = (campaign or {}).get("default_review_policy", "selftest")
    text = " ".join(
        [
            str(feature.get("name") or ""),
            str(feature.get("description") or ""),
            stringify_verification(feature.get("verification")),
            " ".join([str(item) for item in ensure_list(feature.get("acceptance_checklist"))]),
        ]
    ).lower()
    risky_keywords = (
        "browser",
        "playwright",
        "screen",
        "page render",
        "form submit",
        "auth",
        "oauth",
        "login",
        "session token",
        "payment",
        "billing",
        "subscription",
        "stripe",
        "migration",
        "database migration",
        "schema change",
        "alter table",
        "concurrency",
        "race condition",
        "lock",
        "queue",
        "webhook",
        "external api",
        "third-party",
        "integration test",
        "api route",
        "middleware",
        "permission",
        "rbac",
        "encryption",
        "secret",
        "credential",
    )
    if any(keyword in text for keyword in risky_keywords):
        return "qa"
    return default_policy if default_policy in VALID_REVIEW_POLICIES else "selftest"


def default_scope_lists(mode: str) -> Tuple[List[str], List[str]]:
    if mode == "lite":
        return [], []
    return (
        [
            "Implement only the selected feature's verification contract.",
            "Touch the smallest set of files required to satisfy verification.",
        ],
        [
            "Do not modify the immutable verification criteria.",
            "Do not expand scope into unrelated features.",
        ],
    )


def build_contract(
    feature: Dict[str, Any],
    campaign: Dict[str, Any],
    *,
    review_policy: Optional[str] = None,
    scope_in: Optional[List[str]] = None,
    scope_out: Optional[List[str]] = None,
    claims: Optional[List[str]] = None,
    commands: Optional[List[str]] = None,
    manual_checks: Optional[List[str]] = None,
    checklist_items: Optional[List[str]] = None,
) -> Dict[str, Any]:
    mode = campaign.get("mode", "standard")
    derived_claims, derived_commands, derived_manual = parse_verification(feature)
    if claims:
        derived_claims.extend(claims)
    if commands:
        derived_commands.extend(commands)
    if manual_checks:
        derived_manual.extend(manual_checks)
    review_policy = review_policy or derive_review_policy(feature, campaign)
    if review_policy not in VALID_REVIEW_POLICIES:
        raise ValueError(f"Invalid review policy: {review_policy}")
    default_in, default_out = default_scope_lists(mode)
    contract = {
        "feature_id": feature["id"],
        "goal": f"Deliver {feature['id']} - {feature['name']}",
        "scope_in": dedupe(scope_in if scope_in is not None else default_in),
        "scope_out": dedupe(scope_out if scope_out is not None else default_out),
        "verification_claims": dedupe(derived_claims),
        "verification_commands": dedupe(derived_commands),
        "manual_checks": dedupe(derived_manual),
        "review_policy": review_policy,
        "execution_context": {
            "cwd": str(campaign.get("project_root", ".")),
            "timeout_seconds": 300,
        },
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }
    if mode != "lite":
        if checklist_items is not None:
            feature["acceptance_checklist"] = dedupe(checklist_items)
        elif feature.get("acceptance_checklist") is None:
            feature["acceptance_checklist"] = dedupe(contract["verification_claims"])
    return contract


def next_resume_steps(
    campaign: Dict[str, Any],
    features: List[Dict[str, Any]],
    contract: Optional[Dict[str, Any]],
    existing_summary: Optional[Dict[str, Any]] = None,
) -> List[str]:
    current_id = campaign.get("current_feature")
    if current_id:
        feature = get_feature(features, current_id)
        checkpoint = feature.get("checkpoint") or {}
        next_step = str(checkpoint.get("next_step") or "").strip()
        if next_step:
            return [next_step]
        if contract and contract.get("verification_commands"):
            return [f"Resume {current_id} by running: {contract['verification_commands'][0]}"]
        if (
            existing_summary
            and existing_summary.get("current_feature") == current_id
            and existing_summary.get("resume_steps")
        ):
            steps = dedupe([str(item) for item in existing_summary.get("resume_steps", [])])
            if steps:
                return steps
        return [f"Resume {current_id} and refresh the active checkpoint before more edits."]
    next_feature = eligible_features(features)
    if next_feature:
        target = next_feature[0]
        return [
            f"Select {target['id']} - {target['name']} as the next feature.",
            "Create or refresh .harness/current-contract.json before coding.",
        ]
    blocked = [feature["id"] for feature in features if feature.get("status") == "blocked"]
    if blocked:
        return [f"Resolve blocked features before continuing: {', '.join(blocked)}."]
    return ["Run final verification and decide whether to archive or reset the campaign."]


def summarize_known_failures(features: List[Dict[str, Any]], campaign: Dict[str, Any]) -> List[str]:
    failures: List[str] = []
    if campaign.get("baseline_status") == "failing":
        failures.append("Baseline verification is failing.")
    for feature in features:
        if feature.get("status") == "blocked":
            reason = str(feature.get("blocked_reason") or "").strip()
            if reason:
                failures.append(f"{feature['id']}: {reason}")
    return dedupe(failures)


def build_session_summary(
    campaign: Dict[str, Any],
    features: List[Dict[str, Any]],
    contract: Optional[Dict[str, Any]],
    existing_summary: Optional[Dict[str, Any]] = None,
    *,
    environment_status: Optional[str] = None,
    resume_steps: Optional[List[str]] = None,
    known_failures: Optional[List[str]] = None,
) -> Dict[str, Any]:
    summary = dict(existing_summary or {})
    counts = count_statuses(features)
    summary["campaign_goal"] = campaign.get("goal", "")
    summary["mode"] = campaign.get("mode", "standard")
    summary["current_feature"] = campaign.get("current_feature")
    summary["last_completed_feature"] = find_last_completed_feature(features)
    summary["progress_counts"] = counts
    summary["resume_steps"] = dedupe(resume_steps or next_resume_steps(campaign, features, contract, existing_summary))
    summary["known_failures"] = dedupe(known_failures or summarize_known_failures(features, campaign))
    summary["environment_status"] = environment_status or campaign.get("baseline_status", "unknown")
    summary["last_session_date"] = campaign.get("last_session_date", "")
    summary["last_session_commit"] = campaign.get("last_session_commit")
    # Fold open_issues from the current feature's checkpoint into the summary
    current_id = campaign.get("current_feature")
    open_issues: List[str] = []
    if current_id:
        try:
            feature = get_feature(features, current_id)
            checkpoint = feature.get("checkpoint") or {}
            open_issues = [str(i) for i in (checkpoint.get("open_issues") or [])]
        except ValueError:
            pass
    summary["open_issues"] = dedupe(open_issues)
    # Session freshness indicators
    freshness_warnings: List[str] = []
    done_count = counts.get("done", 0)
    prev_done = (existing_summary or {}).get("progress_counts", {}).get("done", 0)
    session_done = done_count - prev_done
    if session_done >= 2:
        freshness_warnings.append(f"{session_done} features completed this session — consider a fresh session.")
    if current_id:
        try:
            feature = get_feature(features, current_id)
            cp = feature.get("checkpoint") or {}
            writes = cp.get("checkpoint_writes", 0)
            steps = len(cp.get("completed_steps") or [])
            retries = cp.get("selftest_retries", 0)
            if writes >= 3:
                freshness_warnings.append(f"checkpoint written {writes} times — context may be heavy.")
            if steps >= 10:
                freshness_warnings.append(f"{steps} completed steps — consider a fresh session.")
            if retries >= 3:
                freshness_warnings.append(f"selftest failed {retries} times — block this feature.")
        except ValueError:
            pass
    summary["freshness_warnings"] = freshness_warnings
    return summary


def validate_feature(feature: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    feature_id = feature.get("id")
    status = feature.get("status")
    if not isinstance(feature_id, str) or not re.match(r"^F[0-9]{3,4}$", feature_id):
        errors.append(f"Feature has invalid id: {feature_id!r}")
    if not isinstance(feature.get("name"), str) or not feature.get("name"):
        errors.append(f"Feature {feature_id}: missing name")
    if status not in VALID_STATUSES:
        errors.append(f"Feature {feature_id}: invalid status {status!r}")
    if not isinstance(feature.get("priority"), int) or not (1 <= feature["priority"] <= 5):
        errors.append(f"Feature {feature_id}: priority must be an integer between 1 and 5")
    verification = feature.get("verification")
    if not isinstance(verification, (str, dict)):
        errors.append(f"Feature {feature_id}: verification must be a string or object")
    elif isinstance(verification, dict):
        invalid_keys = set(verification.keys()) - {"command", "manual_check", "expected"}
        if invalid_keys:
            errors.append(f"Feature {feature_id}: verification has unsupported keys: {sorted(invalid_keys)}")
    checkpoint = feature.get("checkpoint")
    if checkpoint is not None:
        if not isinstance(checkpoint, dict):
            errors.append(f"Feature {feature_id}: checkpoint must be an object or null")
        else:
            if not isinstance(checkpoint.get("completed_steps"), list):
                errors.append(f"Feature {feature_id}: checkpoint.completed_steps must be an array")
            if not isinstance(checkpoint.get("next_step"), str):
                errors.append(f"Feature {feature_id}: checkpoint.next_step must be a string")
            if not isinstance(checkpoint.get("open_issues"), list):
                errors.append(f"Feature {feature_id}: checkpoint.open_issues must be an array")
            if not isinstance(checkpoint.get("files_touched"), list):
                errors.append(f"Feature {feature_id}: checkpoint.files_touched must be an array")
            if not isinstance(checkpoint.get("tests_run"), list):
                errors.append(f"Feature {feature_id}: checkpoint.tests_run must be an array")
            if not isinstance(checkpoint.get("last_updated"), str):
                errors.append(f"Feature {feature_id}: checkpoint.last_updated must be a string")
            if checkpoint.get("last_verified_commit") is not None and not isinstance(
                checkpoint.get("last_verified_commit"), str
            ):
                errors.append(f"Feature {feature_id}: checkpoint.last_verified_commit must be a string or null")
            if not isinstance(checkpoint.get("selftest_retries", 0), int):
                errors.append(f"Feature {feature_id}: checkpoint.selftest_retries must be an integer")
            if not isinstance(checkpoint.get("checkpoint_writes", 0), int):
                errors.append(f"Feature {feature_id}: checkpoint.checkpoint_writes must be an integer")
        if status != "in_progress":
            errors.append(f"Feature {feature_id}: only in_progress features may carry a checkpoint")
    return errors


def validate_campaign(campaign: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if not isinstance(campaign.get("goal"), str):
        errors.append("campaign.goal must be a string")
    if campaign.get("mode") not in VALID_MODES:
        errors.append(f"campaign.mode must be one of {sorted(VALID_MODES)}")
    if campaign.get("default_review_policy") not in VALID_REVIEW_POLICIES:
        errors.append("campaign.default_review_policy must be 'selftest' or 'qa'")
    if campaign.get("baseline_status") not in ENVIRONMENT_STATUSES:
        errors.append("campaign.baseline_status must be unknown, passing, or failing")
    if campaign.get("current_feature") is not None and not isinstance(campaign.get("current_feature"), str):
        errors.append("campaign.current_feature must be a string or null")
    return errors


def validate_contract(contract: Dict[str, Any], features: List[Dict[str, Any]]) -> List[str]:
    errors: List[str] = []
    feature_ids = {feature.get("id") for feature in features}
    if contract.get("feature_id") not in feature_ids:
        errors.append("current-contract.json references an unknown feature_id")
    for field in ("goal", "created_at", "updated_at"):
        if not isinstance(contract.get(field), str):
            errors.append(f"current-contract.{field} must be a string")
    for field in ("scope_in", "scope_out", "verification_claims", "verification_commands", "manual_checks"):
        if not isinstance(contract.get(field), list):
            errors.append(f"current-contract.{field} must be an array")
    if contract.get("review_policy") not in VALID_REVIEW_POLICIES:
        errors.append("current-contract.review_policy must be 'selftest' or 'qa'")
    exec_ctx = contract.get("execution_context")
    if exec_ctx is not None:
        if not isinstance(exec_ctx, dict):
            errors.append("current-contract.execution_context must be an object")
        elif not isinstance(exec_ctx.get("cwd"), str):
            errors.append("current-contract.execution_context.cwd must be a string")
    return errors


def validate_session_summary(summary: Dict[str, Any], feature_ids: Iterable[str]) -> List[str]:
    errors: List[str] = []
    if not isinstance(summary.get("campaign_goal"), str):
        errors.append("session-summary.campaign_goal must be a string")
    if summary.get("mode") not in VALID_MODES:
        errors.append("session-summary.mode must be lite, standard, or heavy")
    current_feature = summary.get("current_feature")
    if current_feature is not None and current_feature not in set(feature_ids):
        errors.append("session-summary.current_feature references an unknown feature")
    if summary.get("last_completed_feature") is not None and summary.get("last_completed_feature") not in set(feature_ids):
        errors.append("session-summary.last_completed_feature references an unknown feature")
    if not isinstance(summary.get("progress_counts"), dict):
        errors.append("session-summary.progress_counts must be an object")
    if not isinstance(summary.get("resume_steps"), list):
        errors.append("session-summary.resume_steps must be an array")
    if not isinstance(summary.get("known_failures"), list):
        errors.append("session-summary.known_failures must be an array")
    if not isinstance(summary.get("open_issues"), list):
        errors.append("session-summary.open_issues must be an array")
    if not isinstance(summary.get("environment_status"), str):
        errors.append("session-summary.environment_status must be a string")
    return errors


def validate_state_links(
    campaign: Dict[str, Any],
    features: List[Dict[str, Any]],
    contract: Optional[Dict[str, Any]],
    summary: Optional[Dict[str, Any]],
) -> List[str]:
    errors: List[str] = []
    feature_ids = [feature.get("id") for feature in features]
    if len(feature_ids) != len(set(feature_ids)):
        errors.append("features.json contains duplicate feature ids")
    in_progress = [feature.get("id") for feature in features if feature.get("status") == "in_progress"]
    if len(in_progress) > 1:
        errors.append("More than one feature is marked in_progress")
    current_feature = campaign.get("current_feature")
    if current_feature and current_feature not in in_progress:
        errors.append("campaign.current_feature must point to the single in_progress feature")
    if not current_feature and in_progress:
        errors.append("campaign.current_feature is empty while a feature is marked in_progress")
    if contract is not None and current_feature and contract.get("feature_id") != current_feature:
        errors.append("current-contract.feature_id does not match campaign.current_feature")
    if contract is not None and not current_feature:
        errors.append("current-contract.json exists but campaign.current_feature is empty")
    if contract is not None and current_feature:
        active_feature = next((feature for feature in features if feature.get("id") == current_feature), None)
        if active_feature and active_feature.get("status") != "in_progress":
            errors.append("current-contract.json exists but the active feature is not in_progress")
    if summary is not None and summary.get("current_feature") != current_feature:
        errors.append("session-summary.current_feature does not match campaign.current_feature")
    return errors


def format_summary_lines(summary: Dict[str, Any], review_policy: str) -> List[str]:
    counts = summary.get("progress_counts", {})
    progress = (
        f"{counts.get('completed', 0)}/{counts.get('total', 0)}"
        f" done, {counts.get('in_progress', 0)} in progress, {counts.get('blocked', 0)} blocked"
    )
    next_step = ""
    if summary.get("resume_steps"):
        next_step = summary["resume_steps"][0]
    lines = [
        f"Campaign: {summary.get('campaign_goal', '')}",
        f"Progress: {progress} (mode: {summary.get('mode', 'standard')})",
        f"Current feature: {summary.get('current_feature') or 'none'}",
        f"Review policy: {review_policy}",
        f"Environment: {summary.get('environment_status', 'unknown')}",
        f"Last session: {summary.get('last_session_date') or 'unknown'}",
        f"Next: {next_step or 'Run harness_summary.py to refresh resume steps.'}",
    ]
    freshness = summary.get("freshness_warnings") or []
    if freshness:
        lines.append("Session freshness:")
        for warning in freshness:
            lines.append(f"  ! {warning}")
    return lines


def fail(message: str, *, exit_code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(exit_code)
