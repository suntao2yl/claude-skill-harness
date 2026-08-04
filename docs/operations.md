# Harness Operations

## `init`

Create `.harness/ledger.json` from an acceptance contract the user has
reviewed. Every criterion needs a stable id and an observable delivery result.

Initialization freezes the initial acceptance criteria. If state already
exists, stop and resume it. The command does not replace existing state.

## `status`

Read the compact state and report the delivery objective, acceptance counts,
open issues, and next steps. Do not change state or begin work.

## `checkpoint`

Write a handoff using facts available in the current task. Include completed
steps, open issues, acceptance evidence observed, and actionable next steps.
Prefer one precise next step and replace `ledger.json` atomically.

Marking a criterion complete requires evidence linked to its id, an observed
`pass` or `success` result, and a non-placeholder source revision.

## `validate`

Check schema, ids, contract immutability, completion evidence, and handoff
consistency. Return validation errors without changing state.
Validation never repairs or advances state implicitly.

## `resume`

Validate first. Then read the contract and latest checkpoint. Return a bounded
handoff containing:

- the approved contract;
- the last verified facts;
- open issues and the recorded update time;
- the recorded next step.

Resume does not perform that next step. The current task decides whether and
how to continue.

For a recognized older `.harness/`, `resume --migrate` performs the explicit,
idempotent schema migration and then returns the handoff. Normal `status` and
`resume` remain read-only and fail on legacy-only state instead of changing it.
Legacy completion labels remain unknown claims until current evidence satisfies
the 3.0 completion rule.

## Unified Codex workflow

`$harness` initializes or validates the approved contract, then enters the
active loop with `pdca enable`. Enabling creates a backup first and changes the
top-level schema from 1 to 2 so bootstrap or older writers fail closed. This is
an internal transition in one workflow, not a second user-facing mode.

The ordered write contract is:

```text
pdca enable
pdca record-plan
pdca record-do
pdca record-check
pdca act
```

Every write takes `--expect-sequence`; retrieve the latest value from `status`,
`resume`, or `pdca status`. Plan binds the immutable contract and complete
pending acceptance scope. Do binds the current Plan and emits one exact
candidate revision. Check binds both revisions and reports every scoped
criterion exactly once. Plan also owns the scale-appropriate discovery, design,
architecture, scope, and risk reasoning needed by the contract. Check owns the
required test, review, release-readiness, and acceptance evidence. Act is
deterministic and is the only path that can add
acceptance-linked evidence or completion in schema v2.

`pdca block` records a real external blocker. `pdca restart` requires explicit
authorization, returns to Plan, preserves history, and requires a higher cycle
budget when the previous one is exhausted. The command never starts agents,
runs project verification, or changes the acceptance contract.
