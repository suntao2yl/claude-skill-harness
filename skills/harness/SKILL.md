---
name: harness
description: "Run one explicit repository-local engineering workflow that merges durable harness contracts, artifacts, gates, and cross-task handoff with a Codex-native PDCA loop: Ultra plans, High implements, Max checks, and deterministic code applies Act. Use only when the user explicitly invokes $harness or explicitly asks to initialize, inspect, validate, resume, migrate, or execute a tracked delivery through this workflow. Do not use for ordinary coding work or short-lived plans."
---

# Harness

Use one entry point, one ledger, one execution loop, and one completion gate.
Do not expose separate legacy, ledger, or PDCA modes to the user.

Treat the directory containing this `SKILL.md` as `<skill-dir>`. Use:

```text
<skill-dir>/scripts/harness_ledger.py
```

## Merge the responsibilities

Retain the useful responsibilities of the original lifecycle harness without
restoring a second seven-phase state machine:

- Fold necessary discovery, design, architecture, scope shaping, and risk
  analysis into Plan. Do only what the approved contract requires.
- Map implementation and other authorized changes to Do.
- Map test, review, release-readiness evidence, and acceptance verification to
  an independent Check.
- Map advance, revise, completion, blocking, and durable handoff to deterministic
  Act plus the ledger checkpoint.

Scale the Plan artifact to the work. A small fix does not require ceremonial
design or architecture documents; a product-scale change must cover those
decisions before Do. The immutable acceptance contract, not a fixed phase count,
defines the required depth.

The ledger is durable control state, not another work mode. Schema version 1 is
only an approved-contract bootstrap or legacy import. Active delivery runs in
schema version 2 through Plan, Do, Check, and Act.

PDCA execution is Codex-only. Another host may inspect and maintain the durable
contract and handoff state, but must not claim it ran the merged agent loop.

## Shared invariants

- Keep the approved goal, acceptance criteria, and contract digest immutable.
- Refuse destructive replacement. A scope change requires explicit user
  authorization to archive or replace the existing ledger.
- Keep `status`, `validate`, and `resume` read-only.
- Preserve unrelated user work and keep all artifacts inside the project.
- Do not add background daemons, hooks, queues, schedulers, or another lifecycle
  framework.
- Never let Plan or Do approve their own output. Check must be fresh and
  independent; Act must remain deterministic.

## Start or resume

Inspect `<project>/.harness/ledger.json` read-only first:

- No ledger: inspect the task and repository, draft the smallest observable
  acceptance contract, and obtain explicit user approval before initialization.
- Schema version 1: validate the approved contract. A request to execute or
  continue `$harness` authorizes enabling the merged loop. Pure status,
  validation, or migration requests remain read-only.
- Schema version 2: resume exactly the recorded phase and sequence.

Prepare a reviewed contract outside `.harness/`:

```json
{
  "acceptance": [
    {
      "id": "A001",
      "criterion": "Describe one observable delivered outcome.",
      "checks": ["State the concrete acceptance check."],
      "verification": {"command": "project-specific command"}
    }
  ]
}
```

Initialize only after approval, then immediately enable the merged loop:

```bash
python3 <skill-dir>/scripts/harness_ledger.py init \
  --project-root <project> \
  --goal "<approved delivery goal>" \
  --contract-file <contract.json>
python3 <skill-dir>/scripts/harness_ledger.py pdca enable \
  --project-root <project> \
  --expect-sequence 0 \
  --max-cycles 3 \
  --max-do-attempts 3 \
  --json
```

Inspect, validate, or resume without changing state:

```bash
python3 <skill-dir>/scripts/harness_ledger.py status --project-root <project>
python3 <skill-dir>/scripts/harness_ledger.py validate --project-root <project>
python3 <skill-dir>/scripts/harness_ledger.py resume --project-root <project>
```

Migrate legacy state only when explicitly requested:

```bash
python3 <skill-dir>/scripts/harness_ledger.py resume \
  --project-root <project> --migrate
```

Enabling creates a recoverable backup and freezes pending acceptance ids as run
scope. Ordinary checkpoints cannot complete acceptance or add acceptance-linked
evidence after enable; only deterministic Act may do so.

### Configure native agents

The project-scoped templates are:

```text
<skill-dir>/templates/agents/harness_planner.toml
<skill-dir>/templates/agents/harness_implementer.toml
<skill-dir>/templates/agents/harness_checker.toml
```

Preflight all destinations, then copy them unchanged to
`<project>/.codex/agents/`. Treat identical files as configured. Refuse to
overwrite a differing agent file without user review. The profiles intentionally
omit a base model while fixing reasoning effort and sandbox mode.

### Enter the loop

For an existing schema-version-1 ledger, read the current sequence and enable:

```bash
python3 <skill-dir>/scripts/harness_ledger.py status \
  --project-root <project> --json
python3 <skill-dir>/scripts/harness_ledger.py pdca enable \
  --project-root <project> \
  --expect-sequence <checkpoint-sequence> \
  --max-cycles 3 \
  --max-do-attempts 3 \
  --json
```

Every mutation requires the latest `checkpoint_sequence` and rejects stale
writes. Enabling is an internal transition in the single workflow, not a
user-visible mode choice.

### Plan — Ultra, read-only

Spawn `harness_planner`, wait for it, and persist its exact JSON inside the
project. Plan must perform the scale-appropriate discovery, design, architecture,
scope, and risk reasoning needed to make Do safe and executable. Require only
`contract_sha256`, `acceptance_ids`, `plan_revision`, `summary`, `steps`,
`verification`, and `risks`. Acceptance ids must exactly match scope in contract
order. `summary` and `plan_revision` are strings; `steps`, `verification`, and
`risks` are arrays of strings, never objects. Record with:

```bash
python3 <skill-dir>/scripts/harness_ledger.py pdca record-plan \
  --project-root <project> \
  --expect-sequence <latest-sequence> \
  --artifact-file <project-relative-plan-json> --json
```

If Plan exposes a required approval, authority boundary, destructive operation,
or release risk not already covered by the contract, do not record the Plan as
ready and do not start Do. Record `pdca block --code approval-required`, obtain
the user's decision, and use the authorized restart path. This is the merged
replacement for the original lifecycle risk gates.

### Do — High, one writer

Spawn `harness_implementer` with the approved Plan artifact. It owns the smallest
complete in-scope implementation or other authorized delivery change and its
relevant verification. Persist only
`plan_revision`, `candidate_revision`, `summary`, `changes`, and `verification`,
where `changes` is an array of strings and each `verification` item contains
only string fields `ref` and `result`. Then record it with `pdca record-do` and
the latest sequence.

### Check — Max, fresh and read-only

Spawn a fresh `harness_checker`. Give it the immutable contract, Plan artifact,
exact candidate revision, diff, and observable verification surfaces. Check owns
test, review, release-readiness evidence, and acceptance verification required by
the contract. Persist only `plan_revision`, `candidate_revision`, `summary`, and
exhaustive `criteria`.
Each criterion uses `acceptance_id`, `result`, `action`, and `evidence_ref`.
Passing criteria use `pass` and null action; failures use `fail` with `fix`,
`replan`, or `blocked`. Record with `pdca record-check` and the latest sequence.

Do not trust the implementer's conclusions or let Check edit the project.

### Act — deterministic

Do not ask a model to choose Act. Run:

```bash
python3 <skill-dir>/scripts/harness_ledger.py pdca act \
  --project-root <project> \
  --expect-sequence <latest-sequence> --json
```

Apply the returned transition: all pass completes the accepted delivery and its
handoff; blocked stops; replan returns to Plan if budget remains; otherwise fix
returns to Do if its budget remains. Exhausted budgets block. Continue until
complete, a real blocker, or a user-authorized scope change.

Record external blockers with `pdca block`. Restart a blocked run only after
explicit user authorization using `pdca restart --reason ...`; preserve all
prior events as audit history.
