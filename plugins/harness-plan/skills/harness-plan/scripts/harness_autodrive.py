#!/usr/bin/env python3
"""Autodrive controller for harness-plan campaigns.

Subcommands:
  --decide          Stop-hook entry. Reads state, spawns the next session if needed.
  --enable          Turn autodrive on (creates .harness/autodrive.json).
  --disable         Flip enabled=false (keeps history; chain will stop).
  --status          Print current autodrive state.
  --reset           Delete autodrive.json and any fail marker (full off).
  --fail --reason   Touch fail marker so the next Stop-hook tick aborts.

State file: .harness/autodrive.json
  {
    "enabled": bool,
    "max_iterations": int,
    "iteration": int,
    "phase": "feature" | "review" | "done",
    "started_at": iso8601,
    "last_spawn_at": iso8601,
    "last_feature_id": str | null,
    "campaign_base_commit": str | null,
    "claude_binary": str | null,           # resolved at --enable time
    "last_progress_counts": {"done": int, "total": int} | null,
    "stall_count": int                     # consecutive ticks with no `done` progress
  }

Failure marker: .harness/autodrive.fail (presence => Stop hook bails)
Log:            .harness/autodrive.log (append-only)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Reuse harness_lib helpers so timestamp / IO conventions stay consistent.
SCRIPTS_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = Path(__file__).resolve()
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from harness_lib import utc_now  # type: ignore  # noqa: E402

DEFAULT_MAX_ITERATIONS = 20
STALL_LIMIT = 2  # consecutive decide ticks with no progress → fail marker


def harness_dir(project_root: Path) -> Path:
    return project_root / ".harness"


def state_path(project_root: Path) -> Path:
    return harness_dir(project_root) / "autodrive.json"


def fail_path(project_root: Path) -> Path:
    return harness_dir(project_root) / "autodrive.fail"


def log_path(project_root: Path) -> Path:
    return harness_dir(project_root) / "autodrive.log"


def append_log(project_root: Path, message: str) -> None:
    log_path(project_root).parent.mkdir(parents=True, exist_ok=True)
    with log_path(project_root).open("a", encoding="utf-8") as fh:
        fh.write(f"[{utc_now()}] {message}\n")


def load_state(project_root: Path) -> dict | None:
    p = state_path(project_root)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        append_log(project_root, f"ERROR loading autodrive.json: {exc}")
        return None


def save_state(project_root: Path, state: dict) -> None:
    p = state_path(project_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def load_summary(project_root: Path) -> dict | None:
    p = harness_dir(project_root) / "session-summary.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_features(project_root: Path) -> list[dict]:
    p = harness_dir(project_root) / "features.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("features"), list):
            return data["features"]
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def all_features_terminal(features: list[dict]) -> bool:
    """True iff no feature is in `pending`, `in_progress`, `backlog`, or `blocked`."""
    if not features:
        return False
    open_states = {"pending", "in_progress", "backlog", "blocked"}
    return not any((f.get("status") or "backlog") in open_states for f in features)


def git_head_commit(project_root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(project_root),
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


def find_git_root(start: Path) -> Path | None:
    """Walk upward from `start` to find a directory containing `.git/`.

    Returns None if no repo root is found within 20 parents.
    """
    current = start.resolve()
    for _ in range(20):
        if (current / ".git").exists():
            return current
        if current.parent == current:
            return None
        current = current.parent
    return None


# ---------- subcommand: enable / disable / status / reset / fail ----------

def cmd_enable(project_root: Path, max_iterations: int) -> int:
    existing = load_state(project_root) or {}
    # Persist the resolved claude binary at enable time, while the user's full
    # PATH (volta/asdf/nvm/bun/etc.) is still in scope. The Stop hook spawns
    # may run with a stripped PATH where shutil.which fails.
    binary = find_claude_binary() or existing.get("claude_binary")
    state = {
        "enabled": True,
        "max_iterations": max_iterations or existing.get("max_iterations") or DEFAULT_MAX_ITERATIONS,
        "iteration": existing.get("iteration", 0),
        "phase": existing.get("phase", "feature"),
        "started_at": existing.get("started_at") or utc_now(),
        "last_spawn_at": existing.get("last_spawn_at"),
        "last_feature_id": existing.get("last_feature_id"),
        "campaign_base_commit": existing.get("campaign_base_commit") or git_head_commit(project_root),
        "claude_binary": binary,
        "last_progress_counts": existing.get("last_progress_counts"),
        "stall_count": existing.get("stall_count", 0),
    }
    save_state(project_root, state)
    # Clear stale fail marker on explicit re-enable.
    fp = fail_path(project_root)
    if fp.exists():
        fp.unlink()
    append_log(project_root, f"autodrive enabled (max_iterations={state['max_iterations']}, claude_binary={binary})")
    print(json.dumps(state, indent=2))
    return 0


def cmd_disable(project_root: Path) -> int:
    state = load_state(project_root)
    if not state:
        print("autodrive not configured")
        return 0
    state["enabled"] = False
    save_state(project_root, state)
    append_log(project_root, "autodrive disabled")
    print(json.dumps(state, indent=2))
    return 0


def cmd_status(project_root: Path) -> int:
    state = load_state(project_root)
    if not state:
        print(json.dumps({"enabled": False, "configured": False}, indent=2))
        return 0
    state_view = dict(state)
    state_view["fail_marker"] = fail_path(project_root).exists()
    print(json.dumps(state_view, indent=2))
    return 0


def cmd_reset(project_root: Path) -> int:
    sp = state_path(project_root)
    fp = fail_path(project_root)
    removed = []
    if sp.exists():
        sp.unlink()
        removed.append("autodrive.json")
    if fp.exists():
        fp.unlink()
        removed.append("autodrive.fail")
    append_log(project_root, f"autodrive reset (removed: {', '.join(removed) or 'nothing'})")
    print(json.dumps({"removed": removed}, indent=2))
    return 0


def cmd_fail(project_root: Path, reason: str) -> int:
    fp = fail_path(project_root)
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(f"{utc_now()}\n{reason}\n", encoding="utf-8")
    append_log(project_root, f"FAIL marker set: {reason}")
    print(json.dumps({"fail_marker": True, "reason": reason}, indent=2))
    return 0


# ---------- subcommand: decide (Stop-hook entry) ----------

REVIEW_PROMPT = f"""The harness-plan campaign just finished all features. You are in a dedicated final-review session. Do exactly the following, then end:

1. Run the /security-review skill against the diff between HEAD and the commit recorded at `.harness/autodrive.json` -> `campaign_base_commit`. If that field is missing, compare against `origin/HEAD` or just the campaign's first commit reachable via `git log --grep='harness'`.

2. Use the Agent tool to launch four parallel general-purpose subagents. Each receives:
   - the campaign goal (read .harness/campaign.json)
   - the diff range from step 1
   - the role described below
   Each returns < 200 words.
     a. Testability reviewer: are tests meaningful and do they cover edge cases the campaign goal implies?
     b. Maintainability reviewer: naming, structure, comments, future-friendliness.
     c. Performance reviewer: hot paths, unnecessary allocations, repeated work.
     d. Design-consistency reviewer: do the changes match existing repo conventions, or do they introduce orphan abstractions?

3. Write `.harness/review-report.md` with five sections: Security (from /security-review), Testability, Maintainability, Performance, Design Consistency. Each section is the agent's findings verbatim. At the bottom add a 3-line "Top fixes" list synthesized across all five.

4. Commit the report:
   git add .harness/review-report.md
   git commit -m "chore(harness): autodrive review report"

5. Mark the review phase done by running:
   python3 {SCRIPT_PATH} --project-root . --mark-review-done

6. End your response. Don't pick another feature, don't ask questions — the user is not present.

If anything in steps 1-4 fails irrecoverably, run:
   python3 {SCRIPT_PATH} --project-root . --fail --reason "review session: <short reason>"
then end."""

CONTINUE_PROMPT = f"""You are resuming a harness-plan campaign in AUTODRIVE mode. A human is NOT present.

Read `.harness/autodrive.json` and `.harness/session-summary.json` to confirm state, then:

1. Use the `harness-plan` skill to resume the active campaign. Pick the next pending feature and implement it.
2. When that ONE feature transitions to `done`:
     git add -u
     git add .harness/
     git commit -m "feat(harness): complete F0XX - <feature title>"
   then end your response immediately. Do NOT pick a second feature in this session — the Stop hook will spawn the next.
3. Never call AskUserQuestion. If you are genuinely blocked (3 self-test retries hit, unresolvable state, missing context), instead run:
     python3 {SCRIPT_PATH} --project-root . --fail --reason "<short reason>"
   then end your response.
4. Never run destructive scripts (harness_reset, archive, force-push)."""


def find_claude_binary() -> str | None:
    explicit = os.environ.get("CLAUDE_BINARY")
    if explicit and Path(explicit).exists():
        return explicit
    found = shutil.which("claude")
    if found:
        return found
    # Probe common install locations. Stop hook subprocess may run with a
    # stripped PATH (volta/asdf/nvm/bun/homebrew often missing under GUI launches),
    # so check the canonical install dirs explicitly.
    home = Path.home()
    candidates = [
        home / ".local/bin/claude",
        home / ".claude/local/claude",
        home / ".bun/bin/claude",
        home / ".volta/bin/claude",
        home / ".asdf/shims/claude",
        Path("/usr/local/bin/claude"),
        Path("/opt/homebrew/bin/claude"),
    ]
    # nvm: scan node version dirs
    nvm_dir = Path(os.environ.get("NVM_DIR") or (home / ".nvm"))
    nvm_versions = nvm_dir / "versions/node"
    if nvm_versions.exists():
        try:
            for ver in nvm_versions.iterdir():
                candidates.append(ver / "bin/claude")
        except Exception:
            pass
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def resolve_claude_binary(state: dict | None) -> str | None:
    """Prefer the binary persisted at --enable time; fall back to discovery."""
    if state:
        cached = state.get("claude_binary")
        if cached and Path(cached).exists():
            return cached
    return find_claude_binary()


def spawn_claude(project_root: Path, prompt: str, state: dict | None = None) -> bool:
    """Detach a `claude -p <prompt>` process. Returns True on successful fork.

    Output goes to .harness/autodrive.log. The new process is detached via
    Popen(start_new_session=True), which calls setsid(2) so it survives the
    parent's exit independent of any shell.

    cwd is set to the git repo root when one can be located, so the spawned
    session loads project-level .claude/settings.json and plugin scopes the
    same way an interactive `cd <repo> && claude` invocation would. The
    harness root (where .harness/ lives) is added back via --add-dir so the
    spawned session can still write to the campaign directory.
    """
    binary = resolve_claude_binary(state)
    if not binary:
        append_log(project_root, "ERROR: cannot find `claude` binary on PATH; chain stopped")
        fail_path(project_root).write_text(f"{utc_now()}\nclaude binary not found\n", encoding="utf-8")
        return False

    log = log_path(project_root)
    log.parent.mkdir(parents=True, exist_ok=True)

    repo_root = find_git_root(project_root)
    spawn_cwd = repo_root if repo_root else project_root
    cmd = [binary, "--dangerously-skip-permissions"]
    if repo_root and repo_root != project_root:
        cmd += ["--add-dir", str(project_root)]
    cmd += ["-p", prompt]

    try:
        log_fh = open(log, "a", encoding="utf-8")
    except Exception as exc:
        append_log(project_root, f"ERROR opening autodrive.log for spawn: {exc}")
        return False

    try:
        subprocess.Popen(
            cmd,
            cwd=str(spawn_cwd),
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=log_fh,
            start_new_session=True,
            close_fds=True,
        )
        append_log(project_root, f"spawn: cwd={spawn_cwd} binary={binary}")
        return True
    except Exception as exc:
        append_log(project_root, f"ERROR spawning claude: {exc}")
        return False
    finally:
        # Popen dups the fd; we can close our handle on the parent side.
        try:
            log_fh.close()
        except Exception:
            pass


def _progress_done(counts: dict, features: list[dict]) -> int:
    """Extract the 'completed' count from summary.progress_counts, with fallbacks."""
    for key in ("done", "completed"):
        v = counts.get(key)
        if isinstance(v, int):
            return v
    return sum(1 for f in features if (f.get("status") or "") in ("done", "skipped"))


def cmd_decide(project_root: Path) -> int:
    """Stop-hook entry. Always exits 0; logs whatever it does."""
    state = load_state(project_root)
    if not state:
        return 0  # autodrive not configured; nothing to do.
    if not state.get("enabled"):
        append_log(project_root, "decide: skipped — autodrive disabled")
        return 0

    if fail_path(project_root).exists():
        append_log(project_root, "decide: skipped — fail marker present")
        return 0

    phase = state.get("phase", "feature")
    if phase == "done":
        append_log(project_root, "decide: skipped — phase=done")
        return 0

    iteration = int(state.get("iteration", 0))
    max_iters = int(state.get("max_iterations", DEFAULT_MAX_ITERATIONS))
    if iteration >= max_iters:
        append_log(project_root, f"decide: STOP — hit max_iterations ({max_iters})")
        state["phase"] = "done"
        save_state(project_root, state)
        return 0

    if phase == "review":
        # If we're in review phase and a session just ended, the review is complete.
        # mark-review-done normally sets phase=done. Belt-and-suspenders here.
        append_log(project_root, "decide: review session ended — marking phase=done")
        state["phase"] = "done"
        save_state(project_root, state)
        return 0

    features = load_features(project_root)
    summary = load_summary(project_root) or {}
    counts = summary.get("progress_counts") or {}

    # H12: empty features.json is a setup error, not "nothing to do". The chain
    # would otherwise loop forever asking Claude to "resume" a nonexistent plan.
    if not features:
        append_log(project_root, "decide: FAIL — features.json missing or empty; run INIT before autodrive")
        fail_path(project_root).write_text(
            f"{utc_now()}\nfeatures.json missing or empty — run INIT before enabling autodrive\n",
            encoding="utf-8",
        )
        return 0

    everything_done = all_features_terminal(features)

    # H6: progress watchdog — if the `done` count hasn't moved for STALL_LIMIT
    # consecutive ticks, something is wrong (spawned session stalled on a
    # permission prompt, repeated on the same feature, etc.). Trip the fail
    # marker so the chain stops cleanly instead of burning max_iterations.
    done_now = _progress_done(counts, features)
    total = counts.get("total") if isinstance(counts.get("total"), int) else len(features)
    prev = state.get("last_progress_counts") or {}
    stall_count = int(state.get("stall_count", 0))
    if prev and prev.get("done") == done_now:
        stall_count += 1
    else:
        stall_count = 0
    state["last_progress_counts"] = {"done": done_now, "total": total}
    state["stall_count"] = stall_count
    if stall_count >= STALL_LIMIT and not everything_done:
        append_log(
            project_root,
            f"decide: FAIL — no progress for {stall_count} consecutive iterations (done={done_now})",
        )
        fail_path(project_root).write_text(
            f"{utc_now()}\nno progress for {stall_count} iterations; last done={done_now}\n",
            encoding="utf-8",
        )
        save_state(project_root, state)
        return 0

    current_feature = summary.get("current_feature") or state.get("last_feature_id")

    # M15: commit state ONLY after spawn succeeds. Previously iteration++ and
    # phase=review were written before Popen, so a spawn failure left the
    # state lying about what happened.
    if everything_done:
        append_log(project_root, "decide: all features terminal — spawning review session")
        if not spawn_claude(project_root, REVIEW_PROMPT, state):
            append_log(project_root, "decide: spawn failed — state left unchanged")
            return 0
        state["phase"] = "review"
        state["iteration"] = iteration + 1
        state["last_spawn_at"] = utc_now()
        save_state(project_root, state)
        append_log(project_root, "decide: review session spawned")
        return 0

    append_log(
        project_root,
        f"decide: continuing — iteration {iteration + 1}/{max_iters}, "
        f"counts={done_now}/{total}, current={current_feature}, stall={stall_count}",
    )
    if not spawn_claude(project_root, CONTINUE_PROMPT, state):
        append_log(project_root, "decide: spawn failed — state left unchanged")
        return 0
    state["iteration"] = iteration + 1
    state["last_spawn_at"] = utc_now()
    state["last_feature_id"] = current_feature
    save_state(project_root, state)
    append_log(project_root, "decide: continuation session spawned")
    return 0


def cmd_mark_review_done(project_root: Path) -> int:
    state = load_state(project_root)
    if not state:
        return 0
    state["phase"] = "done"
    save_state(project_root, state)
    append_log(project_root, "mark-review-done: phase=done")
    return 0


# ---------- entry ----------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root", default=".")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--decide", action="store_true")
    g.add_argument("--enable", action="store_true")
    g.add_argument("--disable", action="store_true")
    g.add_argument("--status", action="store_true")
    g.add_argument("--reset", action="store_true")
    g.add_argument("--fail", action="store_true")
    g.add_argument("--mark-review-done", action="store_true")
    p.add_argument("--max-iterations", type=int, default=DEFAULT_MAX_ITERATIONS)
    p.add_argument("--reason", default="")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).resolve()
    if not project_root.exists():
        print(f"project root does not exist: {project_root}", file=sys.stderr)
        return 2

    if args.decide:
        return cmd_decide(project_root)
    if args.enable:
        return cmd_enable(project_root, args.max_iterations)
    if args.disable:
        return cmd_disable(project_root)
    if args.status:
        return cmd_status(project_root)
    if args.reset:
        return cmd_reset(project_root)
    if args.fail:
        return cmd_fail(project_root, args.reason or "no reason provided")
    if args.mark_review_done:
        return cmd_mark_review_done(project_root)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
