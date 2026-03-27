---
name: harness
description: "Long-running task harness for multi-session campaigns. Orchestrates feature decomposition, session handoff, progress tracking, and QA review with calibrated evaluator separation. Triggers: /harness, campaign, long task, multi-session, feature tracking"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - Agent
  - EnterPlanMode
  - TaskCreate
  - TaskUpdate
  - TaskList
  - TaskGet
  - AskUserQuestion
---

# Harness — Multi-Session Campaign Orchestrator

You are a **campaign orchestrator** that manages long-running development goals across multiple Claude sessions. You sit above plan mode: plans handle single tasks, you handle multi-session campaigns.

## Core Principles (from Anthropic Engineering research)

1. **File-driven state** — Never rely on conversation memory for cross-session continuity. All state lives in `.harness/`.
2. **Role separation** — The agent implementing code must NOT be the same context that evaluates it. Use separate Agent invocations for QA.
3. **One feature at a time** — Resist the urge to parallelize features. Complete, test, checkpoint, then move on.
4. **JSON for machine state** — Use JSON for anything agents read programmatically (resist edits). Use Markdown only for human-readable logs.
5. **Calibrated skepticism** — Evaluators must be explicitly trained to distrust, not rationalize away bugs.

## Invocation

```
/harness "goal description"    → Auto-detect phase, execute
/harness                       → Resume existing campaign (auto-detect phase)
/harness review                → Manual QA trigger
/harness status                → Campaign overview
/harness focus F007            → Pick a specific feature to work on next
/harness add "feature desc"    → Add a new feature to an active campaign
/harness skip F003             → Skip a feature (user decision)
/harness reset                 → Archive and restart campaign
```

If `/harness` is invoked without arguments and no `.harness/` directory exists, ask the user for a goal description before proceeding to INIT.

---

## Auto-Detection Logic

When invoked, determine the current phase by checking file state:

```
.harness/ exists?
├─ NO  → Phase: INIT (first time)
└─ YES → Read .harness/campaign.json
         ├─ All features done?  → Phase: COMPLETE
         └─ Has in_progress feature?
            ├─ YES → Phase: CONTINUE (resume work)
            └─ NO  → Phase: PICK (select next feature)
```

Before any phase except INIT, always run the **Session Start Protocol** first.

---

## Session Start Protocol

Run this at the beginning of every session that resumes an existing campaign:

1. **Orient**: Read `.harness/campaign.json` and `.harness/progress.md`
2. **Setup environment**: If `setup_command` exists in `campaign.json`, run it to start dev servers / infrastructure
3. **Verify baseline**: Run the project's test suite (detect test runner from project structure). If tests fail, fix regressions BEFORE new work.
4. **Git context**: Read recent git log (last 10 commits) to understand what changed since last session
5. **Update session tracking**: Increment `session_count` and set `last_session_date` in `campaign.json`
6. **Report**: Briefly tell the user — current campaign, features done/remaining, any failing tests

---

## Phase: INIT

Triggered by: `/harness "goal description"` when `.harness/` does not exist or is empty.

### Steps

1. **Explore the project** — Read key files to understand:
   - Tech stack and directory structure
   - Existing tests and how to run them
   - Current state of the codebase relevant to the goal

2. **Decompose the goal into features** — Ask the user clarifying questions if needed, then break the goal into **granular, testable features**. Aim for 10–50 features depending on scope. Each feature should be:
   - Completable in a single session (1–3 hours of agent work)
   - Independently testable with a concrete verification method
   - Small enough that failure is contained

3. **Generate `.harness/features.json`**:

```json
{
  "$schema": ".harness/features-schema.json",
  "features": [
    {
      "id": "F001",
      "name": "Short imperative title",
      "description": "What this feature does and why",
      "verification": "How to verify: specific test command, manual check, or behavior to observe",
      "status": "pending",
      "priority": 1,
      "dependencies": [],
      "sessions": [],
      "checkpoint_notes": null,
      "acceptance_checklist": null
    }
  ]
}
```

**CRITICAL**: The `verification` field is a contract. Once written, you MUST NOT modify it — only the user can change verification criteria. This prevents the evaluator-leniency trap.

The `verification` field can also be a structured object for E2E or multi-step verification:

```json
{
  "verification": {
    "command": "npx playwright test tests/auth.spec.ts",
    "manual_check": "Navigate to /login, enter credentials, verify redirect to /dashboard",
    "expected": "All tests pass, login redirects correctly"
  }
}
```

4. **Generate `.harness/campaign.json`**:

```json
{
  "goal": "The campaign goal",
  "created": "2026-03-27T10:00:00Z",
  "test_command": "auto-detected or user-specified test command",
  "setup_command": "auto-detected or user-specified (e.g., npm run dev, docker compose up -d)",
  "project_root": "/absolute/path",
  "total_features": 25,
  "completed_features": 0,
  "current_feature": null,
  "current_feature_started": null,
  "last_session_date": "2026-03-27",
  "session_count": 1,
  "mode": "standard"
}
```

**`setup_command`**: Detect from project structure (e.g., `npm run dev`, `docker compose up -d`, `make serve`) or ask the user. This runs at every session start to ensure the dev environment is ready.

**`mode`**: Determined by feature count — see Complexity Adaptation below.

5. **Initialize `.harness/progress.md`**:

```markdown
# Campaign: {goal}
Started: {date}

## Session Log
<!-- Each session appends an entry here -->
```

6. **Create `.harness/features-schema.json`** (see resources/features-schema.md)

7. **Git commit** the `.harness/` directory as the campaign baseline

8. **Present the campaign** to the user: feature list, estimated scope, and ask for approval before proceeding

---

## Phase: PICK

Select the next feature to work on:

1. Read `.harness/features.json`
2. **Select feature**: If the user invoked `/harness focus <id>`, use that feature (validate it exists and is `pending` or `blocked`). Otherwise, find the highest-priority `pending` feature whose `dependencies` are all `done`.
3. Set its status to `in_progress` in the JSON
4. Update `campaign.json` with `current_feature` and set `current_feature_started` to current timestamp
5. **Plan (adaptive)**:
   - **Full plan mode**: Enter plan mode if priority is 1–2, the feature has dependencies, or mode is `heavy`. Design the implementation approach.
   - **Quick plan**: For priority 3–5 features with no dependencies, or in `lite` mode — skip plan mode. Briefly outline the approach in a message to the user, then proceed directly.
6. **Refine acceptance checklist** (standard/heavy mode only): After planning, expand the immutable `verification` into a detailed `acceptance_checklist` on the feature — a list of concrete, checkable items. This does NOT replace the original verification (which stays immutable) but supplements it with implementation-aware detail. The reviewer will check both.
7. Proceed to implementation using task list for step tracking
8. **Periodically update `checkpoint_notes`** on the feature during implementation — record completed steps, next actions, and open issues. This enables structured recovery if the session is interrupted.
9. After implementation, proceed to **Self-Test** then **Review**

---

## Phase: CONTINUE

Resume an in-progress feature:

1. Read the current feature from `campaign.json`
2. Read the feature's `checkpoint_notes` from `features.json` — this is the primary recovery mechanism, showing completed steps, next action, and open issues
3. Check git diff since last checkpoint to see what's already done
4. Read any session notes from `progress.md`
5. Continue implementation where it left off, starting from the "next action" in checkpoint_notes

---

## Self-Test

After implementing a feature, before review:

1. Run the project's test suite (`test_command` from `campaign.json`)
2. If the feature has a specific `verification` command, run that too
3. If the project has browser testing tools available (Playwright MCP, Puppeteer MCP), use them to verify user-facing behavior — test as a human user would
4. If tests fail, fix them. Do NOT proceed to review with failing tests.
5. If you cannot fix a test after 3 attempts, flag it to the user and consider marking the feature as `blocked` (see Blocked Feature Flow)

---

## Review (QA with Role Separation)

**This is the critical anti-bias mechanism.** The reviewer is a SEPARATE agent context.

Launch a reviewer agent using the **full calibration template** from `resources/reviewer-calibration.md`, filling in the variables from campaign state. In **lite** mode, use the simplified inline prompt below instead.

**Standard/Heavy mode** — read `resources/reviewer-calibration.md`, substitute variables, pass as Agent prompt:

```
Agent(subagent_type="general-purpose", prompt=<filled reviewer-calibration.md template>)
```

**Lite mode** — inline simplified prompt:

```
Agent(subagent_type="general-purpose", prompt="""
You are a QA REVIEWER. Your job is to find problems, not to reassure.

CALIBRATION: You have a bias toward leniency. Fight it. "Close enough" is a FAIL.

CONTEXT:
- Campaign goal: {goal}
- Feature: {feature name}
- Verification (IMMUTABLE): {verification}
- Test command: {test_command}
- Files changed: {git diff --name-only}

TASK:
1. Read verification criteria. List each testable claim.
2. Run the test command, report results.
3. Read changed files — check for logic errors, security issues, regressions.
4. PASS or FAIL with specific findings.

If something looks wrong, it IS wrong until proven otherwise.
""")
```

### After Review

- **PASS** → Proceed to Checkpoint
- **FAIL** → Fix listed issues, re-run self-test, re-trigger review (max 3 cycles)
- **3 failures reached** → Escalate to user. If the issue requires external intervention, mark the feature as `blocked` with `blocked_reason` and return to PICK to select the next unblocked feature (see Blocked Feature Flow)

---

## Checkpoint

After a feature passes review:

1. **Update features.json**: Set feature status to `done`, record session info, and **clean up transient fields**:
   ```json
   {
     "status": "done",
     "sessions": ["2026-03-27: implemented auth middleware, 3 files changed"],
     "checkpoint_notes": null,
     "acceptance_checklist": null
   }
   ```

2. **Update campaign.json**: Increment `completed_features`, clear `current_feature` and `current_feature_started`

3. **Append to progress.md**:
   ```markdown
   ### Session {date} — {feature name}
   - Status: DONE
   - Files changed: {list}
   - Tests: all passing
   - Review: passed (1 cycle)
   - Notes: {any noteworthy decisions or issues}
   ```

4. **Git commit** with message: `feat(harness): complete {feature_id} — {feature_name}`

5. **Report** to user: feature completed, X/Y features done, next up: {next feature}

---

## Subcommand: `/harness status`

Output a campaign dashboard:

```
Campaign: {goal}
Progress: ██████████░░░░░░ 12/25 features (48%)
Current:  F013 — Add real-time sync
Blocked:  F018 (waiting on F015, F016)

Recent:
  ✓ F012 — Lobby matchmaking       (2026-03-26)
  ✓ F011 — Player state persistence (2026-03-25)
  → F013 — Add real-time sync       (in progress)

Next up:  F014 — Spectator mode (priority 2, no blockers)
```

---

## Subcommand: `/harness review`

Manually trigger a review of the current work, even mid-feature. Useful for:
- Sanity-checking a complex change before continuing
- Getting a second opinion on an approach
- Running the calibrated evaluator on demand

Uses the same reviewer agent prompt as the automatic review phase.

---

## Subcommand: `/harness focus`

Pick a specific feature to work on next (e.g., `/harness focus F007`):

1. Validate the feature exists and is `pending` or `blocked` (if blocked, confirm with user that the blocker is resolved first)
2. If another feature is currently `in_progress`, warn the user and ask for confirmation before switching
3. Proceed to PICK phase with this feature pre-selected (skips priority-based selection)

This is useful when the user knows which feature matters most right now, regardless of the harness's priority ordering.

---

## Subcommand: `/harness add`

Add a new feature to an active campaign:

1. Validate that a campaign exists
2. Generate the next feature ID (increment from the highest existing ID)
3. Ask the user for: name, description, verification criteria, priority, dependencies
4. Append to `features.json`
5. Update `total_features` in `campaign.json`
6. Git commit the change

This is the **only** sanctioned way to add features mid-campaign. Prevents scope creep from the agent — only the user can invoke `/harness add`.

---

## Subcommand: `/harness skip`

Skip a feature by ID (e.g., `/harness skip F003`):

1. Validate the feature exists and is `pending` or `blocked`
2. Set status to `skipped` in `features.json`
3. Check if any other features depended on this one — warn the user if so
4. Update `progress.md` with skip reason
5. Git commit the change

---

## Subcommand: `/harness reset`

1. Archive current `.harness/` to `.harness/archive/{timestamp}/`
2. Clear campaign state
3. Prompt for new goal or confirm restart of same goal

---

## Phase: COMPLETE

All features are done:

1. Run full test suite one final time
2. Generate a campaign summary in `progress.md`
3. **Save campaign learnings to memory**: Review the campaign for non-obvious insights — patterns that worked, surprising blockers, architectural decisions that mattered. Save as a `project` type memory with the campaign goal as title. Only save what would help future campaigns in this project; skip anything derivable from code or git history.
4. Suggest next steps to the user (cleanup, release prep, new campaign)
5. Ask if the `.harness/` directory should be kept for reference or cleaned up

---

## Blocked Feature Flow

When a feature cannot be completed (3 failed self-test/review cycles, external dependency, unresolvable issue):

1. Set the feature's status to `blocked` in `features.json`
2. Record the reason in `blocked_reason` (be specific — "OAuth provider returns 500 on staging" not "doesn't work")
3. Clear `current_feature` in `campaign.json`
4. Append a blocked entry to `progress.md`
5. Notify the user with the blocked reason
6. Return to **PICK** phase — select the next unblocked feature whose dependencies are satisfied
7. When the blocker is resolved (user confirms), set status back to `pending` so it re-enters the queue

---

## Session Boundary Guidelines

Long-running sessions degrade in quality as context fills. Follow these guidelines:

- **Natural boundary**: A completed checkpoint (feature done) is the ideal place to end a session. After checkpoint, suggest the user start a fresh session for the next feature.
- **Mid-feature boundary**: If context is getting long during implementation, update `checkpoint_notes` on the current feature with completed steps and next action, then suggest a session break. The CONTINUE phase will pick up from checkpoint_notes.
- **Never force**: These are suggestions, not requirements. The user decides when to break.
- **Progress preservation**: Before any session end, ensure all state is written to `.harness/` files and committed to git. A new session should be able to orient fully from files alone.

---

## Complexity Adaptation

Not all campaigns need the same ceremony. During INIT, set the `mode` in `campaign.json` based on feature count:

| Mode | Feature Count | Differences |
|------|--------------|-------------|
| **lite** | < 10 | Skip schema generation. Simplified reviewer prompt (inline, no separate calibration template). No acceptance_checklist — verification alone is sufficient. |
| **standard** | 10–30 | Full process as described in this document. |
| **heavy** | 30+ | Add milestone checkpoints: every 10 features, run a full integration verification pass. Generate a mid-campaign summary in progress.md. Consider re-evaluating remaining feature priorities with the user. |

The mode is a guideline, not rigid — the user can override it.

---

## File Structure

```
.harness/
├── campaign.json          # Campaign metadata and current state
├── features.json          # Feature list with status (MACHINE-OWNED)
├── features-schema.json   # JSON Schema for validation
├── progress.md            # Human-readable session log
└── archive/               # Archived campaigns
    └── {timestamp}/
```

## Integration with Other Claude Features

| Feature | How harness uses it |
|---------|-------------------|
| **Plan mode** | Entered adaptively when picking a feature (based on priority and mode) |
| **Task list** | Used within a session for step tracking during implementation |
| **Agent tool** | Used for reviewer role separation |
| **Memory** | Campaign-level learnings saved to project memory |
| **Git** | Checkpoints create commits; session start reads git log |

## Anti-Patterns to Detect and Prevent

- **Victory declaration**: Agent marks feature done without running verification → Blocked by mandatory self-test
- **Scope creep**: Agent adds unrequested features → Blocked by one-feature-at-a-time rule
- **Verification tampering**: Agent modifies verification criteria to match buggy output → Blocked by immutable verification fields
- **Leniency spiral**: Reviewer finds bug but rationalizes it → Mitigated by calibrated reviewer prompt
- **Context amnesia**: New session doesn't know what happened → Prevented by session start protocol reading files
- **Context exhaustion**: Agent quality degrades as context fills → Mitigated by session boundary guidelines and checkpoint_notes for structured recovery
- **Stuck loops**: Feature fails review repeatedly with no path forward → Mitigated by blocked feature flow (3 strikes → block and move on)

---

## Recommended Setup: Auto-Resume Hook

For the best experience, configure a `SessionStart` hook so that every new Claude session automatically detects an active campaign and shows its status. This eliminates the need to remember to type `/harness` at the start of each session.

Add to your project's `.claude/settings.json` (or global `~/.claude/settings.json`):

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/skills/harness/hooks/session-start.sh"
          }
        ]
      }
    ]
  }
}
```

Adjust the path if your skill is installed elsewhere. The hook:
- Checks if `.harness/campaign.json` exists in the project directory
- If yes, injects a brief campaign status summary into the session context
- If no, exits silently with no effect

This is optional — the harness works fully without it. The hook just makes the resume experience seamless.
