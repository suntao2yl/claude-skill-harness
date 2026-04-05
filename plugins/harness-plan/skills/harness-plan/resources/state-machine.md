# State Machine

Harness v2 keeps the command surface stable while making feature transitions deterministic.

## Phases

- `INIT`: no `.harness/` yet
- `PICK`: no active feature, choose the next eligible feature
- `CONTINUE`: `campaign.current_feature` exists
- `SELFTEST`: run local verification for the active feature
- `REVIEW`: run separate QA only when `current-contract.review_policy == "qa"`
- `CHECKPOINT`: persist structured handoff state
- `COMPLETE`: no pending or in-progress features remain

## Feature Status Transitions

Allowed transitions:

```text
pending -> in_progress
pending -> skipped
in_progress -> done
in_progress -> blocked
blocked -> pending
```

Disallowed examples:

- `done -> pending`
- `blocked -> in_progress`
- `skipped -> pending`

Use `python3 ${CLAUDE_SKILL_DIR}/scripts/harness_transition.py` for all changes.

## PICK Rules

Default selection:

1. pending only
2. dependencies satisfied
3. lowest priority number first
4. stable tie-breaker by feature id

Explicit focus:

- `focus` may target `pending` or `in_progress`
- blocked features must be moved to `pending` first

## Contract Rules

Every `in_progress` feature should have one active `.harness/current-contract.json`.

- `lite`: only claims, commands, and manual checks
- `standard` / `heavy`: also include `scope_in`, `scope_out`, and checklist-backed detail

Refresh the contract whenever the active feature changes.

## Checkpoint Rules

Write a checkpoint whenever:

- the session is about to end
- a risky code change lands
- self-test finishes
- the active next step changes materially

The checkpoint is the primary recovery record. `progress.md` is secondary.
