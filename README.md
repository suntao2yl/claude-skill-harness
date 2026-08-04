# Harness

Harness 3.2 exposes one explicit Codex skill and plugin: `$harness`. It merges
the durable contract, artifacts, gates, and cross-task handoff of the original
harness with a native PDCA execution loop.

There is no separate ledger mode or PDCA companion. Ultra owns Plan, High owns
Do, a fresh Max owns Check, and deterministic code owns Act. The repository-local
`.harness/` ledger preserves the approved scope and exact handoff across tasks.

## What it preserves

- the approved delivery objective and acceptance criteria;
- acceptance criteria that cannot drift silently;
- completed work, open issues, and one concrete next step;
- acceptance evidence and an auditable handoff summary.

Use it for a tracked delivery that benefits from an explicit acceptance contract
and independent closure. Ordinary one-turn work can continue to use native Codex
without the harness.

## Install in Codex

From a local clone:

```bash
codex plugin marketplace add /absolute/path/to/harness
codex plugin add harness@harness-marketplace
```

Start a new Codex task after installation. The skill is explicit-only:

```text
$harness start the approved delivery
$harness status
$harness validate
$harness resume
```

The plugin declares no hooks and starts no background process. The installed
distribution is generated from the canonical skill and checked for drift:

```bash
python3 scripts/sync_codex_plugin.py --check
```

## Unified Codex-native workflow

`$harness` is explicit and runs one contract-to-Act workflow:

- Plan uses an Ultra, read-only native agent and performs the necessary
  discovery, design, architecture, scope, and risk reasoning;
- Do uses a High, workspace-write native agent and is the only writer;
- Check uses a fresh Max, read-only native agent for contract-required test,
  review, release-readiness, and exact-revision acceptance;
- Act is deterministic code: complete, return to Do, replan, or block.

An approved contract is initialized first and then enters fail-closed schema v2;
schema v1 is only bootstrap or legacy-import state. Every phase records a
structured project-local artifact and uses checkpoint-sequence compare-and-set
protection. See the canonical [Harness skill](skills/harness/SKILL.md).

## State and safety

All active state lives at `<project>/.harness/`; explicit legacy migration may
also create an audit backup beside it. `status` and `validate` are read-only.
`resume` validates and returns the recorded contract, open issues, next phase,
and handoff. Only an exhaustive Check followed by deterministic Act can complete
acceptance criteria.

Acceptance criteria are frozen after initialization. The command has no
operation that rewrites them. A changed criterion is a new, user-approved
contract; preserve the previous ledger as audit history before replacing it.

See [USAGE.md](USAGE.md), [the operation contract](docs/operations.md),
[the architecture](docs/architecture.md), and
[the operating principles](docs/principles.md).

## Migrating from 2.x

Version 3.0 intentionally removes the `full` lifecycle mode and all
`.engineering/` lifecycle behavior.

| 2.x state or command | 3.0 action |
| --- | --- |
| Existing 2.x `.harness/` | Run `resume --migrate`. Migration archives the complete legacy directory, creates a clean active ledger, and is safe to repeat. Normal `status` and `resume` never migrate implicitly. |
| Both `.engineering/` and `.harness/` | Migrate `.harness/`; 3.0 ignores the lifecycle link. Archive the other directory only when your project no longer needs it. |
| Only `.engineering/implementation/.harness/` with legacy campaign files | Run `resume --migrate`; this is the one recognized nested legacy state location. |
| Other `.engineering/` lifecycle state without a recognized legacy `.harness/` | Review the still-relevant acceptance criteria and initialize a new ledger. There is no automatic conversion. |
| `$harness-engineering full ...` | Invoke `$harness`; scale-appropriate lifecycle reasoning is folded into Plan. |
| `$harness-engineering campaign ...` | Invoke `$harness`; the approved contract and PDCA event history replace the separate campaign state. |

The plugin and skill now share the same `harness` name, and `$harness` is the
only invocation. Version 3.2 does not restore a second fixed seven-phase engine;
it merges those responsibilities into the one contract-to-Act loop. The former
`harness-plan` implementation remains recoverable from repository history and
is not published by either marketplace.

Migration never upgrades an old `done` label into accepted completion. It
retains that label as an unknown legacy claim until current, revision-bound
success evidence is recorded.

## Claude compatibility

`.claude-plugin/` and `./install.sh --claude` expose the durable contract and
handoff surface to Claude-compatible hosts. The Ultra/High/Max agent loop remains
Codex-native.

## Validate this repository

```bash
python3 /path/to/skill-creator/scripts/quick_validate.py skills/harness
python3 scripts/sync_codex_plugin.py --check
python3 /path/to/plugin-creator/scripts/validate_plugin.py plugins/harness
python3 -m unittest discover -s tests -v
```
