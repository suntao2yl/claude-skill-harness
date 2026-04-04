# claude-skill-harness

[English](README.md) | [中文](README.zh-CN.md)

A Claude Code skill for long-running, multi-session development campaigns.

Built from the same core ideas described in Anthropic Engineering's long-running harness work:
- [Harness Design for Long-Running Apps](https://www.anthropic.com/engineering/harness-design-long-running-apps)
- [Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)

## What changed in v2

Harness v2 keeps the `/harness` command surface the same, but swaps the internal recovery model:

- compact machine state instead of free-text recovery
- one active `current-contract.json` per feature
- `session-summary.json` as the default resume artifact
- deterministic Python scripts for state transitions
- risk-gated QA instead of always-on full reviewer loops
- portable script paths via `${CLAUDE_SKILL_DIR}` — works regardless of install location
- `harness_reset.py` for deterministic campaign archiving
- command router with explicit routing: `/harness "goal"` → INIT, `/harness` → RESUME
- `/harness focus` checks for in-progress conflicts before switching
- startup reads only the active feature from `features.json`, not the entire file
- session-protocol.md merged into SKILL.md to reduce per-session token overhead

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

### `session-summary.json`

Compact resume artifact used by new sessions and the SessionStart hook:

- campaign goal and mode
- current feature
- progress counts
- next resume steps
- known failures
- environment status

## Built-in scripts

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_validate.py
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_summary.py
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_pick_next.py
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_transition.py --feature-id F007 --to in_progress
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_contract.py --feature-id F007
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_checkpoint.py --feature-id F007 --next-step "..."
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_reset.py --label "phase-1"
```

These scripts only operate on `.harness/` and are meant to replace hand-edited JSON for common state transitions.
`harness_contract.py` and `harness_checkpoint.py` only work on the active `in_progress` feature, and `harness_transition.py` refuses to create a second active feature.

Key script behaviors:
- `harness_validate.py` checks for git drift (HEAD vs last verified commit) and detects circular or dangling feature dependencies.
- `harness_checkpoint.py` auto-extracts `files_touched` from `git diff` when not explicitly provided.
- `harness_transition.py` archives the active contract into the feature record on completion (instead of deleting it) and appends timestamped entries to `blocked_history` when blocking.
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

Configure a hook so each new Claude session sees a compact campaign summary:

```json
{
  "hooks": {
    "SessionStart": [{
      "matcher": "*",
      "hooks": [{
        "type": "command",
        "command": "~/.claude/skills/harness/hooks/session-start.sh"
      }]
    }]
  }
}
```

The hook injects:

- goal
- progress counts
- current feature
- review policy
- environment status (with a warning when baseline is failing)
- last session date
- one next-step line
- known failures (up to 5)
- open issues from the current feature's last checkpoint (up to 5)

## Install

```bash
npx skills add suntao2yl/claude-skill-harness
```

## License

MIT
