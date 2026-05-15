# harness-plan — Troubleshooting

## `harness_validate.py` reports invalid state

1. Read the error output — it names the specific inconsistency (e.g. "current_feature F003 is not in_progress in features.json").
2. Common causes: previous session crashed mid-transition, or a manual edit broke consistency.
3. Fix: use the transition script to correct the feature status, then re-run validate.

## Self-test fails repeatedly on the same error

1. Check `checkpoint.selftest_retries` — if already 2, the next failure forces blocking.
2. Read `checkpoint.last_selftest_failure.error_summary`.
3. If environmental (missing dep, wrong Python version), fix via `campaign.bootstrap_command` first.
4. If a real bug, fix the code, then re-run.

## Contract and `features.json` are inconsistent

1. `harness_validate.py` shows the exact mismatch.
2. Refresh: `harness_contract.py --feature-id <id>`.
3. If the feature was modified outside the scripts, the contract may reference stale verification commands — use `--update-command` to fix.

## `session-summary.json` is missing or stale

1. `harness_summary.py` regenerates it.
2. If `campaign.json` is also missing, the campaign is corrupted — `/harness-plan reset` to archive and start fresh.

## SessionStart hook error: "No such file or directory"

The plugin registers its hooks via `hooks/hooks.json` using `${CLAUDE_PLUGIN_ROOT}`. The plugin framework resolves this automatically — **never** manually write hook entries into `~/.claude/settings.json`. If you see a path like `~/.claude/skills/harness/hooks/session-start.sh` in settings.json, delete that entire `hooks.SessionStart` entry. The plugin's own `hooks.json` is the sole source of truth.

## Autodrive chain stopped unexpectedly

1. Inspect `.harness/autodrive.json` and the fail marker file — the marker holds the abort reason.
2. Common causes: a feature blocked at `selftest_retries >= 3`, an unresolvable state mismatch, or a hook-blocked command.
3. After fixing, `--reset` clears the marker; `--enable` resumes.
