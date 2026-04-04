# Session Protocol

Use this file for startup and resume. Keep the startup sequence compact and repeatable.

## Resume Order

1. Run `pwd`.
2. Run `python3 scripts/harness_validate.py`.
3. Read `.harness/campaign.json`.
4. Read `.harness/session-summary.json`.
5. Read the active feature from `.harness/features.json` if `campaign.current_feature` is set.
6. Read `.harness/current-contract.json` if it exists.
7. Only `tail` `.harness/progress.md` when structured files are missing or disagree.

## Environment Bootstrap

Use this order:

1. `campaign.bootstrap_command`
2. `campaign.setup_command`
3. `./.harness/init.sh` if the campaign created one

If no bootstrap command exists, report that clearly instead of guessing.

## Baseline Verification

Prefer one quick smoke check before the full suite.

Suggested order:

1. Run the bootstrap command.
2. Run one smoke check that proves the environment is alive.
3. Run the full test suite only when:
   - the smoke check fails
   - `campaign.baseline_status` is `failing`
   - the prior session ended with known failures

Update `campaign.baseline_status` and refresh `session-summary.json` after baseline checks.

## Resume Artifact Priority

When deciding what happened last session, trust files in this order:

1. `.harness/session-summary.json`
2. `.harness/current-contract.json`
3. `feature.checkpoint` in `.harness/features.json`
4. recent lines from `.harness/progress.md`

Do not reconstruct the entire campaign from the Markdown log unless the machine files are broken.

## Reviewer Input Budget

When review policy is `qa`, keep reviewer context small. Pass only:

- goal
- current feature metadata
- immutable verification
- active contract
- changed files
- exact test outputs
- one UI route or API route if relevant

Never pass the full feature list or whole progress log to the reviewer.
