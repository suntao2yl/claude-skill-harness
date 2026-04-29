# harness-plan — Examples

## Resume a campaign and complete a feature

```text
User: /harness-plan

→ Startup Rules:
  1. harness_validate.py — state valid
  2. campaign.json: goal="Add CSV export to the dashboard"
  3. session-summary.json: current_feature=F002 "CSV download button"
  4. current-contract.json: next_step="wire the download handler to the export API"

→ CONTINUE phase:
  - Resume from checkpoint.next_step
  - Implement the download handler
  - harness_checkpoint.py --quick-verify (campaign test_command passes)

→ Self-Test:
  - campaign test_command: pytest tests/ → pass
  - verification_commands: pytest tests/test_csv_export.py -k download → pass
  - Update checkpoint with tests_run

→ Completion:
  - harness_transition.py --feature-id F002 --to done
  - harness_summary.py — 3/5 features done
  - Append progress.md entry

→ PICK next feature:
  - harness_pick_next.py — selects F003 "CSV column selector"
  - harness_transition.py --feature-id F003 --to in_progress
  - harness_contract.py --feature-id F003 — new contract
  - Start implementation immediately
```

## Autodrive: complete and hand off

```text
[autodrive enabled, .harness/autodrive.json.enabled = true]

→ Self-Test passes for F004
→ harness_transition.py --feature-id F004 --to done
→ harness_summary.py — 4/5 features done
→ git add -A
→ git commit -m "feat(harness): complete F004 - CSV column selector"
→ Print: [autodrive] feature F004 complete; ending session
→ End response. Stop hook spawns next session.
```

## Autodrive: trip fail marker on unresolvable state

```text
[autodrive enabled]

→ Encounter migration conflict that needs user input
→ python3 ${CLAUDE_SKILL_DIR}/scripts/harness_autodrive.py \
    --project-root . --fail \
    --reason "Migration 0042 conflicts with feature F005's schema change; needs human decision."
→ End session. Stop hook stops the chain.
```

## Standard mode: feature broken into change units

```text
PICK F006 "Add tagging system" — too large for one commit.

→ harness_change.py propose --feature-id F006 --title "Tag model + migration" --reason "..."
→ /change-spec --change-id CHG-001 --output .harness/changes/CHG-001/spec.md
→ harness_change.py to-spec --change-id CHG-001 --spec-path .harness/changes/CHG-001/spec.md
→ Implement
→ /completion-verify --contract .harness/changes/CHG-001/contract.json > .harness/changes/CHG-001/verify.json
→ harness_change.py to-verify ...
→ harness_change.py archive --change-id CHG-001 --files-touched models/tag.py migrations/0042.sql

[Repeat propose→archive for CHG-002 "Tag CRUD endpoints", CHG-003 "Tag UI selector".]

When all archived → feature Self-Test → F006 done.
```
