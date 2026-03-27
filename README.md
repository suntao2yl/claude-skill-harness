# claude-skill-harness

[English](README.md) | [中文](README.zh-CN.md)

A Claude Code skill for orchestrating long-running, multi-session development campaigns.

Built on insights from Anthropic Engineering research:
- [Harness Design for Long-Running Apps](https://www.anthropic.com/engineering/harness-design-long-running-apps)
- [Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)

## What it solves

| Problem | Mechanism |
|---------|-----------|
| Cross-session amnesia | File-driven state in `.harness/` + session start protocol |
| Self-evaluation leniency bias | Physically separated reviewer agent with calibrated skepticism |
| Premature "victory declaration" | Immutable verification contracts in `features.json` |
| Context anxiety / rushed completion | One-feature-at-a-time discipline + mandatory checkpoint |
| New session doesn't know what happened | `campaign.json` + `progress.md` + git log triple recovery |
| Session interrupted mid-feature | Structured `checkpoint_notes` for reliable recovery |
| Dev environment not ready | `setup_command` auto-detected and run at session start |
| Context degradation in long sessions | Session boundary guidelines + checkpoint-based handoff |
| Feature stuck in review loop | Blocked feature flow — 3 strikes, block and move on |
| One-size-fits-all overhead | Complexity adaptation — lite/standard/heavy modes |

## Install

```bash
npx skills add suntao2yl/claude-skill-harness
```

## Usage

```bash
# Start a new campaign
/harness "implement multiplayer battle system"

# Resume in a new session (auto-detects phase)
/harness

# Manual QA review
/harness review

# Check progress
/harness status

# Add a feature mid-campaign
/harness add "spectator mode for matches"

# Skip a feature
/harness skip F003

# Reset campaign
/harness reset
```

## How it works

```
/harness sits above plan mode in the abstraction hierarchy:

  CLAUDE.md → /harness → plan mode → task list
  (rules)    (campaign)  (one task)   (steps)
```

### Campaign lifecycle

```
INIT → PICK feature → plan → implement → self-test → review → checkpoint → PICK next
                                 │                      ↑
                          update checkpoint_notes   Separate agent context
                          periodically              with calibrated skepticism
```

### Key files created

```
.harness/
├── campaign.json          # Campaign metadata, session tracking, and current state
├── features.json          # Feature list with immutable verification contracts
├── features-schema.json   # JSON Schema for validation
├── progress.md            # Human-readable session log
└── archive/               # Archived past campaigns
```

## Key features

### Structured session recovery
Each in-progress feature tracks `checkpoint_notes` — completed steps, next action, open issues. When a session resumes, CONTINUE phase reads these notes for reliable handoff instead of guessing from git diff alone.

### Environment setup automation
`campaign.json` stores a `setup_command` (e.g., `npm run dev`, `docker compose up -d`). Every session start executes it before running tests, ensuring the dev environment is ready.

### Browser/E2E testing integration
When browser testing tools (Playwright MCP, Puppeteer MCP) are available, both self-test and review phases use them to verify user-facing behavior visually — testing as a human user would.

### Acceptance checklist
During PICK phase, the immutable `verification` is expanded into a detailed `acceptance_checklist` — concrete checkable items informed by the implementation plan. The reviewer checks both.

### Blocked feature flow
When a feature fails 3 review cycles or hits an external blocker, it's marked `blocked` with a reason. The campaign moves on to the next unblocked feature instead of getting stuck.

### Complexity adaptation
Campaign `mode` (lite/standard/heavy) is set based on feature count, adjusting ceremony level. Small campaigns skip schema generation; large ones add milestone integration checks.

### Session boundary guidelines
Checkpoints are natural session boundaries. The harness suggests breaks at the right moments and ensures all state is preserved for the next session.

## Design principles

1. **File-driven state** — All cross-session state lives in `.harness/`, never in conversation memory
2. **Role separation** — Implementer and reviewer are physically separate agent contexts
3. **One feature at a time** — Complete, test, checkpoint, then move on
4. **JSON for machine state** — Resists accidental modification better than Markdown
5. **Immutable verification** — Feature acceptance criteria are locked at creation; agents cannot weaken them
6. **Calibrated skepticism** — Reviewer prompt explicitly counters the documented leniency bias
7. **Graceful degradation** — Blocked features don't stall the campaign; context breaks don't lose progress

## License

MIT
