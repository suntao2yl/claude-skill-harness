# Architecture

## Boundary

`$harness` is one contract-to-Act engineering workflow. `.harness/` stores the
approved delivery contract and durable control state; native Codex agents own
Plan, Do, and Check; deterministic ledger code validates phase receipts and
chooses Act.

```text
approved contract ──> Plan/Ultra ──> Do/High ──> Check/Max ──> Act/code
                            ^                         │              │
                            └──────── replan ─────────┘              ├─ complete
                                      Do <──── fix ─────────────────┤
                                                                   └─ blocked
```

The original lifecycle responsibilities are merged rather than preserved as a
second fixed phase engine. Plan performs only the discovery, design,
architecture, scope, and risk reasoning required by the contract; Do executes;
Check owns test, review, release-readiness, and acceptance; Act advances, fixes,
replans, completes, or blocks. The ledger grants no permissions and starts no
background continuation process.

## State model

`.harness/` is the only durable state root:

```text
.harness/
└── ledger.json               # contract, checkpoint, evidence, and handoff
```

`ledger.json` is the entire active contract and control state. Keeping one authoritative file
removes synchronization and partial-update failures between state fragments.

Schema version 1 is approved-contract bootstrap or legacy-import state.
`pdca enable` creates a backup and enters the active fail-closed schema-version-2
loop. Old schema-v1 writers reject schema v2. Structured Plan/Do/Check files are
content-hashed evidence references; they are not a second writable state store.

### Acceptance contract

The contract states the delivery objective and a list of observable acceptance
criteria. Each criterion has a stable id and may declare checks or verification
guidance. Once approved, the criteria are immutable. The command exposes no
contract-rewrite operation. A replacement contract is a separate,
user-approved ledger whose predecessor must be retained as audit history.

### Checkpoint

A checkpoint is a factual handoff, not a progress estimate. It records:

- completed steps;
- one concrete next step;
- open issues;
- acceptance evidence already observed;
- the source revision associated with that evidence.

It must not infer success from intent or from a previous conversation.

### Handoff

The embedded handoff is the bounded resume surface. It contains acceptance
counts, completed steps, open issues, freshness information, and one primary
next step. A consumer can recover it without scanning project files or older
transcripts.

## Operations

The durable ledger exposes five foundational operations:

| Operation | Reads | Writes | Result |
| --- | --- | --- | --- |
| `init` | user-approved acceptance contract | new `ledger.json` | frozen initial ledger |
| `status` | compact state | nothing | current snapshot |
| `checkpoint` | contract and verified facts | `ledger.json` atomically | durable handoff |
| `validate` | ledger structure and invariants | nothing | success or validation errors |
| `resume` | validated compact state | nothing by default | contract, issues, and next step |

The same `$harness` workflow adds ordered phase writes on the locked file:

| Operation | Gate | Result |
| --- | --- | --- |
| `pdca enable` | approved schema-v1 ledger + expected sequence | backup + schema-v2 Plan state |
| `pdca record-plan` | exact contract and acceptance scope | opens Do |
| `pdca record-do` | current Plan revision + candidate revision | opens Check |
| `pdca record-check` | fresh exhaustive report on exact candidate | opens Act |
| `pdca act` | latest Check | deterministic complete, fix, replan, or blocked |
| `pdca restart` | blocked state + explicit authorization | new bounded Plan cycle |

State mutation goes through deterministic helpers with preconditions and
atomic replacement. Direct edits are treated as untrusted until validation
succeeds.

The only migration path is the explicit `resume --migrate` operation. It may
rewrite recognized older `.harness/` state into the current schema, is safe to
repeat, preserves the source in `.harness-legacy-backup-*`, and never runs as a
side effect of ordinary inspection.

## Trust and approval

- Read-only operations never advance state.
- A checkpoint records only evidence available to the current task.
- Completion requires revision-bound `pass` or `success` evidence and cannot
  weaken the approved acceptance contract.
- Existing state blocks initialization; the command does not reset or replace
  it.
- Schema-v2 PDCA state rejects ordinary acceptance completion. Only a passing,
  exhaustive, revision-bound Check followed by deterministic Act can complete
  scoped criteria.
- Every PDCA mutation uses the latest checkpoint sequence as a compare-and-set
  token and shares the ledger's exclusive lock and atomic replacement.
- Project-defined permission boundaries still apply; the ledger grants none.

## Portability

The state format is host-neutral and uses project-relative paths wherever
possible. A fresh task can resume from the repository alone. Host-local task
ids, hidden processes, and conversation transcripts are not part of the state
contract.
