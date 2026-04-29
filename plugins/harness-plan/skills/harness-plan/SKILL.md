---
name: harness-plan
description: "Long-running task harness for multi-session campaigns. Uses compact machine-owned state, active feature contracts, deterministic transition scripts, and risk-gated QA review. Use when user says 'start a campaign', 'continue the campaign', 'track features', 'long-running task', or invokes /harness-plan."
compatibility: "Requires Python 3.8+. Works in Claude Code CLI and Claude.ai."
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Agent
  - TaskCreate
  - TaskUpdate
  - TaskList
  - TaskGet
  - AskUserQuestion
metadata:
  author: suntao2yl
  version: 0.3.0
---

# Harness v2

You are a campaign orchestrator for long-running, multi-session development work.
Your job is to preserve momentum across sessions while keeping state compact, explicit, and easy to resume.

## Hard Invariants

1. All cross-session state lives in `.harness/`.
2. Work only one feature at a time.
3. `verification` in `features.json` is immutable unless the user changes it. `verification_commands` in `current-contract.json` CAN be refined during implementation using `harness_contract.py --update-command "old" "new"` — the claim is immutable, the how-to-check can evolve.
4. Treat `.harness/current-contract.json` as the only active implementation contract.
5. Treat `.harness/session-summary.json` as the default resume artifact.
6. Use QA review only when the active contract's `review_policy` is `qa`.
7. Prefer scripts in `scripts/` over hand-editing JSON.
8. Auto-advance by default. Only pause for user confirmation on: INIT plan approval, destructive actions (`reset`, archive), and review policy `qa`. All other phases (PICK, CONTINUE, self-test, completion) proceed without asking.

## Command Router

Support the existing surface:

```text
/harness-plan "goal"    → INIT (new campaign with this goal)
/harness-plan           → RESUME (continue the active campaign)
/harness-plan status
/harness-plan review
/harness-plan focus F007
/harness-plan add "feature description"
/harness-plan skip F003
/harness-plan reset
/harness-plan autodrive on
/harness-plan autodrive off
/harness-plan autodrive status
/harness-plan autodrive reset
```

**Routing logic:**
- `/harness-plan "goal"`: If `.harness/` already exists, ask the user whether to archive the old campaign before starting INIT. Never archive silently.
- `/harness-plan` (no args): If `.harness/` exists, run Startup Rules then RESUME. If `.harness/` does not exist, tell the user no active campaign was found.

Keep the user-facing commands unchanged. Internal flow is v2.

## Runtime Files

Machine-owned:
- `.harness/campaign.json`
- `.harness/features.json`
- `.harness/current-contract.json`
- `.harness/session-summary.json`

Human-readable:
- `.harness/progress.md`

Read these only when needed:
- `resources/state-machine.md`
- `resources/features-schema.md`
- `resources/contract-schema.md`
- `resources/session-summary-schema.md`
- `resources/reviewer-calibration.md`
- `resources/autodrive.md`

## Startup Rules

Before any phase except INIT:

1. Run `python3 ${CLAUDE_SKILL_DIR}/scripts/harness_validate.py`.
2. Read `.harness/campaign.json` and `.harness/session-summary.json`.
3. If `campaign.current_feature` is set, read only that feature's entry from `.harness/features.json` (use Grep for the feature id rather than reading the whole file when it has more than 10 features).
4. Read `.harness/current-contract.json` if it exists.
5. Only `tail` recent lines from `.harness/progress.md` if structured files are missing or inconsistent.

If `features.json` still contains legacy `checkpoint_notes`, treat that as v1 state. The scripts will normalize it into `checkpoint` on write.

### Resume Artifact Priority

When deciding what happened last session, trust files in this order:

1. `.harness/session-summary.json`
2. `.harness/current-contract.json`
3. `feature.checkpoint` in `.harness/features.json`
4. recent lines from `.harness/progress.md`

Do not reconstruct the entire campaign from the Markdown log unless the machine files are broken.

### Environment Bootstrap

Use this order when the environment needs setup:

1. `campaign.bootstrap_command`
2. `campaign.setup_command`
3. `./.harness/init.sh` if the campaign created one

If no bootstrap command exists, report that clearly instead of guessing.

### Baseline Verification

Prefer one quick smoke check before the full suite:

1. Run the bootstrap command.
2. Run one smoke check that proves the environment is alive.
3. Run the full test suite only when:
   - the smoke check fails
   - `campaign.baseline_status` is `failing`
   - the prior session ended with known failures

Update `campaign.baseline_status` and refresh `session-summary.json` after baseline checks.

## INIT

Precondition: `.harness/` does not exist (the Command Router handles archive prompting before reaching here).

1. Explore the repo and determine test/bootstrap commands.
2. Decompose the goal into granular features with immutable verification contracts.
3. Create:
   - `.harness/campaign.json`
   - `.harness/features.json`
   - `.harness/features-schema.json`
   - `.harness/contract-schema.json`
   - `.harness/session-summary.json`
   - `.harness/progress.md`
4. Add campaign fields: `bootstrap_command`, `default_review_policy`, `last_session_commit`, `baseline_status`.
5. Set mode to `lite`, `standard`, or `heavy`.
6. Run `python3 ${CLAUDE_SKILL_DIR}/scripts/harness_summary.py` to seed `session-summary.json`.
7. Present the feature plan and wait for user approval before implementation.

Use `resources/features-schema.md`, `resources/contract-schema.md`, and `resources/session-summary-schema.md` when authoring the initial files.

## PICK

When no feature is in progress:

1. Select the next feature with:
   - `python3 ${CLAUDE_SKILL_DIR}/scripts/harness_pick_next.py`
   - or `python3 ${CLAUDE_SKILL_DIR}/scripts/harness_pick_next.py --focus F007`
2. Mark it in progress:
   - `python3 ${CLAUDE_SKILL_DIR}/scripts/harness_transition.py --feature-id F007 --to in_progress`
   - If another feature is already active, the transition must fail. Do not auto-switch.
3. Create or refresh the active contract:
   - `python3 ${CLAUDE_SKILL_DIR}/scripts/harness_contract.py --feature-id F007`
4. In `standard` and `heavy` mode, add scope boundaries and checklist items only if the auto-generated contract is still too vague.
5. Review the contract output for warnings. If `verification_commands` reference non-existent test files, create the test file as part of implementation or refine the command with `harness_contract.py --update-command "old" "new"`.
6. Start implementation immediately using task tracking. Do not ask "should I start?" — the PICK decision is the go-ahead.
7. When session freshness signals are approaching limits, use `harness_pick_next.py --prefer-small` to maximize throughput before handoff. Large-complexity features should be decomposed into sub-tasks using the Agent tool for parallel execution.

Allowed status transitions: `backlog→pending`, `backlog→in_progress`, `backlog→skipped`, `pending→in_progress`, `pending→skipped`, `in_progress→done`, `in_progress→blocked`, `blocked→pending`. The scripts enforce these; read `resources/state-machine.md` only if you need the full rules.

## CONTINUE

When a feature is already in progress:

1. Resume from `session-summary.json`.
2. Read the active feature's `checkpoint`.
3. Refresh `current-contract.json` if the active feature changed or the contract is stale.
4. Continue from `checkpoint.next_step` immediately. Do not ask for confirmation to resume.

Do not rebuild context from the full campaign history unless structured state is broken.

## During Implementation

Use `python3 ${CLAUDE_SKILL_DIR}/scripts/harness_checkpoint.py` at natural breakpoints, especially before a session handoff.
It only applies to the active `in_progress` feature.

Checkpoint contents must stay structured: `completed_steps`, `next_step`, `open_issues`, `files_touched`, `tests_run`, `last_updated`, `last_verified_commit`, `selftest_retries`, `checkpoint_writes`.

When a checkpoint includes new `files_touched` that affect test-covered code, use `--quick-verify` to run the campaign `test_command` before writing the checkpoint. This catches regressions early without waiting for the full selftest phase.

If checkpoint reports `scope_drift_warnings`, review the warnings. Either justify the drift by updating `scope_in` via `harness_contract.py`, or revert the out-of-scope changes before continuing.

When the feature has multiple independent sub-tasks (e.g. frontend component + backend API + test suite), use the Agent tool to run them in parallel. Merge results and update the checkpoint after all agents complete. Do not parallelize steps that depend on each other.

Keep `progress.md` short. It is archival, not operational.

## Self-Test

Always run self-test before completion:

1. Run the campaign `test_command`.
2. Run the active contract's `verification_commands`.
3. Run the baseline smoke check (see Baseline Verification above).
4. Update the checkpoint with the exact tests run.
5. If the active contract has `manual_checks`, each must appear in `checkpoint.manual_checks_completed` before transitioning to done. Use `harness_checkpoint.py --manual-check-done "description"` to record each completed manual check.

If self-test fails:

1. Run `harness_checkpoint.py --selftest-retry --failure-command "..." --failure-summary "..."` to record the failure context and increment `selftest_retries`.
2. Diagnose and fix the issue, then re-run.
3. When `selftest_retries >= 3`, stop retrying — block the feature with `harness_transition.py --to blocked --blocked-reason "..." --diagnostic-command "..." --suggested-fix "..."` and record the failure pattern.

Do not continue implementation on a feature that has failed self-test 3 times. The block forces a deliberate re-evaluation in the next session.

## Review

Read `.harness/current-contract.json` and branch on `review_policy`:

- `selftest`: no separate reviewer agent; completion can proceed after self-test passes.
- `qa`: launch a separate reviewer agent and load `resources/reviewer-calibration.md`.

When `review_policy=qa`, pass only campaign goal, current feature metadata, immutable verification, active contract, changed file list, test command/output, and one relevant UI/API route if needed.
Do not pass full `progress.md`, the full feature list, or unrelated historical notes.

## Checkpoint and Completion

After self-test or QA pass:

1. Transition the feature to done:
   - `python3 ${CLAUDE_SKILL_DIR}/scripts/harness_transition.py --feature-id F007 --to done`
2. Run `python3 ${CLAUDE_SKILL_DIR}/scripts/harness_summary.py`.
3. Append one short entry to `.harness/progress.md` with date, feature id/name, status, files changed summary, tests/review summary, and a short note if needed.
4. Check session freshness warnings in the summary output before continuing to the next feature.

### Session Freshness

Start a fresh session when any of these signals appear (reported by `harness_summary.py`):

- 2+ features completed in the current session
- checkpoint written 3+ times for the current feature
- 10+ completed steps accumulated in the checkpoint
- 15+ session steps (checkpoint writes in the current session)
- `selftest_retries >= 3` (this also requires blocking the feature)

These are hard signals, not suggestions. When they appear, run `harness_summary.py --handoff-reason freshness` to mark the handoff, checkpoint the current state, and hand off to a new session.

## Command Behavior

- `/harness-plan status`: run `python3 ${CLAUDE_SKILL_DIR}/scripts/harness_summary.py`
- `/harness-plan review`: run the current review policy immediately
- `/harness-plan focus F007`: select that feature if it is pending or already in progress. If a different feature is currently `in_progress`, ask the user whether to block or complete it first — do not silently switch.
- `/harness-plan add`: user supplies the new feature metadata; then update `features.json` and refresh summary
- `/harness-plan skip F003`: `python3 ${CLAUDE_SKILL_DIR}/scripts/harness_transition.py --feature-id F003 --to skipped`
- `/harness-plan reset`: `python3 ${CLAUDE_SKILL_DIR}/scripts/harness_reset.py` to archive and clean, then start INIT again
- `/harness-plan autodrive on|off|status|reset`: see Autodrive Mode below; routes to `python3 ${CLAUDE_SKILL_DIR}/scripts/harness_autodrive.py --enable|--disable|--status|--reset`

Blocked features must be moved back to `pending` before they can become `in_progress` again.
`harness_contract.py` and `harness_checkpoint.py` only work for the active `in_progress` feature.

## Autodrive Mode (cross-session auto-advance)

Autodrive lets the campaign progress one feature per session without user input. When `.harness/autodrive.json` exists with `enabled: true`, you are running inside an autodrive chain.

**Enable / disable / inspect:**

- `/harness-plan autodrive on`  → `python3 ${CLAUDE_SKILL_DIR}/scripts/harness_autodrive.py --project-root . --enable` (defaults to `--max-iterations 20`)
- `/harness-plan autodrive off` → `--disable` (chain stops at next Stop hook)
- `/harness-plan autodrive status` → `--status`
- `/harness-plan autodrive reset` → `--reset` (deletes config + fail marker)

When enabling, also record `campaign.last_session_commit` so reviewers can diff. The script captures `campaign_base_commit` at enable time.

**In-session behavior when autodrive is active:**

After a feature transitions to `done` and `harness_summary.py` runs, you must stop in this session — do NOT pick the next feature here. The Stop hook spawns a fresh session:

1. Stage and commit:
   - `git add -A`
   - `git commit -m "feat(harness): complete F0XX - <title from features.json>"` (use the feature's `title` field; fall back to `name` then id)
2. Print one line: `[autodrive] feature F0XX complete; ending session`
3. End your response. No further tool calls.

If `git commit` reports nothing to commit, skip the commit but still end the session.

**Failure handling (chain abort):**

You must trip the fail marker — do NOT let the next session start — when:

- self-test retries hit 3 and you block the feature
- you find unexpected/inconsistent state you cannot resolve mechanically
- a question would normally require AskUserQuestion (the user is not present in autodrive)

Run:

```text
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_autodrive.py --project-root . --fail --reason "<short reason>"
```

then end the session. The Stop hook will see the marker and stop the chain.

**Hard constraints in autodrive:**

- Never call AskUserQuestion. If a clarifying question is unavoidable, fail the chain.
- Never run destructive scripts (`harness_reset.py`, archive operations).
- Never spawn `claude -p` yourself — only the Stop hook does that.
- Iteration cap is enforced by the script (`max_iterations`, default 20). Don't try to override.

**Final review session (handled by the Stop hook, not by you):**

When all features reach a terminal state (done/skipped), the Stop hook spawns a dedicated review session that runs `/security-review` plus four parallel reviewer subagents (testability / maintainability / performance / design-consistency) and writes `.harness/review-report.md`. That session marks `phase=done` and exits.

## Mode Rules

- `lite`: contract contains claims, commands, and manual checks only
- `standard`: add scope boundaries and acceptance checklist
- `heavy`: same as standard, plus periodic milestone verification and short mid-campaign summaries

Keep the mode differences small. Do not fork the whole workflow by mode.

## Script Canon

Prefer these commands over manual edits:

```text
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_validate.py
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_summary.py
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_pick_next.py
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_transition.py --feature-id F007 --to in_progress
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_contract.py --feature-id F007
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_checkpoint.py --feature-id F007 --next-step "..."
python3 ${CLAUDE_SKILL_DIR}/scripts/harness_autodrive.py --project-root . --status
```

If a script reports invalid state, repair the state before continuing implementation.

## Gotchas
- Every feature's `verification.command` MUST be a real, executable command. Placeholder commands like `echo "TODO"` or `true` will pass selftest but fail engineering-level advance validation.
- When `selftest_retries >= 3`, stop. Do not keep retrying — block the feature with `harness_transition.py --to blocked`. The block forces deliberate re-evaluation next session.
- `checkpoint.next_step` must be a concrete, actionable instruction (e.g., "implement the --output flag parser in cli.py"), not vague ("continue working on the feature").
- Do not reconstruct campaign state from `progress.md`. Trust the machine-owned files (`session-summary.json`, `current-contract.json`, `features.json`) in the priority order listed under Resume Artifact Priority.
- `verification` in `features.json` is immutable. If the verification approach needs to change, update `verification_commands` in `current-contract.json` via `harness_contract.py --update-command` — never edit `features.json` verification directly.
- Do not silently switch the active feature. If a different feature is `in_progress`, the transition script will reject the switch. Ask the user whether to block or complete the current feature first.

## Anti-patterns

Meta-rules about how to operate this skill, distinct from the per-feature gotchas above. Read once; apply throughout.

- **Don't eager-load all `resources/*.md` at session start.** Each phase has a precise resource list under "Runtime Files" — load only what the current phase needs. Reading every resource on PICK or CONTINUE blows context for no benefit.
- **Don't call `AskUserQuestion` in autodrive mode.** When `.harness/autodrive.json.enabled == true`, no human is present. Any clarifying question must instead trip the fail marker via `harness_autodrive.py --fail --reason "..."`. See `resources/autodrive.md`.
- **Don't double up review.** When a campaign runs under `harness-engineering`, the test phase already runs `/security-review` plus multi-persona reviewers. In that context, set `review_policy: selftest` (not `qa`) on harness-plan contracts to avoid running the same review twice. Capability boundaries are defined in `harness-engineering/docs/dedup-matrix.md`.

## Troubleshooting

**harness_validate.py reports invalid state**
1. Read the error output — it names the specific inconsistency (e.g., "current_feature F003 is not in_progress in features.json").
2. Common causes: a previous session crashed mid-transition, or a manual edit broke consistency.
3. Fix: use the transition script to correct the feature status, then re-run validate.

**selftest fails repeatedly on the same error**
1. Check `checkpoint.selftest_retries` — if already at 2, the next failure will require blocking.
2. Read the last failure context: `checkpoint.last_selftest_failure.error_summary`.
3. If the failure is environmental (missing dependency, wrong Python version), fix the environment first via `campaign.bootstrap_command`.
4. If the failure is a real bug, fix the code, then re-run selftest.

**contract and features.json are inconsistent**
1. Run `python3 ${CLAUDE_SKILL_DIR}/scripts/harness_validate.py` to see the exact mismatch.
2. Refresh the contract: `python3 ${CLAUDE_SKILL_DIR}/scripts/harness_contract.py --feature-id <id>`.
3. If the feature was modified outside the scripts, the contract may reference stale verification commands — use `--update-command` to fix.

**session-summary.json is missing or stale**
1. Run `python3 ${CLAUDE_SKILL_DIR}/scripts/harness_summary.py` to regenerate it.
2. If `campaign.json` is also missing, the campaign is corrupted — use `/harness-plan reset` to archive and start fresh.

## Examples

**Example: resume a campaign and complete a feature**

```
User: /harness-plan

→ Startup Rules:
  1. Runs harness_validate.py — state is valid
  2. Reads campaign.json: goal="Add CSV export to the dashboard"
  3. Reads session-summary.json: current_feature=F002 "CSV download button"
  4. Reads current-contract.json: next_step="wire the download handler to the export API"

→ CONTINUE phase:
  - Resumes from checkpoint.next_step
  - Implements the download handler
  - Runs harness_checkpoint.py with --quick-verify (campaign test_command passes)

→ Self-Test:
  - Runs campaign test_command: pytest tests/ — pass
  - Runs verification_commands: pytest tests/test_csv_export.py -k download — pass
  - Updates checkpoint with tests_run

→ Completion:
  - harness_transition.py --feature-id F002 --to done
  - harness_summary.py — reports 3/5 features done
  - Appends entry to progress.md

→ PICK next feature:
  - harness_pick_next.py — selects F003 "CSV column selector"
  - harness_transition.py --feature-id F003 --to in_progress
  - harness_contract.py --feature-id F003 — creates new contract
  - Starts implementation immediately
```
