#!/usr/bin/env python3
"""Maintain the repository-local ledger behind the unified $harness skill."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_fcntl: Any
try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - exercised only on non-POSIX hosts
    _fcntl = None


SCHEMA_VERSION = 1
PDCA_LEDGER_SCHEMA_VERSION = 2
KIND = "cross-task-delivery-ledger"
PDCA_SCHEMA_VERSION = 1
PDCA_PHASES = {"plan", "do", "check", "act"}
PDCA_STATUSES = {"active", "blocked", "complete"}
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
EVIDENCE_FIELDS = ("kind", "ref", "result", "observed_at", "revision")
EVIDENCE_KEYS = set(EVIDENCE_FIELDS) | {"acceptance_ids"}
PASS_RESULTS = {"pass", "success"}
PLACEHOLDER_REVISIONS = {
    "-",
    "n/a",
    "na",
    "none",
    "null",
    "pending",
    "placeholder",
    "replace-me",
    "tbd",
    "todo",
    "unknown",
    "unset",
    "changeme",
}
FALLBACK_LOCK_TIMEOUT_SECONDS = 10.0
FALLBACK_LOCK_RETRY_SECONDS = 0.05
LIST_FIELDS = (
    "completed_acceptance",
    "completed_steps",
    "next_steps",
    "open_issues",
)


class LedgerError(ValueError):
    """A user-correctable ledger error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def project_root(value: str) -> Path:
    root = Path(value).expanduser().resolve()
    if value == ".":
        for candidate in (root, *root.parents):
            if (
                (candidate / ".harness" / "ledger.json").is_file()
                or (
                    (candidate / ".harness" / "campaign.json").is_file()
                    and (candidate / ".harness" / "features.json").is_file()
                )
                or (
                    (candidate / ".engineering" / "implementation" / ".harness" / "campaign.json").is_file()
                    and (candidate / ".engineering" / "implementation" / ".harness" / "features.json").is_file()
                )
            ):
                root = candidate
                break
    if not root.is_dir():
        raise LedgerError(f"project root is not a directory: {root}")
    return root


def harness_dir(root: Path) -> Path:
    return root / ".harness"


def ledger_path(root: Path) -> Path:
    return harness_dir(root) / "ledger.json"


def ensure_safe_directory(path: Path, label: str) -> None:
    if path.is_symlink():
        raise LedgerError(f"refusing symlinked {label}: {path}")
    if path.exists() and not path.is_dir():
        raise LedgerError(f"{label} is not a directory: {path}")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LedgerError(f"missing required file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise LedgerError(f"invalid JSON in {path}: {exc}") from exc


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def contract_digest(goal: str, acceptance: list[dict[str, Any]]) -> str:
    payload = {"goal": goal, "acceptance": acceptance}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            output.append(text)
    return output


def normalize_acceptance(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise LedgerError("contract.acceptance must be a non-empty array")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    allowed = {"id", "criterion", "checks", "verification"}
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise LedgerError(f"acceptance[{index - 1}] must be an object")
        unknown = set(item) - allowed
        if unknown:
            raise LedgerError(f"acceptance[{index - 1}] has unsupported keys: {sorted(unknown)}")
        item_id = str(item.get("id") or f"A{index:03d}").strip()
        if not ID_PATTERN.fullmatch(item_id):
            raise LedgerError(f"acceptance[{index - 1}].id is invalid: {item_id!r}")
        if item_id in seen:
            raise LedgerError(f"duplicate acceptance id: {item_id}")
        seen.add(item_id)
        criterion = str(item.get("criterion") or "").strip()
        if not criterion:
            raise LedgerError(f"acceptance {item_id} has no criterion")
        checks = item.get("checks", [])
        if checks is None:
            checks = []
        if not isinstance(checks, list) or any(not isinstance(value, str) for value in checks):
            raise LedgerError(f"acceptance {item_id}.checks must be an array of strings")
        entry: dict[str, Any] = {
            "id": item_id,
            "criterion": criterion,
            "checks": dedupe(checks),
        }
        if item.get("verification") is not None:
            verification = item["verification"]
            if not isinstance(verification, (str, list, dict)):
                raise LedgerError(
                    f"acceptance {item_id}.verification must be a string, array, or object"
                )
            entry["verification"] = verification
        normalized.append(entry)
    return normalized


def normalize_contract_file(path_text: str, goal: str) -> list[dict[str, Any]]:
    if path_text == "-":
        try:
            payload = json.load(sys.stdin)
        except json.JSONDecodeError as exc:
            raise LedgerError(f"invalid contract JSON on stdin: {exc}") from exc
    else:
        payload = read_json(Path(path_text).expanduser())
    if not isinstance(payload, dict):
        raise LedgerError("contract file must contain an object")
    if payload.get("goal") is not None and str(payload["goal"]).strip() != goal:
        raise LedgerError("contract file goal does not match --goal")
    unknown = set(payload) - {"goal", "acceptance"}
    if unknown:
        raise LedgerError(f"contract file has unsupported keys: {sorted(unknown)}")
    return normalize_acceptance(payload.get("acceptance"))


def empty_checkpoint(now: str) -> dict[str, Any]:
    return {
        "sequence": 0,
        "completed_acceptance": [],
        "completed_steps": [],
        "next_steps": [],
        "open_issues": [],
        "evidence": [],
        "summary": "Delivery ledger initialized.",
        "updated_at": now,
    }


def build_state(
    goal: str,
    acceptance: list[dict[str, Any]],
    *,
    checkpoint: dict[str, Any] | None = None,
    migration: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    now = utc_now()
    state: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "goal": goal,
        "contract": {
            "acceptance": acceptance,
            "sha256": contract_digest(goal, acceptance),
            "approved_at": created_at or now,
        },
        "checkpoint": checkpoint or empty_checkpoint(now),
        "created_at": created_at or now,
        "updated_at": now,
    }
    if migration is not None:
        state["migration"] = migration
    return state


def evidence_error(value: Any, prefix: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{prefix} must be an object"]
    errors: list[str] = []
    unknown = set(value) - EVIDENCE_KEYS
    if unknown:
        errors.append(f"{prefix} has unsupported keys: {sorted(unknown)}")
    for field in EVIDENCE_FIELDS:
        if not isinstance(value.get(field), str) or not value[field].strip():
            errors.append(f"{prefix}.{field} must be a non-empty string")
    if (
        isinstance(value.get("revision"), str)
        and revision_is_placeholder(value["revision"])
        and value.get("kind") != "legacy-claim"
    ):
        errors.append(f"{prefix}.revision must be a non-placeholder token")
    acceptance_ids = value.get("acceptance_ids")
    if acceptance_ids is not None and (
        not isinstance(acceptance_ids, list)
        or any(not isinstance(item, str) or not item.strip() for item in acceptance_ids)
    ):
        errors.append(f"{prefix}.acceptance_ids must be an array of non-empty strings when present")
    return errors


def revision_is_placeholder(value: Any) -> bool:
    if not isinstance(value, str):
        return True
    token = value.strip()
    return (
        token.lower() in PLACEHOLDER_REVISIONS
        or (token.startswith("<") and token.endswith(">"))
    )


def latest_evidence_by_acceptance(evidence: list[Any]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for item in evidence:
        if not isinstance(item, dict) or not isinstance(item.get("acceptance_ids"), list):
            continue
        for acceptance_id in item["acceptance_ids"]:
            if isinstance(acceptance_id, str):
                latest[acceptance_id] = item
    return latest


def evidence_passes(item: dict[str, Any] | None) -> bool:
    if item is None:
        return False
    return (
        str(item.get("result") or "").strip().lower() in PASS_RESULTS
        and not revision_is_placeholder(item.get("revision"))
    )


def pdca_state_errors(
    value: Any,
    *,
    acceptance_ids: set[str],
    contract_sha256: str | None,
    checkpoint: dict[str, Any] | None,
) -> list[str]:
    prefix = "pdca"
    if not isinstance(value, dict):
        return [f"{prefix} must be an object"]
    errors: list[str] = []
    allowed = {
        "schema_version",
        "contract_sha256",
        "policy",
        "policy_sha256",
        "status",
        "phase",
        "cycle",
        "do_attempt",
        "scope",
        "events",
        "bound_checkpoint_sequence",
        "updated_at",
    }
    unknown = set(value) - allowed
    if unknown:
        errors.append(f"{prefix} has unsupported keys: {sorted(unknown)}")
    if value.get("schema_version") != PDCA_SCHEMA_VERSION:
        errors.append(f"{prefix}.schema_version must be {PDCA_SCHEMA_VERSION}")
    if value.get("contract_sha256") != contract_sha256:
        errors.append(f"{prefix}.contract_sha256 must match the immutable contract")

    policy = value.get("policy")
    if not isinstance(policy, dict):
        errors.append(f"{prefix}.policy must be an object")
    else:
        expected_efforts = {"plan": "ultra", "do": "high", "check": "max"}
        for phase, effort in expected_efforts.items():
            role = policy.get(phase)
            if not isinstance(role, dict):
                errors.append(f"{prefix}.policy.{phase} must be an object")
                continue
            if role.get("reasoning_effort") != effort:
                errors.append(
                    f"{prefix}.policy.{phase}.reasoning_effort must be {effort!r}"
                )
            if not isinstance(role.get("agent"), str) or not role["agent"].strip():
                errors.append(f"{prefix}.policy.{phase}.agent must be a non-empty string")
            expected_sandbox = "workspace-write" if phase == "do" else "read-only"
            if role.get("sandbox_mode") != expected_sandbox:
                errors.append(
                    f"{prefix}.policy.{phase}.sandbox_mode must be {expected_sandbox!r}"
                )
        if policy.get("act") != "deterministic":
            errors.append(f"{prefix}.policy.act must be 'deterministic'")
        for field in ("max_cycles", "max_do_attempts"):
            amount = policy.get(field)
            if not isinstance(amount, int) or isinstance(amount, bool) or amount < 1:
                errors.append(f"{prefix}.policy.{field} must be a positive integer")
        expected_policy_sha = hashlib.sha256(canonical_json(policy).encode("utf-8")).hexdigest()
        if value.get("policy_sha256") != expected_policy_sha:
            errors.append(f"{prefix}.policy_sha256 does not match policy")

    status = value.get("status")
    phase = value.get("phase")
    if status not in PDCA_STATUSES:
        errors.append(f"{prefix}.status must be one of {sorted(PDCA_STATUSES)}")
    if phase not in PDCA_PHASES:
        errors.append(f"{prefix}.phase must be one of {sorted(PDCA_PHASES)}")
    cycle = value.get("cycle")
    attempt = value.get("do_attempt")
    if not isinstance(cycle, int) or isinstance(cycle, bool) or cycle < 1:
        errors.append(f"{prefix}.cycle must be a positive integer")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 0:
        errors.append(f"{prefix}.do_attempt must be a non-negative integer")
    if isinstance(policy, dict):
        max_cycles = policy.get("max_cycles")
        max_attempts = policy.get("max_do_attempts")
        if isinstance(cycle, int) and isinstance(max_cycles, int) and cycle > max_cycles:
            errors.append(f"{prefix}.cycle exceeds policy.max_cycles")
        if isinstance(attempt, int) and isinstance(max_attempts, int) and attempt > max_attempts:
            errors.append(f"{prefix}.do_attempt exceeds policy.max_do_attempts")

    scope = value.get("scope")
    scope_values = scope if isinstance(scope, list) else []
    if (
        not isinstance(scope, list)
        or not scope
        or any(not isinstance(item, str) or not item.strip() for item in scope)
        or len(set(scope_values)) != len(scope_values)
    ):
        errors.append(f"{prefix}.scope must be a non-empty array of unique ids")
    else:
        unknown_scope = [item for item in scope if item not in acceptance_ids]
        if unknown_scope:
            errors.append(f"{prefix}.scope has unknown acceptance ids: {unknown_scope}")

    events = value.get("events")
    if not isinstance(events, list):
        errors.append(f"{prefix}.events must be an array")
        events = []
    else:
        for index, event in enumerate(events, start=1):
            event_prefix = f"{prefix}.events[{index - 1}]"
            if not isinstance(event, dict):
                errors.append(f"{event_prefix} must be an object")
                continue
            if event.get("sequence") != index:
                errors.append(f"{event_prefix}.sequence must be {index}")
            if event.get("phase") not in PDCA_PHASES:
                errors.append(f"{event_prefix}.phase is invalid")
            if not isinstance(event.get("outcome"), str) or not event["outcome"].strip():
                errors.append(f"{event_prefix}.outcome must be a non-empty string")
            if not isinstance(event.get("observed_at"), str):
                errors.append(f"{event_prefix}.observed_at must be a string")
            linked = event.get("acceptance_ids")
            if linked != scope_values:
                errors.append(f"{event_prefix}.acceptance_ids must equal pdca.scope")
            if event.get("phase") in {"plan", "do", "check"}:
                for field in ("artifact_ref", "artifact_sha256", "revision", "summary"):
                    if not isinstance(event.get(field), str) or not event[field].strip():
                        errors.append(f"{event_prefix}.{field} must be a non-empty string")
                digest = event.get("artifact_sha256")
                if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                    errors.append(f"{event_prefix}.artifact_sha256 must be a lowercase sha256")
                if revision_is_placeholder(event.get("revision")):
                    errors.append(f"{event_prefix}.revision must be a non-placeholder token")
            if event.get("phase") in {"do", "check"}:
                plan_revision = event.get("plan_revision")
                if not isinstance(plan_revision, str) or revision_is_placeholder(plan_revision):
                    errors.append(f"{event_prefix}.plan_revision must be a non-placeholder token")
            if event.get("phase") == "check":
                criteria = event.get("criteria")
                if not isinstance(criteria, list) or len(criteria) != len(scope_values):
                    errors.append(f"{event_prefix}.criteria must cover pdca.scope exactly once")
                else:
                    criterion_ids: list[str] = []
                    for criterion_index, criterion in enumerate(criteria):
                        criterion_prefix = f"{event_prefix}.criteria[{criterion_index}]"
                        if not isinstance(criterion, dict):
                            errors.append(f"{criterion_prefix} must be an object")
                            continue
                        if set(criterion) != {
                            "acceptance_id", "result", "action", "evidence_ref"
                        }:
                            errors.append(f"{criterion_prefix} has invalid fields")
                        acceptance_id = criterion.get("acceptance_id")
                        if isinstance(acceptance_id, str):
                            criterion_ids.append(acceptance_id)
                        result = criterion.get("result")
                        action = criterion.get("action")
                        if result == "pass":
                            if action is not None:
                                errors.append(f"{criterion_prefix}.action must be null on pass")
                        elif result == "fail":
                            if action not in {"fix", "replan", "blocked"}:
                                errors.append(f"{criterion_prefix}.action is invalid on fail")
                        else:
                            errors.append(f"{criterion_prefix}.result must be pass or fail")
                        if not isinstance(criterion.get("evidence_ref"), str) or not criterion[
                            "evidence_ref"
                        ].strip():
                            errors.append(
                                f"{criterion_prefix}.evidence_ref must be a non-empty string"
                            )
                    if criterion_ids != scope_values:
                        errors.append(
                            f"{event_prefix}.criteria must match pdca.scope in contract order"
                        )
            if event.get("phase") == "act":
                if event.get("decision") not in {"complete", "fix", "replan", "blocked", "restart"}:
                    errors.append(f"{event_prefix}.decision is invalid")
                reasons = event.get("reason_codes")
                if not isinstance(reasons, list) or any(not isinstance(item, str) for item in reasons):
                    errors.append(f"{event_prefix}.reason_codes must be an array of strings")

        plan_event: dict[str, Any] | None = None
        do_event: dict[str, Any] | None = None
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                continue
            event_prefix = f"{prefix}.events[{index}]"
            event_phase = event.get("phase")
            if event_phase == "plan":
                plan_event = event
                do_event = None
            elif event_phase == "do":
                if plan_event is None or event.get("plan_revision") != plan_event.get("revision"):
                    errors.append(f"{event_prefix} is not bound to the current Plan revision")
                do_event = event
            elif event_phase == "check":
                if plan_event is None or event.get("plan_revision") != plan_event.get("revision"):
                    errors.append(f"{event_prefix} is not bound to the current Plan revision")
                if do_event is None or event.get("revision") != do_event.get("revision"):
                    errors.append(f"{event_prefix} is not bound to the current Do revision")

        last_event = events[-1] if events and isinstance(events[-1], dict) else None
        if status == "active" and phase == "do":
            if not isinstance(last_event, dict) or not (
                last_event.get("phase") == "plan"
                or (last_event.get("phase") == "act" and last_event.get("decision") == "fix")
            ):
                errors.append(f"{prefix} active Do phase lacks a Plan or fix transition")
        if status == "active" and phase == "check":
            if not isinstance(last_event, dict) or last_event.get("phase") != "do":
                errors.append(f"{prefix} active Check phase lacks a current Do event")
        if status == "active" and phase == "act":
            if not isinstance(last_event, dict) or last_event.get("phase") != "check":
                errors.append(f"{prefix} active Act phase lacks a current Check event")
        if status == "active" and phase == "plan" and events:
            if not isinstance(last_event, dict) or not (
                last_event.get("phase") == "act"
                and last_event.get("decision") in {"replan", "restart"}
            ):
                errors.append(f"{prefix} active Plan phase has an invalid previous transition")
        if status == "blocked":
            if not isinstance(last_event, dict) or not (
                last_event.get("phase") == "act" and last_event.get("decision") == "blocked"
            ):
                errors.append(f"{prefix} blocked state lacks a deterministic blocked event")
        if status == "complete":
            if not isinstance(last_event, dict) or not (
                last_event.get("phase") == "act" and last_event.get("decision") == "complete"
            ):
                errors.append(f"{prefix} complete state lacks a deterministic complete event")

    if not isinstance(value.get("updated_at"), str):
        errors.append(f"{prefix}.updated_at must be a string")
    if checkpoint is not None:
        if value.get("bound_checkpoint_sequence") != checkpoint.get("sequence"):
            errors.append(f"{prefix}.bound_checkpoint_sequence does not match checkpoint.sequence")
        completed = set(checkpoint.get("completed_acceptance", []))
        scoped = set(scope_values)
        if status == "complete":
            if phase != "act":
                errors.append(f"{prefix}.phase must be 'act' when status is complete")
            missing_completion = sorted(scoped - completed)
            if missing_completion:
                errors.append(
                    f"{prefix} complete scope lacks checkpoint completion: {missing_completion}"
                )
            latest = latest_evidence_by_acceptance(checkpoint.get("evidence", []))
            invalid_evidence = [
                item
                for item in scope_values
                if not (
                    isinstance(latest.get(item), dict)
                    and latest[item].get("kind") == "pdca-check"
                    and evidence_passes(latest[item])
                    and isinstance(last_event, dict)
                    and latest[item].get("revision")
                    == next(
                        (
                            event.get("revision")
                            for event in reversed(events)
                            if isinstance(event, dict) and event.get("phase") == "check"
                        ),
                        None,
                    )
                )
            ]
            if invalid_evidence:
                errors.append(
                    f"{prefix} complete scope lacks latest passing pdca-check evidence: "
                    f"{invalid_evidence}"
                )
        elif set(scope_values) & completed:
            errors.append(f"{prefix} scope cannot be completed before deterministic Act")
    return errors


def state_errors(state: Any, *, expected_schema: int | None = None) -> list[str]:
    if not isinstance(state, dict):
        return ["ledger.json must contain an object"]
    errors: list[str] = []
    actual_schema = state.get("schema_version")
    if expected_schema is None:
        if actual_schema not in {SCHEMA_VERSION, PDCA_LEDGER_SCHEMA_VERSION}:
            errors.append(
                f"schema_version must be {SCHEMA_VERSION} or {PDCA_LEDGER_SCHEMA_VERSION}"
            )
        expected_schema = actual_schema if isinstance(actual_schema, int) else SCHEMA_VERSION
    if state.get("schema_version") != expected_schema:
        errors.append(f"schema_version must be {expected_schema}")
    if state.get("kind") != KIND:
        errors.append(f"kind must be {KIND!r}")
    goal = state.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        errors.append("goal must be a non-empty string")
    contract = state.get("contract")
    acceptance: list[dict[str, Any]] = []
    if not isinstance(contract, dict):
        errors.append("contract must be an object")
    else:
        raw_acceptance = contract.get("acceptance")
        try:
            acceptance = normalize_acceptance(raw_acceptance)
            if raw_acceptance != acceptance:
                errors.append("contract.acceptance must already be in canonical normalized form")
        except LedgerError as exc:
            errors.append(str(exc))
        expected = contract_digest(goal, acceptance) if isinstance(goal, str) and acceptance else None
        if expected and contract.get("sha256") != expected:
            errors.append("immutable acceptance contract digest does not match")
        if not isinstance(contract.get("approved_at"), str):
            errors.append("contract.approved_at must be a string")
    checkpoint = state.get("checkpoint")
    if not isinstance(checkpoint, dict):
        errors.append("checkpoint must be an object")
    else:
        sequence = checkpoint.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            errors.append("checkpoint.sequence must be a non-negative integer")
        for field in LIST_FIELDS:
            value = checkpoint.get(field)
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                errors.append(f"checkpoint.{field} must be an array of strings")
        ids = {item["id"] for item in acceptance}
        completed = checkpoint.get("completed_acceptance", [])
        completed_values = completed if isinstance(completed, list) else []
        if isinstance(completed, list):
            unknown = [item for item in completed if isinstance(item, str) and item not in ids]
            if unknown:
                errors.append(f"checkpoint.completed_acceptance has unknown ids: {unknown}")
        evidence = checkpoint.get("evidence")
        if not isinstance(evidence, list):
            errors.append("checkpoint.evidence must be an array")
        else:
            for index, item in enumerate(evidence):
                errors.extend(evidence_error(item, f"checkpoint.evidence[{index}]"))
                if isinstance(item, dict) and isinstance(item.get("acceptance_ids"), list):
                    unknown_links = [
                        value
                        for value in item["acceptance_ids"]
                        if isinstance(value, str) and value not in ids
                    ]
                    if unknown_links:
                        errors.append(
                            f"checkpoint.evidence[{index}].acceptance_ids has unknown ids: "
                            f"{unknown_links}"
                        )
            latest = latest_evidence_by_acceptance(evidence)
            unsupported_completion = [
                value
                for value in completed_values
                if isinstance(value, str) and not evidence_passes(latest.get(value))
            ]
            if unsupported_completion:
                errors.append(
                    "checkpoint.completed_acceptance lacks latest passing evidence with a known "
                    f"revision: {unsupported_completion}"
                )
        if not isinstance(checkpoint.get("summary"), str):
            errors.append("checkpoint.summary must be a string")
        if not isinstance(checkpoint.get("updated_at"), str):
            errors.append("checkpoint.updated_at must be a string")
    if "pdca" in state:
        if expected_schema != PDCA_LEDGER_SCHEMA_VERSION:
            errors.append("pdca control state requires schema_version 2")
        else:
            errors.extend(
                pdca_state_errors(
                    state["pdca"],
                    acceptance_ids={item["id"] for item in acceptance},
                    contract_sha256=contract.get("sha256") if isinstance(contract, dict) else None,
                    checkpoint=checkpoint if isinstance(checkpoint, dict) else None,
                )
            )
    elif expected_schema == PDCA_LEDGER_SCHEMA_VERSION:
        errors.append("schema_version 2 requires pdca control state")
    for field in ("created_at", "updated_at"):
        if not isinstance(state.get(field), str):
            errors.append(f"{field} must be a string")
    return errors


def require_valid_state(root: Path) -> dict[str, Any]:
    target = harness_dir(root)
    ensure_safe_directory(target, ".harness")
    path = ledger_path(root)
    if path.is_symlink():
        raise LedgerError(f"refusing symlinked ledger: {path}")
    if not path.exists():
        legacy = legacy_candidates(root)
        if legacy:
            locations = ", ".join(str(item) for item in legacy)
            raise LedgerError(
                f"legacy harness state detected at {locations}; run resume --migrate"
            )
    state = read_json(path)
    errors = state_errors(state)
    if not errors and isinstance(state.get("pdca"), dict):
        errors.extend(pdca_artifact_state_errors(root, state))
    if errors:
        raise LedgerError("invalid delivery ledger:\n- " + "\n- ".join(errors))
    return state


def write_json_atomic(path: Path, payload: Any) -> None:
    temporary = path.parent / f".{path.name}.tmp-{os.getpid()}"
    if temporary.exists():
        raise LedgerError(f"refusing existing temporary file: {temporary}")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
        except Exception:
            os.close(descriptor)
            raise
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextmanager
def exclusive_harness_lock(root: Path):
    target = harness_dir(root)
    ensure_safe_directory(target, ".harness")
    if not target.exists():
        require_valid_state(root)
    if _fcntl is None:
        lock_directory = target / ".checkpoint-lock"
        deadline = time.monotonic() + FALLBACK_LOCK_TIMEOUT_SECONDS
        while True:
            try:
                lock_directory.mkdir(mode=0o700)
                break
            except FileExistsError as exc:
                if not os.path.lexists(lock_directory):
                    continue
                if lock_directory.is_symlink() or not lock_directory.is_dir():
                    raise LedgerError(
                        f"checkpoint lock path is not a safe directory: {lock_directory}"
                    ) from exc
                if time.monotonic() >= deadline:
                    raise LedgerError(
                        "timed out waiting for checkpoint lock; if no checkpoint process is "
                        f"running, remove the stale directory {lock_directory}"
                    ) from exc
                time.sleep(FALLBACK_LOCK_RETRY_SECONDS)
        try:
            yield
        finally:
            try:
                lock_directory.rmdir()
            except OSError as exc:
                raise LedgerError(
                    f"checkpoint lock cleanup failed; remove {lock_directory} after confirming "
                    "that no checkpoint process is running"
                ) from exc
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(target, flags)
    try:
        _fcntl.flock(descriptor, _fcntl.LOCK_EX)
        yield
    finally:
        _fcntl.flock(descriptor, _fcntl.LOCK_UN)
        os.close(descriptor)


def create_harness_atomically(root: Path, state: dict[str, Any]) -> None:
    target = harness_dir(root)
    ensure_safe_directory(target, ".harness")
    if target.exists():
        raise LedgerError(f"refusing existing .harness directory: {target}")
    staged = root / f".harness.staged-{os.getpid()}"
    if staged.exists():
        raise LedgerError(f"refusing existing staging directory: {staged}")
    try:
        staged.mkdir(mode=0o700)
        write_json_atomic(staged / "ledger.json", state)
        staged.rename(target)
    finally:
        if staged.exists():
            shutil.rmtree(staged)


def parse_evidence(raw_values: list[str]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_values):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LedgerError(f"--evidence-json #{index + 1} is invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise LedgerError(f"--evidence-json #{index + 1} must be an object")
        item = dict(value)
        item.setdefault("observed_at", utc_now())
        errors = evidence_error(item, f"evidence[{index}]")
        if errors:
            raise LedgerError("; ".join(errors))
        if revision_is_placeholder(item["revision"]):
            raise LedgerError(f"evidence[{index}].revision must be a non-placeholder token")
        output.append(item)
    return output


def handoff_payload(state: dict[str, Any]) -> dict[str, Any]:
    acceptance = state["contract"]["acceptance"]
    checkpoint = state["checkpoint"]
    completed_ids = set(checkpoint["completed_acceptance"])
    completed = [item for item in acceptance if item["id"] in completed_ids]
    pending = [item for item in acceptance if item["id"] not in completed_ids]
    pdca = state.get("pdca")
    pdca_summary = None
    if isinstance(pdca, dict):
        pdca_summary = {
            "status": pdca.get("status"),
            "phase": pdca.get("phase"),
            "cycle": pdca.get("cycle"),
            "do_attempt": pdca.get("do_attempt"),
            "scope": pdca.get("scope"),
            "policy": pdca.get("policy"),
            "event_count": len(pdca.get("events", []))
            if isinstance(pdca.get("events"), list)
            else None,
            "updated_at": pdca.get("updated_at"),
        }
    return {
        "goal": state["goal"],
        "contract_sha256": state["contract"]["sha256"],
        "checkpoint_sequence": checkpoint["sequence"],
        "progress": {"completed": len(completed), "total": len(acceptance)},
        "completed_acceptance": completed,
        "pending_acceptance": pending,
        "completed_steps": checkpoint["completed_steps"],
        "next_steps": checkpoint["next_steps"],
        "open_issues": checkpoint["open_issues"],
        "evidence": checkpoint["evidence"],
        "summary": checkpoint["summary"],
        "updated_at": checkpoint["updated_at"],
        "migration": state.get("migration"),
        "schema_migrations": state.get("schema_migrations", []),
        "pdca": pdca_summary,
    }


def print_handoff(state: dict[str, Any], *, as_json: bool, resume: bool = False) -> None:
    payload = handoff_payload(state)
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    progress = payload["progress"]
    print(f"Goal: {payload['goal']}")
    print(f"Progress: {progress['completed']}/{progress['total']} acceptance items complete")
    print(f"Checkpoint: {payload['checkpoint_sequence']}")
    print(f"Summary: {payload['summary'] or '(none)'}")
    if payload["pdca"]:
        pdca = payload["pdca"]
        print(
            "PDCA: "
            f"{pdca['status']} / {pdca['phase']} "
            f"(cycle {pdca['cycle']}, do attempt {pdca['do_attempt']})"
        )
    if resume:
        completed_ids = [item["id"] for item in payload["completed_acceptance"]]
        print(f"Completed acceptance: {', '.join(completed_ids) if completed_ids else 'none'}")
        print("Pending acceptance:")
        if payload["pending_acceptance"]:
            for item in payload["pending_acceptance"]:
                print(f"- {item['id']}: {item['criterion']}")
        else:
            print("- none")
        print(f"Evidence records: {len(payload['evidence'])}")
        for item in payload["evidence"][-5:]:
            print(
                f"- {item['kind']} {item['result']}: {item['ref']} "
                f"(revision {item['revision']})"
            )
    if payload["open_issues"]:
        print("Open issues:")
        for item in payload["open_issues"]:
            print(f"- {item}")
    if payload["next_steps"]:
        print("Resume steps:" if resume else "Next steps:")
        for item in payload["next_steps"]:
            print(f"- {item}")
    elif resume:
        print("Resume steps: none recorded")


def allowed_legacy_sources(root: Path) -> tuple[Path, Path]:
    return (
        root / ".harness",
        root / ".engineering" / "implementation" / ".harness",
    )


def ensure_source_path_is_safe(root: Path, source: Path) -> None:
    try:
        relative = source.relative_to(root)
    except ValueError as exc:
        raise LedgerError(f"legacy source must be inside project root {root}: {source}") from exc
    cursor = root
    for component in relative.parts:
        cursor = cursor / component
        if cursor.is_symlink():
            raise LedgerError(f"legacy source path must not contain symlinks: {cursor}")
    ensure_safe_directory(source, "legacy source")


def lexical_project_root(value: str, canonical_root: Path) -> Path:
    supplied = Path(os.path.abspath(Path(value).expanduser()))
    if value != ".":
        return supplied
    for candidate in (supplied, *supplied.parents):
        if candidate.resolve() == canonical_root:
            return candidate
    return canonical_root


def resolve_explicit_source_path(
    root: Path,
    explicit: str,
    project_root_value: str = ".",
) -> Path:
    expanded = Path(explicit).expanduser()
    supplied_lexical = Path(os.path.abspath(expanded))
    lexical_root = lexical_project_root(project_root_value, root)
    if supplied_lexical not in allowed_legacy_sources(lexical_root):
        choices = ", ".join(str(path) for path in allowed_legacy_sources(root))
        raise LedgerError(f"--source must resolve exactly to one of: {choices}")
    supplied = expanded.resolve()
    if supplied not in allowed_legacy_sources(root):
        choices = ", ".join(str(path) for path in allowed_legacy_sources(root))
        raise LedgerError(f"--source must resolve exactly to one of: {choices}")
    ensure_source_path_is_safe(root, supplied)
    return supplied


def legacy_candidates(root: Path) -> list[Path]:
    return [
        candidate
        for candidate in allowed_legacy_sources(root)
        if (candidate / "campaign.json").is_file() and (candidate / "features.json").is_file()
    ]


def resolve_legacy_source(
    root: Path,
    explicit: str | None,
    project_root_value: str = ".",
) -> Path:
    if explicit:
        source = resolve_explicit_source_path(root, explicit, project_root_value)
        if not (source / "campaign.json").is_file() or not (source / "features.json").is_file():
            raise LedgerError(
                f"legacy source must contain campaign.json and features.json: {source}"
            )
    else:
        matches = legacy_candidates(root)
        if not matches:
            raise LedgerError("no legacy harness state found; pass --source <legacy-.harness-path>")
        if len(matches) > 1:
            joined = ", ".join(str(path) for path in matches)
            raise LedgerError(f"multiple legacy harness states found ({joined}); pass --source")
        source = matches[0]
        ensure_source_path_is_safe(root, source)
    return source


def legacy_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return dedupe([str(item) for item in value])
    return dedupe([part.strip(" -") for part in re.split(r"[\n;,]+", str(value))])


def parse_legacy_checkpoint(value: Any) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {
        "completed_steps": [],
        "next_steps": [],
        "open_issues": [],
        "evidence": [],
    }
    if isinstance(value, dict):
        result["completed_steps"] = legacy_text_list(value.get("completed_steps"))
        next_step = value.get("next_step") or value.get("next_steps")
        result["next_steps"] = legacy_text_list(next_step)
        result["open_issues"] = legacy_text_list(value.get("open_issues"))
        for ref in legacy_text_list(value.get("tests_run")):
            result["evidence"].append(ref)
        return result
    if not value:
        return result
    for raw_line in str(value).splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if lower.startswith("completed:"):
            result["completed_steps"].extend(legacy_text_list(line.split(":", 1)[1]))
        elif lower.startswith("next:"):
            result["next_steps"].extend(legacy_text_list(line.split(":", 1)[1]))
        elif lower.startswith("issues:"):
            result["open_issues"].extend(legacy_text_list(line.split(":", 1)[1]))
        elif line:
            result["completed_steps"].append(line)
    return result


def load_optional_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = read_json(path)
    if not isinstance(value, dict):
        raise LedgerError(f"legacy file must contain an object: {path}")
    return value


def preflight_legacy(source: Path) -> tuple[str, list[dict[str, Any]], dict[str, Any], str]:
    campaign = read_json(source / "campaign.json")
    features_payload = read_json(source / "features.json")
    if not isinstance(campaign, dict):
        raise LedgerError("legacy campaign.json must contain an object")
    legacy_version = campaign.get("schema_version")
    if legacy_version is not None and legacy_version not in (1, 2):
        raise LedgerError(f"unsupported legacy schema_version: {legacy_version!r}")
    if isinstance(features_payload, list):
        raw_features = features_payload
    elif isinstance(features_payload, dict) and isinstance(features_payload.get("features"), list):
        raw_features = features_payload["features"]
    else:
        raise LedgerError("legacy features.json must contain a features array")
    if not raw_features:
        raise LedgerError("legacy features array is empty")
    goal = str(campaign.get("goal") or "").strip()
    if not goal:
        raise LedgerError("legacy campaign.goal is empty")

    acceptance: list[dict[str, Any]] = []
    statuses: dict[str, str] = {}
    checkpoints: dict[str, dict[str, list[str]]] = {}
    seen: set[str] = set()
    for index, raw in enumerate(raw_features, start=1):
        if not isinstance(raw, dict):
            raise LedgerError(f"legacy features[{index - 1}] must be an object")
        item_id = str(raw.get("id") or f"F{index:03d}").strip()
        if not ID_PATTERN.fullmatch(item_id) or item_id in seen:
            raise LedgerError(f"legacy feature id is invalid or duplicated: {item_id!r}")
        seen.add(item_id)
        title = str(raw.get("name") or raw.get("title") or "").strip()
        description = str(raw.get("description") or "").strip()
        criterion = (
            f"{title} — {description}"
            if title and description and description != title
            else title or description
        )
        if not criterion:
            raise LedgerError(f"legacy feature {item_id} has no name, title, or description")
        entry: dict[str, Any] = {
            "id": item_id,
            "criterion": criterion,
            "checks": legacy_text_list(raw.get("acceptance_checklist")),
        }
        if raw.get("verification") is not None:
            entry["verification"] = raw["verification"]
        acceptance.append(entry)
        statuses[item_id] = str(raw.get("status") or "pending")
        checkpoints[item_id] = parse_legacy_checkpoint(raw.get("checkpoint") or raw.get("checkpoint_notes"))

    summary = load_optional_object(source / "session-summary.json")
    current_contract = load_optional_object(source / "current-contract.json")
    campaign_current = str(campaign.get("current_feature") or "").strip()
    summary_current = str(summary.get("current_feature") or "").strip()
    contract_current = str(current_contract.get("feature_id") or "").strip()
    in_progress = [item_id for item_id, status in statuses.items() if status == "in_progress"]
    if len(in_progress) > 1:
        raise LedgerError(f"legacy state has multiple in-progress features: {in_progress}")
    active_claims = {
        value
        for value in (campaign_current, summary_current, contract_current, *in_progress)
        if value
    }
    if len(active_claims) > 1:
        raise LedgerError(f"legacy active feature references conflict: {sorted(active_claims)}")
    current_id = next(iter(active_claims), "")
    if current_id and current_id not in seen:
        raise LedgerError(f"legacy current feature is unknown: {current_id}")
    active_checkpoint = checkpoints.get(current_id, {
        "completed_steps": [], "next_steps": [], "open_issues": [], "evidence": []
    })
    next_steps = legacy_text_list(summary.get("resume_steps")) or active_checkpoint["next_steps"]
    open_issues = dedupe(
        legacy_text_list(summary.get("open_issues"))
        + legacy_text_list(summary.get("known_failures"))
        + active_checkpoint["open_issues"]
    )
    execution_context = current_contract.get("execution_context")
    if not isinstance(execution_context, dict):
        execution_context = {}
    revision = str(
        campaign.get("last_session_commit")
        or summary.get("last_session_commit")
        or execution_context.get("revision")
        or "unknown"
    )
    migrated_at = utc_now()
    evidence = [
        {
            "kind": "legacy-claim",
            "ref": ref,
            "result": "unknown",
            "observed_at": migrated_at,
            "revision": revision,
            "acceptance_ids": [current_id] if current_id else [],
        }
        for ref in active_checkpoint["evidence"]
    ]
    evidence.extend(
        {
            "kind": "legacy-claim",
            "ref": f"legacy feature {item_id} status=done",
            "result": "unknown",
            "observed_at": migrated_at,
            "revision": revision,
            "acceptance_ids": [item_id],
        }
        for item_id, status in statuses.items()
        if status == "done"
    )
    try:
        sequence = int(campaign.get("session_count") or 0)
    except (TypeError, ValueError) as exc:
        raise LedgerError("legacy campaign.session_count must be an integer") from exc
    if sequence < 0:
        raise LedgerError("legacy campaign.session_count must not be negative")
    checkpoint = {
        "sequence": sequence,
        "completed_acceptance": [],
        "completed_steps": active_checkpoint["completed_steps"],
        "next_steps": next_steps,
        "open_issues": open_issues,
        "evidence": evidence,
        "summary": f"Migrated legacy handoff{f' for {current_id}' if current_id else ''}.",
        "updated_at": migrated_at,
    }
    created_at = str(campaign.get("created") or campaign.get("created_at") or migrated_at)
    return goal, normalize_acceptance(acceptance), checkpoint, created_at


def backup_path(root: Path) -> Path:
    stem = datetime.now(timezone.utc).strftime(".harness-legacy-backup-%Y%m%dT%H%M%SZ")
    candidate = root / stem
    counter = 1
    while candidate.exists():
        candidate = root / f"{stem}-{counter}"
        counter += 1
    return candidate


def source_digest(source: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(source.rglob("*"), key=lambda item: item.relative_to(source).as_posix()):
        if path.is_symlink():
            raise LedgerError(f"legacy source must not contain symlinks: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(source).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def copy_legacy_backup(source: Path, destination: Path) -> None:
    staged = destination.parent / f".{destination.name}.staged-{os.getpid()}"
    if staged.exists() or destination.exists():
        raise LedgerError("refusing existing migration backup or staging directory")
    try:
        shutil.copytree(source, staged)
        staged.rename(destination)
    finally:
        if staged.exists():
            shutil.rmtree(staged)


def replace_root_harness_atomically(root: Path, state: dict[str, Any]) -> None:
    target = harness_dir(root)
    staged = root / f".harness.ledger-staged-{os.getpid()}"
    displaced = root / f".harness.legacy-displaced-{os.getpid()}"
    if staged.exists() or displaced.exists():
        raise LedgerError("refusing existing migration staging directory")
    try:
        staged.mkdir(mode=0o700)
        write_json_atomic(staged / "ledger.json", state)
        target.rename(displaced)
        try:
            staged.rename(target)
        except Exception:
            displaced.rename(target)
            raise
        try:
            shutil.rmtree(displaced)
        except OSError as exc:
            raise LedgerError(
                f"migration activated, but obsolete displaced state remains at {displaced}"
            ) from exc
    finally:
        if staged.exists():
            shutil.rmtree(staged)


def migrate(
    root: Path,
    explicit_source: str | None,
    project_root_value: str = ".",
) -> dict[str, Any]:
    target = harness_dir(root)
    ensure_safe_directory(target, ".harness")
    if explicit_source:
        resolve_explicit_source_path(root, explicit_source, project_root_value)
    if ledger_path(root).exists():
        return require_valid_state(root)
    source = resolve_legacy_source(root, explicit_source, project_root_value)
    if target.exists() and source != target:
        raise LedgerError(
            f"target {target} already exists while legacy source is {source}; refusing to merge directories"
        )
    backup = backup_path(root)
    legacy_digest = source_digest(source)
    try:
        copy_legacy_backup(source, backup)
        if source_digest(backup) != legacy_digest or source_digest(source) != legacy_digest:
            raise LedgerError("legacy state changed while the migration backup was being created")

        goal, acceptance, checkpoint, created_at = preflight_legacy(backup)
        migration = {
            "from": "harness-v1-or-v2",
            "source": str(source.relative_to(root)),
            "backup": str(backup.relative_to(root)),
            "source_sha256": legacy_digest,
            "migrated_at": utc_now(),
            "legacy_files_preserved": sorted(
                path.relative_to(backup).as_posix()
                for path in backup.rglob("*")
                if path.is_file()
            ),
        }
        state = build_state(
            goal,
            acceptance,
            checkpoint=checkpoint,
            migration=migration,
            created_at=created_at,
        )
        errors = state_errors(state)
        if errors:
            raise LedgerError("refusing invalid migrated state:\n- " + "\n- ".join(errors))
        if source_digest(source) != legacy_digest:
            raise LedgerError("legacy state changed after the migration backup was created")
    except Exception:
        if backup.exists():
            shutil.rmtree(backup)
        raise

    try:
        if source == target:
            replace_root_harness_atomically(root, state)
        else:
            create_harness_atomically(root, state)
    except Exception:
        if not ledger_path(root).exists() and backup.exists():
            shutil.rmtree(backup)
        raise
    return state


def pdca_policy(max_cycles: int, max_do_attempts: int) -> dict[str, Any]:
    return {
        "plan": {
            "agent": "harness_planner",
            "reasoning_effort": "ultra",
            "sandbox_mode": "read-only",
        },
        "do": {
            "agent": "harness_implementer",
            "reasoning_effort": "high",
            "sandbox_mode": "workspace-write",
        },
        "check": {
            "agent": "harness_checker",
            "reasoning_effort": "max",
            "sandbox_mode": "read-only",
        },
        "act": "deterministic",
        "max_cycles": max_cycles,
        "max_do_attempts": max_do_attempts,
    }


def require_positive_budget(value: int, label: str) -> int:
    if isinstance(value, bool) or value < 1 or value > 100:
        raise LedgerError(f"{label} must be between 1 and 100")
    return value


def require_expected_sequence(state: dict[str, Any], expected: int) -> None:
    actual = state["checkpoint"]["sequence"]
    if expected != actual:
        raise LedgerError(
            f"stale PDCA write: expected checkpoint sequence {expected}, current is {actual}"
        )


def pdca_artifact(root: Path, path_text: str) -> tuple[Path, str, str]:
    lexical = Path(path_text).expanduser()
    if not lexical.is_absolute():
        lexical = root / lexical
    if os.path.lexists(lexical) and lexical.is_symlink():
        raise LedgerError(f"PDCA artifact must not be a symlink: {lexical}")
    try:
        resolved = lexical.resolve(strict=True)
        relative = resolved.relative_to(root)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise LedgerError("PDCA artifact must be a regular file inside the project root") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise LedgerError(f"PDCA artifact path must not contain symlinks: {current}")
    if not resolved.is_file():
        raise LedgerError(f"PDCA artifact is not a regular file: {resolved}")
    size = resolved.stat().st_size
    if size < 2 or size > 1024 * 1024:
        raise LedgerError("PDCA artifact size must be between 2 bytes and 1 MiB")
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    return resolved, relative.as_posix(), digest


def pdca_artifact_state_errors(root: Path, state: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    pdca = state.get("pdca")
    if not isinstance(pdca, dict) or not isinstance(pdca.get("events"), list):
        return errors
    canonical_events: list[dict[str, Any]] = []
    for index, event in enumerate(pdca["events"]):
        if not isinstance(event, dict) or event.get("phase") not in {"plan", "do", "check"}:
            continue
        prefix = f"pdca.events[{index}]"
        phase = event["phase"]
        reference = event.get("artifact_ref")
        if not isinstance(reference, str) or not reference:
            continue
        try:
            resolved, canonical_reference, digest = pdca_artifact(root, reference)
        except LedgerError as exc:
            errors.append(f"{prefix} artifact is unavailable or unsafe: {exc}")
            continue
        if canonical_reference != reference:
            errors.append(f"{prefix}.artifact_ref is not canonical project-relative form")
        if digest != event.get("artifact_sha256"):
            errors.append(f"{prefix} artifact sha256 does not match recorded content")
        try:
            payload = read_json(resolved)
            if not isinstance(payload, dict):
                raise LedgerError("PDCA artifact must contain a JSON object")
            artifact_context = {
                "scope": pdca["scope"],
                "events": canonical_events,
            }
            if phase == "plan":
                validate_pdca_plan(payload, state, artifact_context)
                projection = {
                    "summary": payload["summary"],
                    "revision": payload["plan_revision"],
                }
            elif phase == "do":
                validate_pdca_do(payload, artifact_context)
                projection = {
                    "summary": payload["summary"],
                    "revision": payload["candidate_revision"],
                    "plan_revision": payload["plan_revision"],
                }
            else:
                validate_pdca_check(payload, artifact_context)
                projection = {
                    "summary": payload["summary"],
                    "revision": payload["candidate_revision"],
                    "plan_revision": payload["plan_revision"],
                    "criteria": payload["criteria"],
                }
        except (LedgerError, UnicodeError) as exc:
            errors.append(f"{prefix} artifact content is invalid: {exc}")
            continue

        mismatched = [
            field for field, expected in projection.items() if event.get(field) != expected
        ]
        if mismatched:
            errors.append(
                f"{prefix} event projection does not match artifact content: {mismatched}"
            )
        canonical_events.append({"phase": phase, **projection})
    return errors


def read_pdca_json_artifact(root: Path, path_text: str) -> tuple[dict[str, Any], str, str]:
    resolved, reference, digest = pdca_artifact(root, path_text)
    payload = read_json(resolved)
    if not isinstance(payload, dict):
        raise LedgerError("PDCA artifact must contain a JSON object")
    return payload, reference, digest


def require_exact_keys(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise LedgerError(f"{label} has unsupported keys: {sorted(unknown)}")


def require_string_list(value: Any, label: str, *, non_empty: bool = True) -> list[str]:
    if (
        not isinstance(value, list)
        or (non_empty and not value)
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        qualifier = "non-empty " if non_empty else ""
        raise LedgerError(f"{label} must be a {qualifier}array of non-empty strings")
    return [item.strip() for item in value]


def require_pdca(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("schema_version") != PDCA_LEDGER_SCHEMA_VERSION:
        raise LedgerError("PDCA is not enabled; run pdca enable explicitly")
    pdca = state.get("pdca")
    if not isinstance(pdca, dict):
        raise LedgerError("schema_version 2 ledger has no pdca control state")
    return pdca


def require_active_pdca(state: dict[str, Any], phase: str) -> dict[str, Any]:
    pdca = require_pdca(state)
    if pdca.get("status") != "active" or pdca.get("phase") != phase:
        raise LedgerError(
            f"PDCA is {pdca.get('status')} / {pdca.get('phase')}; expected active / {phase}"
        )
    return pdca


def append_pdca_event(
    pdca: dict[str, Any],
    *,
    phase: str,
    outcome: str,
    summary: str,
    **extra: Any,
) -> dict[str, Any]:
    event = {
        "sequence": len(pdca["events"]) + 1,
        "phase": phase,
        "cycle": pdca["cycle"],
        "do_attempt": pdca["do_attempt"],
        "outcome": outcome,
        "acceptance_ids": list(pdca["scope"]),
        "summary": summary,
        "observed_at": utc_now(),
        **extra,
    }
    pdca["events"].append(event)
    return event


def touch_pdca_state(state: dict[str, Any]) -> None:
    now = utc_now()
    checkpoint = state["checkpoint"]
    checkpoint["sequence"] += 1
    checkpoint["updated_at"] = now
    state["updated_at"] = now
    state["pdca"]["bound_checkpoint_sequence"] = checkpoint["sequence"]
    state["pdca"]["updated_at"] = now


def validate_pdca_plan(
    payload: dict[str, Any], state: dict[str, Any], pdca: dict[str, Any]
) -> dict[str, Any]:
    require_exact_keys(
        payload,
        {
            "contract_sha256",
            "acceptance_ids",
            "plan_revision",
            "summary",
            "steps",
            "verification",
            "risks",
        },
        "plan artifact",
    )
    if payload.get("contract_sha256") != state["contract"]["sha256"]:
        raise LedgerError("plan artifact contract_sha256 does not match the ledger contract")
    if payload.get("acceptance_ids") != pdca["scope"]:
        raise LedgerError("plan artifact acceptance_ids must exactly match pdca scope")
    revision = str(payload.get("plan_revision") or "").strip()
    if revision_is_placeholder(revision):
        raise LedgerError("plan artifact plan_revision must be a non-placeholder token")
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        raise LedgerError("plan artifact summary must be a non-empty string")
    require_string_list(payload.get("steps"), "plan artifact steps")
    require_string_list(payload.get("verification"), "plan artifact verification")
    require_string_list(payload.get("risks", []), "plan artifact risks", non_empty=False)
    return payload


def validate_pdca_do(payload: dict[str, Any], pdca: dict[str, Any]) -> dict[str, Any]:
    require_exact_keys(
        payload,
        {"plan_revision", "candidate_revision", "summary", "changes", "verification"},
        "do artifact",
    )
    plan_event = next(
        (item for item in reversed(pdca["events"]) if item.get("phase") == "plan"),
        None,
    )
    if not isinstance(plan_event, dict) or payload.get("plan_revision") != plan_event.get("revision"):
        raise LedgerError("do artifact plan_revision does not match the current plan")
    candidate = str(payload.get("candidate_revision") or "").strip()
    if revision_is_placeholder(candidate):
        raise LedgerError("do artifact candidate_revision must be a non-placeholder token")
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        raise LedgerError("do artifact summary must be a non-empty string")
    require_string_list(payload.get("changes"), "do artifact changes")
    verification = payload.get("verification")
    if not isinstance(verification, list) or not verification:
        raise LedgerError("do artifact verification must be a non-empty array")
    for index, item in enumerate(verification):
        if not isinstance(item, dict):
            raise LedgerError(f"do artifact verification[{index}] must be an object")
        require_exact_keys(item, {"ref", "result"}, f"do artifact verification[{index}]")
        for field in ("ref", "result"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise LedgerError(
                    f"do artifact verification[{index}].{field} must be a non-empty string"
                )
    return payload


def validate_pdca_check(payload: dict[str, Any], pdca: dict[str, Any]) -> dict[str, Any]:
    require_exact_keys(
        payload,
        {"plan_revision", "candidate_revision", "summary", "criteria"},
        "check artifact",
    )
    plan_event = next(
        (item for item in reversed(pdca["events"]) if item.get("phase") == "plan"),
        None,
    )
    do_event = next(
        (item for item in reversed(pdca["events"]) if item.get("phase") == "do"),
        None,
    )
    if not isinstance(plan_event, dict) or payload.get("plan_revision") != plan_event.get("revision"):
        raise LedgerError("check artifact plan_revision does not match the current plan")
    if not isinstance(do_event, dict) or payload.get("candidate_revision") != do_event.get("revision"):
        raise LedgerError("check artifact candidate_revision does not match the current Do revision")
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        raise LedgerError("check artifact summary must be a non-empty string")
    criteria = payload.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise LedgerError("check artifact criteria must be a non-empty array")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(criteria):
        if not isinstance(item, dict):
            raise LedgerError(f"check artifact criteria[{index}] must be an object")
        require_exact_keys(
            item,
            {"acceptance_id", "result", "action", "evidence_ref"},
            f"check artifact criteria[{index}]",
        )
        acceptance_id = str(item.get("acceptance_id") or "").strip()
        if acceptance_id in seen:
            raise LedgerError(f"check artifact has duplicate acceptance id: {acceptance_id}")
        seen.add(acceptance_id)
        result = str(item.get("result") or "").strip().lower()
        action = item.get("action")
        if result in PASS_RESULTS:
            if action is not None:
                raise LedgerError(
                    f"passing check {acceptance_id} must use null action"
                )
            result = "pass"
        elif result == "fail":
            if action not in {"fix", "replan", "blocked"}:
                raise LedgerError(
                    f"failing check {acceptance_id} action must be fix, replan, or blocked"
                )
        else:
            raise LedgerError(f"check {acceptance_id} result must be pass, success, or fail")
        evidence_ref = str(item.get("evidence_ref") or "").strip()
        if not evidence_ref:
            raise LedgerError(f"check {acceptance_id} evidence_ref must be non-empty")
        normalized.append(
            {
                "acceptance_id": acceptance_id,
                "result": result,
                "action": action,
                "evidence_ref": evidence_ref,
            }
        )
    if [item["acceptance_id"] for item in normalized] != pdca["scope"]:
        raise LedgerError(
            "check artifact criteria must cover pdca scope exactly once and in contract order"
        )
    payload["criteria"] = normalized
    return payload


def pdca_output(state: dict[str, Any], *, as_json: bool) -> None:
    pdca = state["pdca"]
    payload = {
        "checkpoint_sequence": state["checkpoint"]["sequence"],
        "contract_sha256": state["contract"]["sha256"],
        "status": pdca["status"],
        "phase": pdca["phase"],
        "cycle": pdca["cycle"],
        "do_attempt": pdca["do_attempt"],
        "scope": pdca["scope"],
        "policy": pdca["policy"],
        "event_count": len(pdca["events"]),
        "last_event": pdca["events"][-1] if pdca["events"] else None,
        "updated_at": pdca["updated_at"],
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            f"PDCA: {payload['status']} / {payload['phase']} "
            f"(cycle {payload['cycle']}, do attempt {payload['do_attempt']})"
        )
        print(f"Checkpoint sequence: {payload['checkpoint_sequence']}")
        print(f"Scope: {', '.join(payload['scope'])}")


def validate_and_write_pdca(root: Path, state: dict[str, Any]) -> None:
    errors = state_errors(state, expected_schema=PDCA_LEDGER_SCHEMA_VERSION)
    if not errors:
        errors.extend(pdca_artifact_state_errors(root, state))
    if errors:
        raise LedgerError("refusing invalid PDCA state:\n- " + "\n- ".join(errors))
    write_json_atomic(ledger_path(root), state)


def cmd_pdca_enable(args: argparse.Namespace) -> int:
    root = project_root(args.project_root)
    max_cycles = require_positive_budget(args.max_cycles, "--max-cycles")
    max_attempts = require_positive_budget(args.max_do_attempts, "--max-do-attempts")
    with exclusive_harness_lock(root):
        state = require_valid_state(root)
        require_expected_sequence(state, args.expect_sequence)
        if state["schema_version"] != SCHEMA_VERSION or "pdca" in state:
            raise LedgerError("PDCA is already enabled or this ledger is not schema version 1")
        completed = set(state["checkpoint"]["completed_acceptance"])
        scope = [
            item["id"] for item in state["contract"]["acceptance"] if item["id"] not in completed
        ]
        if not scope:
            raise LedgerError("all acceptance criteria are already complete")
        backup = backup_path(root)
        source_hash = source_digest(harness_dir(root))
        copy_legacy_backup(harness_dir(root), backup)
        if source_digest(backup) != source_hash:
            shutil.rmtree(backup)
            raise LedgerError("PDCA enable backup does not match the source ledger")
        policy = pdca_policy(max_cycles, max_attempts)
        now = utc_now()
        state["schema_version"] = PDCA_LEDGER_SCHEMA_VERSION
        state["pdca"] = {
            "schema_version": PDCA_SCHEMA_VERSION,
            "contract_sha256": state["contract"]["sha256"],
            "policy": policy,
            "policy_sha256": hashlib.sha256(canonical_json(policy).encode("utf-8")).hexdigest(),
            "status": "active",
            "phase": "plan",
            "cycle": 1,
            "do_attempt": 0,
            "scope": scope,
            "events": [],
            "bound_checkpoint_sequence": state["checkpoint"]["sequence"],
            "updated_at": now,
        }
        state.setdefault("schema_migrations", []).append(
            {
                "from": SCHEMA_VERSION,
                "to": PDCA_LEDGER_SCHEMA_VERSION,
                "backup": str(backup.relative_to(root)),
                "source_sha256": source_hash,
                "migrated_at": now,
                "reason": "explicit-pdca-enable",
            }
        )
        touch_pdca_state(state)
        try:
            validate_and_write_pdca(root, state)
        except Exception:
            if backup.exists():
                shutil.rmtree(backup)
            raise
    pdca_output(state, as_json=args.json)
    return 0


def cmd_pdca_status(args: argparse.Namespace) -> int:
    root = project_root(args.project_root)
    state = require_valid_state(root)
    require_pdca(state)
    pdca_output(state, as_json=args.json)
    return 0


def cmd_pdca_record_plan(args: argparse.Namespace) -> int:
    root = project_root(args.project_root)
    payload, reference, digest = read_pdca_json_artifact(root, args.artifact_file)
    with exclusive_harness_lock(root):
        state = require_valid_state(root)
        require_expected_sequence(state, args.expect_sequence)
        pdca = require_active_pdca(state, "plan")
        validate_pdca_plan(payload, state, pdca)
        append_pdca_event(
            pdca,
            phase="plan",
            outcome="ready",
            summary=payload["summary"],
            artifact_ref=reference,
            artifact_sha256=digest,
            revision=payload["plan_revision"],
        )
        pdca["phase"] = "do"
        pdca["do_attempt"] = 0
        touch_pdca_state(state)
        validate_and_write_pdca(root, state)
    pdca_output(state, as_json=args.json)
    return 0


def cmd_pdca_record_do(args: argparse.Namespace) -> int:
    root = project_root(args.project_root)
    payload, reference, digest = read_pdca_json_artifact(root, args.artifact_file)
    with exclusive_harness_lock(root):
        state = require_valid_state(root)
        require_expected_sequence(state, args.expect_sequence)
        pdca = require_active_pdca(state, "do")
        if pdca["do_attempt"] >= pdca["policy"]["max_do_attempts"]:
            raise LedgerError("Do attempt budget is exhausted; run pdca act after a Check")
        validate_pdca_do(payload, pdca)
        pdca["do_attempt"] += 1
        append_pdca_event(
            pdca,
            phase="do",
            outcome="ready",
            summary=payload["summary"],
            artifact_ref=reference,
            artifact_sha256=digest,
            revision=payload["candidate_revision"],
            plan_revision=payload["plan_revision"],
        )
        pdca["phase"] = "check"
        touch_pdca_state(state)
        validate_and_write_pdca(root, state)
    pdca_output(state, as_json=args.json)
    return 0


def cmd_pdca_record_check(args: argparse.Namespace) -> int:
    root = project_root(args.project_root)
    payload, reference, digest = read_pdca_json_artifact(root, args.artifact_file)
    with exclusive_harness_lock(root):
        state = require_valid_state(root)
        require_expected_sequence(state, args.expect_sequence)
        pdca = require_active_pdca(state, "check")
        validate_pdca_check(payload, pdca)
        append_pdca_event(
            pdca,
            phase="check",
            outcome="recorded",
            summary=payload["summary"],
            artifact_ref=reference,
            artifact_sha256=digest,
            revision=payload["candidate_revision"],
            plan_revision=payload["plan_revision"],
            criteria=payload["criteria"],
        )
        pdca["phase"] = "act"
        touch_pdca_state(state)
        validate_and_write_pdca(root, state)
    pdca_output(state, as_json=args.json)
    return 0


def cmd_pdca_act(args: argparse.Namespace) -> int:
    root = project_root(args.project_root)
    with exclusive_harness_lock(root):
        state = require_valid_state(root)
        require_expected_sequence(state, args.expect_sequence)
        pdca = require_active_pdca(state, "act")
        check_event = pdca["events"][-1] if pdca["events"] else None
        if not isinstance(check_event, dict) or check_event.get("phase") != "check":
            raise LedgerError("PDCA Act requires the latest event to be Check")
        criteria = check_event.get("criteria", [])
        actions = [item.get("action") for item in criteria if item.get("result") == "fail"]
        reasons: list[str] = []
        if not actions:
            decision = "complete"
        elif "blocked" in actions:
            decision = "blocked"
            reasons.append("check-blocked")
        elif "replan" in actions:
            if pdca["cycle"] >= pdca["policy"]["max_cycles"]:
                decision = "blocked"
                reasons.append("cycle-budget-exhausted")
            else:
                decision = "replan"
        else:
            if pdca["do_attempt"] >= pdca["policy"]["max_do_attempts"]:
                decision = "blocked"
                reasons.append("do-attempt-budget-exhausted")
            else:
                decision = "fix"

        append_pdca_event(
            pdca,
            phase="act",
            outcome=decision,
            summary=("Deterministic Act: " + decision),
            decision=decision,
            reason_codes=reasons,
        )

        if decision == "complete":
            evidence = {
                "kind": "pdca-check",
                "ref": check_event["artifact_ref"],
                "result": "pass",
                "observed_at": utc_now(),
                "revision": check_event["revision"],
                "acceptance_ids": list(pdca["scope"]),
            }
            checkpoint = state["checkpoint"]
            checkpoint["evidence"].append(evidence)
            checkpoint["completed_acceptance"] = dedupe(
                checkpoint["completed_acceptance"] + pdca["scope"]
            )
            checkpoint["completed_steps"] = dedupe(
                checkpoint["completed_steps"]
                + [
                    f"PDCA Check accepted cycle {pdca['cycle']} revision "
                    f"{check_event['revision']}"
                ]
            )
            checkpoint["next_steps"] = []
            checkpoint["summary"] = check_event["summary"]
            pdca["status"] = "complete"
        elif decision == "fix":
            pdca["phase"] = "do"
        elif decision == "replan":
            pdca["cycle"] += 1
            pdca["do_attempt"] = 0
            pdca["phase"] = "plan"
        else:
            pdca["status"] = "blocked"
        touch_pdca_state(state)
        validate_and_write_pdca(root, state)
    pdca_output(state, as_json=args.json)
    return 0


def cmd_pdca_block(args: argparse.Namespace) -> int:
    root = project_root(args.project_root)
    with exclusive_harness_lock(root):
        state = require_valid_state(root)
        require_expected_sequence(state, args.expect_sequence)
        pdca = require_pdca(state)
        if pdca["status"] != "active":
            raise LedgerError("only an active PDCA run can be blocked")
        append_pdca_event(
            pdca,
            phase="act",
            outcome="blocked",
            summary=args.reason.strip(),
            decision="blocked",
            reason_codes=[args.code.strip()],
        )
        pdca["status"] = "blocked"
        touch_pdca_state(state)
        validate_and_write_pdca(root, state)
    pdca_output(state, as_json=args.json)
    return 0


def cmd_pdca_restart(args: argparse.Namespace) -> int:
    root = project_root(args.project_root)
    with exclusive_harness_lock(root):
        state = require_valid_state(root)
        require_expected_sequence(state, args.expect_sequence)
        pdca = require_pdca(state)
        if pdca["status"] != "blocked":
            raise LedgerError("pdca restart requires blocked state")
        if args.max_cycles is not None:
            new_max = require_positive_budget(args.max_cycles, "--max-cycles")
            if new_max < pdca["policy"]["max_cycles"]:
                raise LedgerError("--max-cycles cannot reduce the existing budget")
            pdca["policy"]["max_cycles"] = new_max
        if pdca["cycle"] >= pdca["policy"]["max_cycles"]:
            raise LedgerError("restart requires an explicit higher --max-cycles budget")
        append_pdca_event(
            pdca,
            phase="act",
            outcome="restart",
            summary=args.reason.strip(),
            decision="restart",
            reason_codes=["user-authorized-restart"],
        )
        pdca["cycle"] += 1
        pdca["do_attempt"] = 0
        pdca["phase"] = "plan"
        pdca["status"] = "active"
        pdca["policy_sha256"] = hashlib.sha256(
            canonical_json(pdca["policy"]).encode("utf-8")
        ).hexdigest()
        touch_pdca_state(state)
        validate_and_write_pdca(root, state)
    pdca_output(state, as_json=args.json)
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    root = project_root(args.project_root)
    legacy = legacy_candidates(root)
    if legacy:
        locations = ", ".join(str(item) for item in legacy)
        raise LedgerError(
            f"legacy harness state detected at {locations}; run resume --migrate"
        )
    goal = args.goal.strip()
    if not goal:
        raise LedgerError("--goal must not be empty")
    acceptance = normalize_contract_file(args.contract_file, goal)
    state = build_state(goal, acceptance)
    errors = state_errors(state)
    if errors:
        raise LedgerError("refusing invalid initial state:\n- " + "\n- ".join(errors))
    create_harness_atomically(root, state)
    print_handoff(state, as_json=args.json)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = project_root(args.project_root)
    print_handoff(require_valid_state(root), as_json=args.json)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    root = project_root(args.project_root)
    state = require_valid_state(root)
    payload = {
        "ok": True,
        "schema_version": state["schema_version"],
        "contract_sha256": state["contract"]["sha256"],
        "file": ".harness/ledger.json",
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("Delivery ledger is valid.")
    return 0


def cmd_checkpoint(args: argparse.Namespace) -> int:
    root = project_root(args.project_root)
    evidence = parse_evidence(args.evidence_json)
    if args.complete and not evidence:
        raise LedgerError("--complete requires at least one new --evidence-json object")
    changed = any(
        (
            args.complete,
            args.completed_step,
            args.next_step,
            args.open_issue,
            args.evidence_json,
            args.summary is not None,
            args.clear_next_steps,
            args.clear_open_issues,
        )
    )
    if not changed:
        raise LedgerError("checkpoint requires at least one field to record")

    with exclusive_harness_lock(root):
        state = require_valid_state(root)
        contract_before = canonical_json(state["contract"])
        checkpoint = state["checkpoint"]
        pdca = state.get("pdca")
        if isinstance(pdca, dict):
            if args.complete:
                raise LedgerError(
                    "acceptance completion is controlled by deterministic PDCA Act; "
                    "checkpoint --complete is disabled while pdca state exists"
                )
            linked_evidence = [
                item for item in evidence if isinstance(item.get("acceptance_ids"), list)
            ]
            if linked_evidence:
                raise LedgerError(
                    "acceptance-linked evidence is controlled by PDCA Check/Act while "
                    "pdca state exists"
                )
        acceptance_ids = {item["id"] for item in state["contract"]["acceptance"]}
        unknown = [item for item in args.complete if item not in acceptance_ids]
        if unknown:
            raise LedgerError(f"unknown acceptance ids: {unknown}")
        for item in evidence:
            linked = item.get("acceptance_ids")
            if linked is None and len(args.complete) == 1:
                linked = [args.complete[0]]
                item["acceptance_ids"] = linked
            if linked is not None:
                unknown_links = [value for value in linked if value not in acceptance_ids]
                if unknown_links:
                    raise LedgerError(f"evidence references unknown acceptance ids: {unknown_links}")
        if args.complete:
            new_latest = latest_evidence_by_acceptance(evidence)
            missing_links = [
                value for value in args.complete if not evidence_passes(new_latest.get(value))
            ]
            if missing_links:
                raise LedgerError(
                    "latest new passing evidence with a known revision must cover every "
                    f"completed acceptance id: {missing_links}"
                )

        checkpoint["evidence"].extend(evidence)
        completed = dedupe(checkpoint["completed_acceptance"] + args.complete)
        latest = latest_evidence_by_acceptance(checkpoint["evidence"])
        checkpoint["completed_acceptance"] = [
            acceptance_id
            for acceptance_id in completed
            if evidence_passes(latest.get(acceptance_id))
        ]
        checkpoint["completed_steps"] = dedupe(
            checkpoint["completed_steps"] + args.completed_step
        )
        if args.clear_next_steps:
            checkpoint["next_steps"] = []
        if args.next_step:
            checkpoint["next_steps"] = dedupe(args.next_step)
        if args.clear_open_issues:
            checkpoint["open_issues"] = []
        if args.open_issue:
            checkpoint["open_issues"] = dedupe(
                checkpoint["open_issues"] + args.open_issue
            )
        if args.summary is not None:
            checkpoint["summary"] = args.summary.strip()
        checkpoint["sequence"] += 1
        checkpoint["updated_at"] = utc_now()
        state["updated_at"] = checkpoint["updated_at"]
        if isinstance(pdca, dict):
            pdca["bound_checkpoint_sequence"] = checkpoint["sequence"]
            pdca["updated_at"] = checkpoint["updated_at"]
        if canonical_json(state["contract"]) != contract_before:
            raise LedgerError("internal error: checkpoint attempted to mutate the contract")
        errors = state_errors(state)
        if errors:
            raise LedgerError("refusing invalid checkpoint:\n- " + "\n- ".join(errors))
        write_json_atomic(ledger_path(root), state)
    print_handoff(state, as_json=args.json)
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    root = project_root(args.project_root)
    if args.source and not args.migrate:
        raise LedgerError("--source is valid only with --migrate")
    state = (
        migrate(root, args.source, args.project_root)
        if args.migrate
        else require_valid_state(root)
    )
    print_handoff(state, as_json=args.json, resume=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    init = subcommands.add_parser("init", help="create an immutable acceptance ledger")
    init.add_argument("--project-root", default=".")
    init.add_argument("--goal", required=True)
    init.add_argument("--contract-file", required=True, help="JSON path or '-' for stdin")
    init.add_argument("--json", action="store_true")
    init.set_defaults(handler=cmd_init)

    status = subcommands.add_parser("status", help="print a read-only progress snapshot")
    status.add_argument("--project-root", default=".")
    status.add_argument("--json", action="store_true")
    status.set_defaults(handler=cmd_status)

    checkpoint = subcommands.add_parser("checkpoint", help="atomically record one handoff snapshot")
    checkpoint.add_argument("--project-root", default=".")
    checkpoint.add_argument("--complete", action="append", default=[], metavar="ID")
    checkpoint.add_argument("--completed-step", action="append", default=[], metavar="TEXT")
    checkpoint.add_argument("--next-step", action="append", default=[], metavar="TEXT")
    checkpoint.add_argument("--open-issue", action="append", default=[], metavar="TEXT")
    checkpoint.add_argument("--evidence-json", action="append", default=[], metavar="JSON")
    checkpoint.add_argument("--summary")
    checkpoint.add_argument("--clear-next-steps", action="store_true")
    checkpoint.add_argument("--clear-open-issues", action="store_true")
    checkpoint.add_argument("--json", action="store_true")
    checkpoint.set_defaults(handler=cmd_checkpoint)

    validate = subcommands.add_parser("validate", help="verify schema and contract integrity")
    validate.add_argument("--project-root", default=".")
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(handler=cmd_validate)

    resume = subcommands.add_parser("resume", help="print the compact read-only handoff")
    resume.add_argument("--project-root", default=".")
    resume.add_argument("--migrate", action="store_true", help="explicitly migrate legacy state")
    resume.add_argument("--source", help="legacy .harness path; requires --migrate")
    resume.add_argument("--json", action="store_true")
    resume.set_defaults(handler=cmd_resume)

    pdca = subcommands.add_parser(
        "pdca", help="advance the unified Codex-native Plan/Do/Check/Act loop"
    )
    pdca_commands = pdca.add_subparsers(dest="pdca_command", required=True)

    pdca_enable = pdca_commands.add_parser(
        "enable", help="enter fail-closed Plan/Do/Check/Act state from a bootstrap ledger"
    )
    pdca_enable.add_argument("--project-root", default=".")
    pdca_enable.add_argument("--expect-sequence", required=True, type=int)
    pdca_enable.add_argument("--max-cycles", type=int, default=3)
    pdca_enable.add_argument("--max-do-attempts", type=int, default=3)
    pdca_enable.add_argument("--json", action="store_true")
    pdca_enable.set_defaults(handler=cmd_pdca_enable)

    pdca_status = pdca_commands.add_parser("status", help="print read-only PDCA state")
    pdca_status.add_argument("--project-root", default=".")
    pdca_status.add_argument("--json", action="store_true")
    pdca_status.set_defaults(handler=cmd_pdca_status)

    for name, handler, help_text in (
        ("record-plan", cmd_pdca_record_plan, "record a Plan artifact and open Do"),
        ("record-do", cmd_pdca_record_do, "record a Do artifact and open Check"),
        ("record-check", cmd_pdca_record_check, "record an exhaustive Check artifact"),
    ):
        command = pdca_commands.add_parser(name, help=help_text)
        command.add_argument("--project-root", default=".")
        command.add_argument("--expect-sequence", required=True, type=int)
        command.add_argument("--artifact-file", required=True)
        command.add_argument("--json", action="store_true")
        command.set_defaults(handler=handler)

    pdca_act = pdca_commands.add_parser(
        "act", help="apply the deterministic transition derived from the latest Check"
    )
    pdca_act.add_argument("--project-root", default=".")
    pdca_act.add_argument("--expect-sequence", required=True, type=int)
    pdca_act.add_argument("--json", action="store_true")
    pdca_act.set_defaults(handler=cmd_pdca_act)

    pdca_block = pdca_commands.add_parser(
        "block", help="record a real blocker without letting a model pick the next phase"
    )
    pdca_block.add_argument("--project-root", default=".")
    pdca_block.add_argument("--expect-sequence", required=True, type=int)
    pdca_block.add_argument("--code", required=True)
    pdca_block.add_argument("--reason", required=True)
    pdca_block.add_argument("--json", action="store_true")
    pdca_block.set_defaults(handler=cmd_pdca_block)

    pdca_restart = pdca_commands.add_parser(
        "restart", help="restart a blocked run at Plan with explicit authorization"
    )
    pdca_restart.add_argument("--project-root", default=".")
    pdca_restart.add_argument("--expect-sequence", required=True, type=int)
    pdca_restart.add_argument("--reason", required=True)
    pdca_restart.add_argument("--max-cycles", type=int)
    pdca_restart.add_argument("--json", action="store_true")
    pdca_restart.set_defaults(handler=cmd_pdca_restart)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.handler(args))
    except (LedgerError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
