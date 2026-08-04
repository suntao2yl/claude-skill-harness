# Capability Ownership

The 3.2 boundary prevents the unified workflow from duplicating its host.

| Capability | Owner | `$harness` responsibility |
| --- | --- | --- |
| Scale-appropriate discovery, design, architecture, and planning | Ultra native agent | Produce the revisioned Plan required by the approved contract |
| Implementation and authorized delivery changes | High native agent | Execute one approved Plan as the only writer |
| Tool choice and permission enforcement | Current host and project | Record approved boundaries; never grant authority |
| Test, review, release-readiness, and acceptance | Fresh Max native agent | Independently check the exact Do revision |
| Delivery objective | `.harness/ledger.json` | Persist and validate |
| Acceptance criteria | `.harness/ledger.json` | Freeze and validate |
| Cross-task checkpoint | `.harness/ledger.json` | Persist verified facts and next steps |
| Compact handoff | `.harness/ledger.json` | Produce a bounded resume surface |
| State consistency | ledger validator | Report errors without advancing state |
| Plan / Do / Check reasoning | Native Codex custom agents | Fix role, effort, sandbox, and structured handoff only |
| Act and retry budget | deterministic ledger command | Derive the next legal phase; never call a model |
| Concurrent phase writes | checkpoint sequence + lock | Reject stale state with compare-and-set semantics |

The plugin ships one explicit `$harness` skill. It does not restore a separate
seven-phase lifecycle engine: the useful lifecycle responsibilities are folded
into one sequential contract-to-Act loop, while intelligent work remains with
the host's native agents.
