# Principles

These rules define the 3.2 unified Harness boundary.

## 1. Persist only what must cross a task boundary

The ledger exists for continuity. Ephemeral reasoning and ordinary execution
details stay in the current task. Approved scope, acceptance criteria,
checkpoints, failures, and the next step are durable.

## 2. The project state is the source of truth

A future task must not reconstruct delivery status from conversation history.
If a fact matters to handoff, write it to `.harness/` before ending the task.

## 3. Acceptance criteria do not drift silently

Approval freezes the contract. The command does not reinterpret or rewrite it.
A later change belongs in a new user-approved ledger, with the predecessor
retained as history.

## 4. Checkpoints are evidence, not optimism

Record observed results and an exact next step. Do not turn plans, attempted
commands, or unverified edits into claims of completion.

## 5. Resume is bounded

Start with the compact summary and active contract. Load older records only to
resolve an inconsistency or answer an audit question.

## 6. Read-only means read-only

`status`, `validate`, and the default `resume` path do not advance delivery
state. Inspection must be safe to repeat.

## 7. Destructive changes are outside the skill

The command has no reset, replacement, or delete operation. Existing state
blocks initialization; any external archival or deletion follows the host and
project approval rules.

## 8. The ledger grants no authority

Recorded permission boundaries describe the approved scope; they do not grant
access or override the host and project controls.

## 9. One skill, one state root, one execution loop

`$harness` owns the durable contract and native-agent role protocol. It uses
`.harness/ledger.json` as the only authoritative active state. Schema version 1
is bootstrap or legacy-import state; active delivery uses Plan, Do, Check, and
Act in schema version 2. Explicit migration backups and phase artifacts are
audit inputs, not a second state engine.

## 10. Prefer no ledger when no handoff is needed

State has a maintenance cost. If work will finish in the current task and no
audit trail is required, do not initialize `.harness/`.

## Non-goals

Harness assigns the contract-required planning, implementation, and independent
checking responsibilities to native Codex agents. It does not replace their
tools, host sandboxes, approvals, permission boundaries, or project policy.
