---
name: harness-plan
description: "Long-running task harness for multi-session campaigns with compact machine-owned state, immutable feature contracts, and risk-gated review. Use when user says 'start a campaign', 'continue the campaign', 'track features', 'long-running task', or invokes /harness-plan."
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
  version: 0.5.3
---

# Harness v2

Campaign orchestrator for long-running, multi-session development. Preserves momentum across sessions while keeping state compact, explicit, easy to resume.

## Hard invariants

1. All cross-session state lives in `.harness/`.
2. Work only one feature at a time.
3. `verification` in `features.json` is **immutable** unless the user changes it. `verification_commands` in `current-contract.json` MAY be refined via `harness_contract.py --update-command`.
4. `.harness/current-contract.json` is the only active implementation contract.
5. `.harness/session-summary.json` is the default resume artifact.
6. Use QA review only when active contract's `review_policy: qa`.
7. Prefer `scripts/` over hand-editing JSON.
8. Auto-advance by default. Pause only for: INIT plan approval, destructive actions (`reset`, archive), `review_policy: qa`.

## Command router

```text
/harness-plan "goal"     → INIT (new campaign)
/harness-plan            → RESUME (continue active campaign)
/harness-plan status | review | reset
/harness-plan focus F007 | add "..." | skip F003
/harness-plan autodrive on | off | status | reset
```

If `.harness/` exists and user runs `/harness-plan "goal"`, ask before archiving. If `.harness/` does not exist and user runs `/harness-plan` (no args), report no active campaign.

## Runtime files

Machine-owned: `campaign.json`, `features.json`, `current-contract.json`, `session-summary.json`. Human-readable: `progress.md`. All under `.harness/`.

Reference docs (load only when phase needs them): `resources/state-machine.md`, `resources/features-schema.md`, `resources/contract-schema.md`, `resources/session-summary-schema.md`, `resources/reviewer-calibration.md`, `resources/autodrive.md`.

## Phases (one-line summary)

- **Startup Rules** (before every phase except INIT): validate, read summary + active feature only, trust files in priority order. See [REFERENCE.md](REFERENCE.md#startup-rules).
- **INIT**: explore repo, decompose goal into features (use `/tdd-plan` for each), seed state files, await user approval. See [REFERENCE.md](REFERENCE.md#init).
- **PICK**: select next feature → mark in_progress → create active contract → start implementing immediately. See [REFERENCE.md](REFERENCE.md#pick).
- **CONTINUE**: resume from `session-summary.json` + `checkpoint.next_step` without asking. See [REFERENCE.md](REFERENCE.md#continue).
- **Implementation**: checkpoint at natural breakpoints with `harness_checkpoint.py`. Use `--quick-verify` when test-covered files change. See [REFERENCE.md](REFERENCE.md#implementation).
- **Self-Test**: invoke `/completion-verify --contract .harness/current-contract.json` and act on JSON status. See [REFERENCE.md](REFERENCE.md#self-test).
- **Review**: branch on `review_policy` (`selftest` skip; `qa` launch reviewer with calibrated context). See [REFERENCE.md](REFERENCE.md#review).
- **Completion**: transition to done → summary → progress.md entry → check session-freshness signals.

## Modes

- `lite`: claims + commands + manual checks. Skip change units.
- `standard`: + scope boundaries + acceptance checklist + change units enabled.
- `heavy`: + milestone verification + mid-campaign summaries.

For trivial features (≤30 LOC, single file/test) prefer flat-feature flow even in standard mode.

## Composes with

- `/tdd-plan` — seeds each feature's `verification` with a real test command.
- `/completion-verify` — canonical Self-Test executor.
- `/change-spec` — mini-RFC for change units (used in standard / heavy modes).
- `caveman` + `git-guardrails` — recommended in autodrive.

## Autodrive (one-paragraph)

`/harness-plan autodrive on|off|status|reset`. When `.harness/autodrive.json.enabled == true`: after feature → done, commit and **end the session** (Stop hook spawns the next); never call `AskUserQuestion` — trip the fail marker instead; never run destructive scripts. Full protocol: [REFERENCE.md](REFERENCE.md#autodrive) + `resources/autodrive.md`.

## Change units

In `standard` / `heavy`, break multi-commit features into CHG-NNN units via `harness_change.py propose | to-spec | to-verify | archive`. Use `/change-spec` for the mini-RFC. Feature → done only when all units `archived`. Skip in `lite`. See [REFERENCE.md](REFERENCE.md#change-units).

## Anti-patterns

- Don't eager-load all `resources/*.md` at session start — load only what the current phase needs.
- Don't call `AskUserQuestion` in autodrive — trip the fail marker instead.
- Don't double-review under `harness-engineering` — set `review_policy: selftest`.

See [REFERENCE.md](REFERENCE.md), [EXAMPLES.md](EXAMPLES.md), [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
