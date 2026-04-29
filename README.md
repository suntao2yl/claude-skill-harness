# claude-skill-harness

[English](README.md) | [中文](README.zh-CN.md)

A Claude Code skill for long-running, multi-session development campaigns.

Built from the same core ideas described in Anthropic Engineering's long-running harness work:
- [Harness Design for Long-Running Apps](https://www.anthropic.com/engineering/harness-design-long-running-apps)
- [Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)

## What changed in v2

Harness v2 keeps the `/harness-plan` command surface the same, but swaps the internal recovery model:

- compact machine state instead of free-text recovery
- one active `current-contract.json` per feature
- `session-summary.json` as the default resume artifact
- deterministic Python scripts for state transitions
- risk-gated QA instead of always-on full reviewer loops
- portable script paths via `${CLAUDE_SKILL_DIR}` — works regardless of install location
- `harness_reset.py` for deterministic campaign archiving
- command router with explicit routing: `/harness-plan "goal"` → INIT, `/harness-plan` → RESUME
- `/harness-plan focus` checks for in-progress conflicts before switching
- startup reads only the active feature from `features.json`, not the entire file
- session-protocol.md merged into SKILL.md to reduce per-session token overhead
- retry escalation: `selftest_retries` counter auto-blocks after 3 consecutive failures
- session freshness signals: `checkpoint_writes`, completed step count, and session feature count trigger new-session recommendations
- parallel sub-task guidance: use Agent tool for independent work within a single feature
- auto-advance by default: only INIT plan approval, destructive actions, and QA review pause for confirmation
- scope drift detection: checkpoint warns when `files_touched` violate `scope_out` boundaries
- quick-verify: `harness_checkpoint.py --quick-verify` runs `test_command` during implementation to catch regressions early
- structured failure recording: `last_failure` object in checkpoint (command, error_summary, affected_files, timestamp)
- session handoff context: `session_id`, `session_step_count`, and `handoff_reason` in session-summary for cross-session continuity
- manual check tracking: `--manual-check-done` records completed manual checks before feature completion
- contract command history: `command_history` tracks verification command refinements with timestamps
- `backlog` status added to state machine with transitions to `pending`, `in_progress`, and `skipped`
- runtime platform detection: `detect_platform()` / `skill_home()` for Codex environment compatibility

## Core files

```text
.harness/
├── campaign.json
├── features.json
├── current-contract.json
├── session-summary.json
├── features-schema.json
├── contract-schema.json
├── session-summary-schema.json
└── progress.md
```

## State model

### `campaign.json`

Campaign metadata and defaults:

- `bootstrap_command`
- `setup_command`
- `default_review_policy`
- `baseline_status`
- `last_session_commit`

### `features.json`

Feature tracking with immutable `verification` and structured `checkpoint` objects.
Each feature also carries `blocked_history` (timestamped block/unblock log, capped at 10) and `archived_contract` (the contract snapshot saved when a feature completes).

### `current-contract.json`

The active feature contract:

- `feature_id`
- `goal`
- `scope_in`
- `scope_out`
- `verification_claims`
- `verification_commands`
- `manual_checks`
- `review_policy`
- `execution_context` — working directory and timeout for verification commands
- `command_history` — timestamped log of verification command refinements

### `session-summary.json`

Compact resume artifact used by new sessions and the SessionStart hook:

- campaign goal and mode
- current feature
- progress counts
- next resume steps
- known failures
- environment status
- `session_id` and `session_step_count` for session boundary detection
- `handoff_reason` — why the previous session ended (freshness, blocked, completed, interrupted)

## Built-in scripts

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_validate.py
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_summary.py
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_pick_next.py
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_transition.py --feature-id F007 --to in_progress
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_contract.py --feature-id F007
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_checkpoint.py --feature-id F007 --next-step "..."
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_checkpoint.py --feature-id F007 --quick-verify
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_checkpoint.py --feature-id F007 --manual-check-done "check description"
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_contract.py --feature-id F007 --update-command "old cmd" "new cmd"
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_reset.py --label "phase-1"
```

These scripts only operate on `.harness/` and are meant to replace hand-edited JSON for common state transitions.
`harness_contract.py` and `harness_checkpoint.py` only work on the active `in_progress` feature, and `harness_transition.py` refuses to create a second active feature.

Key script behaviors:
- `harness_validate.py` checks for git drift (HEAD vs last verified commit) and detects circular or dangling feature dependencies.
- `harness_checkpoint.py` auto-extracts `files_touched` from `git diff` when not explicitly provided. `--quick-verify` runs `test_command` before writing. `--selftest-retry` / `--failure-command` / `--failure-summary` record structured failure info. `--manual-check-done` marks manual checks as completed.
- `harness_contract.py` supports `--update-command` to refine verification commands with history tracking.
- `harness_transition.py` archives the active contract into the feature record on completion (instead of deleting it) and appends timestamped entries to `blocked_history` when blocking. Supports `backlog` status.
- `harness_reset.py` archives the entire campaign into `.harness/archive/<timestamp>_<label>/` and cleans `.harness/` for a fresh INIT.

## Workflow

```text
INIT -> PICK -> contract -> implement -> self-test -> optional QA -> checkpoint -> done
```

Resume priority:

1. `session-summary.json`
2. `current-contract.json`
3. active feature `checkpoint`
4. recent lines from `progress.md` only if needed

## Review policy

- `selftest`: run local verification only
- `qa`: run local verification first, then launch a separate skeptical reviewer agent

Use `qa` when the active feature touches UI flows, auth, payments, migrations, concurrency, or external integrations. Otherwise default to `selftest`.

## SessionStart hook

The plugin automatically registers a SessionStart hook on install. Each new session sees a compact campaign summary injected:

- goal
- progress counts
- current feature
- review policy
- environment status (with a warning when baseline is failing)
- last session date
- one next-step line
- known failures (up to 5)
- open issues from the current feature's last checkpoint (up to 5)
- `handoff_reason` from previous session (freshness, blocked, completed, interrupted)
- last selftest failure details when available

## Install

### Claude Code

```bash
# Add the marketplace, then install the plugin
/plugin marketplace add suntao2yl/claude-skill-harness
/plugin install harness-plan@suntao-skills
```

After installation, Claude Code exposes the slash command `/harness-plan`; the command routes into the bundled `harness-plan` skill.

### Codex

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo suntao2yl/claude-skill-harness \
  --path plugins/harness-plan/skills/harness-plan
```

Restart Codex after installation so the new skill appears in the skill list.

## License

MIT
