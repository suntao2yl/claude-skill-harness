# Usage

Resolve `<skill-dir>` to the installed directory containing `SKILL.md`. The
public skill uses one deterministic command:

```bash
python3 <skill-dir>/scripts/harness_ledger.py <operation> [options]
```

Routine writes replace only `<project>/.harness/ledger.json`. Explicit legacy
migration also creates a project-root backup of the source state. The command
does not perform project work on the user's behalf.

## Initialize the workflow contract

Prepare a user-approved acceptance contract, then initialize once:

```json
{
  "acceptance": [
    {
      "id": "A001",
      "criterion": "The approved delivery result is observable"
    }
  ]
}
```

Each acceptance entry may also contain `checks` as an array of strings and
`verification` as a string, array, or object. The contract may contain a
top-level `goal`; when present, it must exactly match `--goal`.

```bash
python3 <skill-dir>/scripts/harness_ledger.py init \
  --project-root /path/to/project \
  --goal "Deliver the approved backlog" \
  --contract-file /path/to/approved-contract.json
```

If `.harness/` already exists, stop and inspect it. Initialization never
replaces existing state implicitly.

For a new `$harness` delivery, initialization is immediately followed by
`pdca enable`; schema version 1 is only the approved-contract bootstrap:

```bash
python3 <skill-dir>/scripts/harness_ledger.py pdca enable \
  --project-root /path/to/project \
  --expect-sequence 0 \
  --max-cycles 3 \
  --max-do-attempts 3 \
  --json
```

The equivalent explicit skill request is:

```text
$harness start the approved delivery
```

The skill must show the proposed contract to the user before passing it to the
command.

## Inspect status

```bash
python3 <skill-dir>/scripts/harness_ledger.py status \
  --project-root /path/to/project
```

Add `--json` for machine-readable output. Status is read-only and safe to
repeat.

## Record non-acceptance handoff facts

Record only facts observed in the current task:

```bash
python3 <skill-dir>/scripts/harness_ledger.py checkpoint \
  --project-root /path/to/project \
  --completed-step "Updated the service boundary" \
  --next-step "Run the contract verification in the staging environment" \
  --open-issue "Staging credentials are not available" \
  --summary "Implementation is ready for environment verification"
```

Repeat `--completed-step` or `--open-issue` to add multiple entries. Prefer one
precise `--next-step`; repeated next steps exist for migrated or genuinely
ordered handoffs. Use `--clear-next-steps` or `--clear-open-issues` only when the
current task has established that the recorded entries are obsolete.

The low-level schema-version-1 bootstrap format can complete an acceptance id
with `--complete <id>` and evidence, but the merged `$harness` workflow does not
use this path. Once enabled, only an exhaustive Check followed by deterministic
Act may complete acceptance. The legacy/bootstrap command shape is:

```bash
python3 <skill-dir>/scripts/harness_ledger.py checkpoint \
  --project-root /path/to/project \
  --complete A001 \
  --evidence-json '{"kind":"test","ref":"npm test","result":"pass","revision":"abc123"}' \
  --next-step "Continue A002" \
  --summary "A001 accepted"
```

Completion without matching evidence is rejected. Each evidence object
contains at least:

```json
{
  "kind": "test",
  "ref": "the observed command, check, artifact, or external record",
  "result": "the observed result",
  "revision": "source, artifact, deployment, or snapshot revision associated with the evidence"
}
```

`observed_at` is filled automatically when omitted. Completion accepts only
associated evidence whose `result` is `pass` or `success`; `revision` must be a
non-placeholder token and cannot be `unknown`. The caller asserts that token;
the ledger records it but does not invoke Git or another version system to
resolve it.
With one `--complete`, evidence that omits `acceptance_ids` is associated with
that id automatically. With multiple `--complete` arguments, evidence must
declare `"acceptance_ids":["A001", "A002"]` and collectively cover every
completed id. Use `--json` when the caller needs the updated ledger as
structured output. Later failing evidence linked to a completed id reopens that
id, so current status follows the newest linked evidence rather than an older
success.

## Validate

```bash
python3 <skill-dir>/scripts/harness_ledger.py validate \
  --project-root /path/to/project
```

Validation checks schema and internal links without repairing or advancing
state. Add `--json` for machine-readable success output; validation errors are
written to standard error and return exit code 2.

## Resume a handoff

```bash
python3 <skill-dir>/scripts/harness_ledger.py resume \
  --project-root /path/to/project
```

Resume is read-only. It validates the ledger and returns the approved contract,
current checkpoint, open issues, and recorded next steps. It does not execute
those steps.

## Run the unified Codex-native loop

`$harness` reviews and initializes the contract, reads the current
`checkpoint_sequence`, and enters one bounded run:

```bash
python3 <skill-dir>/scripts/harness_ledger.py pdca enable \
  --project-root /path/to/project \
  --expect-sequence 0 \
  --max-cycles 3 \
  --max-do-attempts 3 \
  --json
```

This creates a recoverable backup and upgrades the bootstrap ledger from schema
v1 to fail-closed schema v2. In schema v2, ordinary `checkpoint
--complete` and acceptance-linked checkpoint evidence are rejected.

The skill saves structured phase reports inside the project and records them in
order:

```bash
python3 <skill-dir>/scripts/harness_ledger.py pdca record-plan \
  --project-root /path/to/project \
  --expect-sequence 1 \
  --artifact-file .harness/reports/cycle-001-plan.json

python3 <skill-dir>/scripts/harness_ledger.py pdca record-do \
  --project-root /path/to/project \
  --expect-sequence 2 \
  --artifact-file .harness/reports/cycle-001-do.json

python3 <skill-dir>/scripts/harness_ledger.py pdca record-check \
  --project-root /path/to/project \
  --expect-sequence 3 \
  --artifact-file .harness/reports/cycle-001-check.json

python3 <skill-dir>/scripts/harness_ledger.py pdca act \
  --project-root /path/to/project \
  --expect-sequence 4 \
  --json
```

Each mutation requires the sequence returned by the previous command. Plan
must cover the exact pending acceptance scope and contract digest. Do must bind
the current Plan and emit a non-placeholder candidate revision. Check must bind
that exact revision and report every scoped criterion exactly once. Act derives
the next phase from Check; no Act model exists.

Use `pdca status` for read-only inspection, `pdca block` for a real external
blocker, and `pdca restart` only with explicit authorization. Full role prompts,
JSON shapes, sandbox modes, and retry behavior live in
[`skills/harness/SKILL.md`](skills/harness/SKILL.md).

## Migrate 2.x state

Migration is the sole mutating form of `resume`:

```bash
python3 <skill-dir>/scripts/harness_ledger.py resume \
  --project-root /path/to/project \
  --migrate
```

It recognizes the old project-root `.harness/` and the older nested
`.engineering/implementation/.harness/` location. Migration is idempotent. If
both sources exist, the command refuses to guess; select one explicitly. The
selected source must be one of those two locations inside the project root:

```bash
python3 <skill-dir>/scripts/harness_ledger.py resume \
  --project-root /path/to/project \
  --migrate \
  --source /path/to/project/.engineering/implementation/.harness
```

Without `--migrate`, `status` and `resume` fail because no current ledger is
present and leave every file unchanged.

Migration also refuses unknown future schema versions and conflicting active
references. An old `done` label becomes an evidence claim with an unknown
result, not completed acceptance; re-verify it before using `--complete`.
