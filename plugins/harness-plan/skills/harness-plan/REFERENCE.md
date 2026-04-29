# harness-plan — Detailed Reference

Full operational detail for each phase. The main `SKILL.md` carries the contract; this document holds the procedural specifics.

## Startup rules

Before any phase except INIT:

1. Run `python3 ${CLAUDE_SKILL_DIR}/scripts/harness_validate.py`.
2. Read `.harness/campaign.json` and `.harness/session-summary.json`.
3. If `campaign.current_feature` is set, read only that feature's entry from `features.json` (use `Grep` for the feature id when there are >10 features).
4. Read `.harness/current-contract.json` if it exists.
5. Only `tail` recent lines from `.harness/progress.md` if structured files are missing or inconsistent.

If `features.json` still contains legacy `checkpoint_notes`, treat as v1; scripts will normalize on write.

### Resume artifact priority

When deciding what happened last session, trust files in this order:

1. `.harness/session-summary.json`
2. `.harness/current-contract.json`
3. `feature.checkpoint` in `.harness/features.json`
4. recent lines from `.harness/progress.md`

Do not reconstruct the campaign from the Markdown log unless machine files are broken.

### Environment bootstrap

Try in order:

1. `campaign.bootstrap_command`
2. `campaign.setup_command`
3. `./.harness/init.sh`

If none exists, report clearly instead of guessing.

### Baseline verification

1. Run the bootstrap command.
2. Run one smoke check.
3. Run full suite only when smoke fails, `campaign.baseline_status == "failing"`, or prior session ended with failures.

Update `campaign.baseline_status` and refresh `session-summary.json` after baseline.

## INIT

Precondition: `.harness/` does not exist.

1. Explore the repo and determine test/bootstrap commands.
2. Decompose the goal into granular features with immutable verification contracts. For each feature, invoke `/tdd-plan --feature-id <id>` (or `/tdd-plan "<description>"` when `features.json` isn't written yet). Use the returned `verification_command` as `feature.verification.command`.
3. Create: `campaign.json`, `features.json`, `features-schema.json`, `contract-schema.json`, `session-summary.json`, `progress.md`.
4. Add `bootstrap_command`, `default_review_policy`, `last_session_commit`, `baseline_status` to `campaign.json`.
5. Set mode = `lite | standard | heavy`.
6. Run `harness_summary.py` to seed `session-summary.json`.
7. Present plan and wait for user approval.

## PICK

When no feature is in progress:

1. `harness_pick_next.py` (or `--focus F007`).
2. `harness_transition.py --feature-id F007 --to in_progress`. If another feature is active, the transition fails — do not auto-switch.
3. `harness_contract.py --feature-id F007` to create/refresh the active contract.
4. In `standard`/`heavy`, add scope boundaries and checklist items only if auto-generated contract is too vague.
5. Review contract warnings. If `verification_commands` reference non-existent test files, create the file as part of implementation, or refine via `--update-command`.
6. Start implementation immediately — PICK is the go-ahead.
7. When session-freshness signals approach limits, `--prefer-small`. Decompose large features via `Agent` for parallel execution.

Allowed transitions: `backlog→pending`, `backlog→in_progress`, `backlog→skipped`, `pending→in_progress`, `pending→skipped`, `in_progress→done`, `in_progress→blocked`, `blocked→pending`. See `resources/state-machine.md` for full rules.

## CONTINUE

When a feature is already in progress:

1. Resume from `session-summary.json`.
2. Read the active feature's `checkpoint`.
3. Refresh `current-contract.json` if active feature changed or contract is stale.
4. Continue from `checkpoint.next_step` immediately. Do not ask for confirmation.

Do not rebuild context from full campaign history unless structured state is broken.

## Implementation

`harness_checkpoint.py` at natural breakpoints (especially before session handoff). Applies only to active `in_progress` feature.

Checkpoint contents (all required): `completed_steps`, `next_step`, `open_issues`, `files_touched`, `tests_run`, `last_updated`, `last_verified_commit`, `selftest_retries`, `checkpoint_writes`.

When checkpoint includes new `files_touched` affecting test-covered code, use `--quick-verify` to run the campaign `test_command` early.

If checkpoint reports `scope_drift_warnings`: justify via `harness_contract.py` (update `scope_in`) or revert out-of-scope changes.

When the feature has independent sub-tasks (e.g. frontend + backend + tests), use `Agent` for parallel execution. Merge results, then update checkpoint.

`progress.md` is archival, not operational. Keep entries short.

## Self-Test

Canonical executor: `/completion-verify` from `harness-discipline`.

1. Baseline smoke check only if `baseline_status == "failing"` or prior session ended with failures. Otherwise skip — `/completion-verify` covers the active contract.
2. `/completion-verify --contract .harness/current-contract.json`. Parse JSON:
   - `pass` → proceed to Checkpoint and Completion.
   - `partial` → manual checks remain. Each via `harness_checkpoint.py --manual-check-done "..."` before completion.
   - `fail` → see failure handling below.
   - `no_commands` → contract malformed; refresh via `harness_contract.py` and re-run.
3. Update checkpoint `tests_run` with commands actually executed.

**Degraded mode** (no `harness-discipline`): run contract's `verification_commands` inline and construct equivalent JSON by hand.

### Failure handling

1. `harness_checkpoint.py --selftest-retry --failure-command "..." --failure-summary "..."`.
2. Diagnose, fix, re-run.
3. When `selftest_retries >= 3`, stop. Block via `harness_transition.py --to blocked --blocked-reason "..." --diagnostic-command "..." --suggested-fix "..."`. Forces deliberate re-evaluation next session.

## Review

Read `current-contract.json`, branch on `review_policy`:

- `selftest`: completion proceeds after self-test passes.
- `qa`: launch separate reviewer agent; load `resources/reviewer-calibration.md`.

When `review_policy: qa`, pass only: campaign goal, current feature metadata, immutable verification, active contract, changed file list, test command/output, one relevant UI/API route. **Do not pass** full `progress.md`, full feature list, unrelated history.

## Checkpoint and completion

After self-test or QA pass:

1. `harness_transition.py --feature-id F007 --to done`.
2. `harness_summary.py`.
3. Append one short entry to `progress.md`: date, feature id/name, status, files-changed summary, tests/review summary, optional note.
4. Check session freshness warnings before next feature.

### Session freshness

Start a fresh session when any signal appears (reported by `harness_summary.py`):

- 2+ features completed in current session
- checkpoint written 3+ times for current feature
- 10+ completed steps in checkpoint
- 15+ session steps
- `selftest_retries >= 3` (also requires blocking)

Hard signals, not suggestions. `harness_summary.py --handoff-reason freshness` marks the handoff.

## Autodrive

Cross-session auto-advance, one feature per session.

**Enable / disable / inspect:**

- `on` → `harness_autodrive.py --enable` (defaults to `--max-iterations 20`)
- `off` → `--disable`
- `status` → `--status`
- `reset` → `--reset` (deletes config + fail marker)

When enabling, also record `campaign.last_session_commit`. Script captures `campaign_base_commit` at enable time.

**In-session behavior when active:**

After feature → done and `harness_summary.py` runs, you must stop in this session — do NOT pick the next feature here. Stop hook spawns a fresh session:

1. Stage and commit:
   - `git add -A`
   - `git commit -m "feat(harness): complete F0XX - <title>"`
2. Print one line: `[autodrive] feature F0XX complete; ending session`
3. End your response. No further tool calls.

If `git commit` reports nothing to commit, skip the commit but still end the session.

**Failure handling (chain abort):**

Trip the fail marker — do NOT let next session start — when:

- Self-test retries hit 3 and you block the feature
- Unexpected/inconsistent state you cannot resolve mechanically
- A question would normally require `AskUserQuestion`

```text
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_autodrive.py --project-root . --fail --reason "<short reason>"
```

Then end the session. Stop hook sees the marker and stops the chain.

**Hard constraints in autodrive:**

- Never `AskUserQuestion`. If unavoidable, fail the chain.
- Never run destructive scripts (`harness_reset.py`, archive operations).
- Never spawn `claude -p` yourself — only the Stop hook does that.
- Iteration cap enforced by script (`max_iterations`, default 20).

**Final review session** (handled by Stop hook): when all features terminal, hook spawns dedicated review session running `/security-review` plus four parallel reviewer subagents (testability / maintainability / performance / design-consistency). Writes `.harness/review-report.md`. Marks `phase=done` and exits.

## Change units

Each CHG-NNN has its own propose → spec → verify → archive lifecycle. Parent feature transitions to `done` only when all units are `archived`.

In `standard` / `heavy`, when PICK selects a multi-commit/multi-file feature:

1. **Propose**: `harness_change.py --project-root . propose --feature-id F003 --title "Add CSV parser" --reason "..."`
2. **Spec**: `/change-spec --change-id CHG-001 --output .harness/changes/CHG-001/spec.md`, then `harness_change.py to-spec --change-id CHG-001 --spec-path .harness/changes/CHG-001/spec.md`.
3. **Verify**: `/completion-verify --contract <derived-from-spec>` → write JSON to `.harness/changes/CHG-001/verify.json`, then `harness_change.py to-verify --change-id CHG-001 --verify-evidence ...`.
4. **Archive**: `harness_change.py archive --change-id CHG-001 --files-touched src/csv.py tests/test_csv.py`.

When all units archived, run feature Self-Test as usual.

In `lite` mode, change units are not used.

For trivial features (≤30 LOC, single file, single test), prefer flat-feature flow even in standard mode — overhead beats granularity at small sizes.

`harness_change.py status [--feature-id F003]` reports change-unit progress. `session-summary.json` includes `current_change_unit` and `change_progress` when units exist.

## Script canon

Prefer these over manual edits:

```text
harness_validate.py
harness_summary.py
harness_pick_next.py
harness_transition.py --feature-id F007 --to in_progress
harness_contract.py --feature-id F007
harness_checkpoint.py --feature-id F007 --next-step "..."
harness_autodrive.py --project-root . --status
harness_change.py --project-root . status [--feature-id F007]
```

If a script reports invalid state, repair before continuing implementation.

## Gotchas

- Every feature's `verification.command` MUST be real and executable. `echo "TODO"` or `true` will pass selftest but fail engineering-level advance validation.
- When `selftest_retries >= 3`, stop. Block — do not retry.
- `checkpoint.next_step` must be concrete and actionable.
- Do not reconstruct state from `progress.md`. Trust machine-owned files in priority order.
- `verification` in `features.json` is immutable. Update `verification_commands` in the contract instead.
- Do not silently switch active feature. Transition script will reject; ask the user first.
