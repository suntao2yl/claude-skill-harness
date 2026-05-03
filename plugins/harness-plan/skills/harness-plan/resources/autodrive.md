# Autodrive Protocol

Autodrive turns a harness-plan campaign into a chain of one-feature-per-session
runs that proceed without user interaction. Each completed feature ends its
session; a Stop hook then spawns a fresh `claude -p` session that picks up the
next feature. After all features reach a terminal state, one final session
runs review and ends the chain.

## Components

| Piece | Path | Role |
|---|---|---|
| Stop hook | `hooks/stop.sh` | Fires when any session in the project ends. Calls the controller. |
| Controller | `scripts/harness_autodrive.py` | State machine. Decides whether to spawn the next session and with what prompt. |
| State file | `.harness/autodrive.json` | Iteration count, phase (`feature`/`review`/`done`), max cap, base commit. |
| Fail marker | `.harness/autodrive.fail` | If present, Stop hook bails. |
| Log | `.harness/autodrive.log` | Append-only record of every decide / spawn / fail. |
| In-session Claude | `SKILL.md` § "Autodrive Mode" | Knows to commit + end after each `done` instead of picking another feature. |

## State machine

States in `phase`:

- `feature` — features remain; on session end, spawn `claude -p "/harness-plan"`.
- `review` — all features terminal; review session is running. On session end, set `phase=done`.
- `done` — chain finished. Stop hook is a no-op from now on.

The controller transitions phase only on the Stop-hook decide tick (and on the
explicit `--mark-review-done` call from the review session itself).

## Decide-tick logic (Stop hook → `--decide`)

```
if no autodrive.json or enabled=false → exit 0
if .harness/autodrive.fail exists      → exit 0 (chain aborted)
if phase == "done"                     → exit 0
if iteration >= max_iterations         → set phase=done, exit 0
if phase == "review"                   → set phase=done, exit 0
if all features terminal               → spawn review session, set phase=review
else                                   → spawn continuation session, increment iteration
```

"All features terminal" means no feature has status `pending`, `in_progress`,
`backlog`, or `blocked`. (`done` and `skipped` are terminal.)

## What the in-session Claude must do

When `.harness/autodrive.json` is present and `enabled: true`:

1. Work on the active feature exactly as in normal mode.
2. After `harness_summary.py` reports the feature as done:
   - `git add -u` (staged tracked changes only — avoids folding unrelated untracked files into the feature commit)
   - `git add .harness/` (pick up campaign state updates)
   - `git commit -m "feat(harness): complete F0XX - <feature title>"`
   - End the session. **Do not pick the next feature.**
3. If self-test retries hit 3 (block condition) or the run encounters
   irrecoverable state, call:

   ```
   python3 <absolute path to harness_autodrive.py> --project-root . \
     --fail --reason "<short reason>"
   ```

   (The absolute path is embedded in the prompt the Stop hook sends — don't rely
   on `$CLAUDE_SKILL_DIR` / `$CLAUDE_PLUGIN_ROOT` being set in the spawned session.)
   Then end the session.

The Stop hook handles everything else.

## Spawn mechanics

`harness_autodrive.py` spawns the next session via Python's
`subprocess.Popen(..., start_new_session=True)`, which calls `setsid(2)` so
the new process is fully detached and survives the parent Claude's exit.
stdin is `/dev/null`; stdout and stderr go to `.harness/autodrive.log`.

The spawn command is:

```
<claude-binary> --dangerously-skip-permissions [--add-dir <harness-root>] -p "<prompt>"
```

- `--dangerously-skip-permissions` is required — the spawned session has no
  stdin (DEVNULL) and cannot answer permission prompts. Without this flag the
  session stalls on the first tool that needs confirmation and never reaches
  its natural Stop, breaking the chain on iteration 1.
- cwd is set to the git repo root (when locatable), so project-level
  `.claude/settings.json` and plugin scopes resolve the same way an
  interactive `cd <repo> && claude` would. `--add-dir <harness-root>` adds
  back write access to the campaign subdirectory (e.g.
  `.engineering/implementation/`).

The `claude` binary path is captured at `--enable` time (while the user's full
PATH is in scope) and persisted to `autodrive.json.claude_binary`. At spawn
time the controller prefers that path over re-running discovery, because the
Stop hook subprocess may run with a stripped PATH where shutil.which fails
(volta/asdf/nvm/bun often missing under GUI launches). Fallback probes
`~/.local/bin`, `~/.claude/local`, `~/.bun/bin`, `~/.volta/bin`,
`~/.asdf/shims`, `/usr/local/bin`, `/opt/homebrew/bin`, and every
`$NVM_DIR/versions/node/*/bin` entry before giving up.

## Review session prompt

The Stop hook spawns the review session with a self-contained prompt that:

1. Runs `/security-review` against the diff between `HEAD` and
   `campaign_base_commit` (recorded at enable time).
2. Launches four parallel `general-purpose` Agent subagents:
   - Testability
   - Maintainability
   - Performance
   - Design consistency
   Each returns < 200 words.
3. Concatenates all five outputs into `.harness/review-report.md`.
4. Commits the report with `chore(harness): autodrive review report`.
5. Calls `harness_autodrive.py --mark-review-done`, then ends.

## Operator commands

```
/harness-plan autodrive on        # Enable. Records campaign_base_commit = current HEAD.
/harness-plan autodrive off       # Disable (next Stop tick will exit). State file kept.
/harness-plan autodrive status    # Print state JSON, including fail marker presence.
/harness-plan autodrive reset     # Delete autodrive.json and any fail marker.
```

To kill a running chain immediately:

```
rm .harness/autodrive.json
# or
touch .harness/autodrive.fail
```

The first removes config so future Stop ticks become no-ops. The second leaves
config in place so you can investigate, then resume by deleting the marker.

## Limits and gotchas

- **Token cost compounds.** A 20-iteration chain runs 20 full Claude sessions.
  Adjust `--max-iterations` when enabling.
- **No human in the loop.** Autodrive must never call `AskUserQuestion`. If the
  in-session Claude would normally ask, it must trip the fail marker instead.
- **No destructive commands.** `harness_reset.py`, archive operations, force
  pushes, and similar are off-limits in autodrive mode.
- **Hook semantics.** Stop hook fires when a session ends naturally (Claude
  emits a final assistant message with no tool calls). It does not fire when
  the user kills the process. If you Ctrl-C out of an autodrive session, the
  chain pauses until you start the next one yourself.
- **Working tree assumption.** The commit uses `git add -u && git add .harness/`, so only tracked changes plus campaign state get folded in. Any unrelated untracked files you had staged before autodrive are left alone; make sure that's what you want before enabling.
- **One claude process at a time.** The detached spawn doesn't check whether
  another claude session is running. Don't manually start a second
  interactive session in the same project while autodrive is active.

## Failure modes the controller handles

| Condition | Effect |
|---|---|
| `.harness/autodrive.json` missing | Stop hook exits 0 (autodrive not configured). |
| `enabled: false` | Stop hook exits 0. Logged. |
| Fail marker present | Stop hook exits 0. Logged. Chain stays stopped until marker is removed. |
| `phase == "done"` | Stop hook exits 0. |
| `iteration >= max_iterations` | Set phase=done, exit. Logged with "hit max_iterations". |
| `features.json` missing/empty | Write fail marker (`features.json missing or empty — run INIT…`), exit. Chain pauses for operator. |
| No progress for 2 consecutive ticks | Progress watchdog trips. `done` count compared tick-to-tick; if unchanged and `stall_count >= 2`, write fail marker, exit. Prevents burning max_iterations on a stuck feature. |
| `claude` binary not found | Write fail marker, log error, exit. `--enable` persists the resolved binary path to `autodrive.json.claude_binary`, so the Stop hook's stripped PATH no longer matters. |
| Subprocess exception during spawn | Log error, exit 0. State is left unchanged (no iteration++) so a retry on the next Stop tick starts clean. |
