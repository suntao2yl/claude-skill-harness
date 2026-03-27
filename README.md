# claude-skill-harness

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
| Context anxiety → rushed completion | One-feature-at-a-time discipline + mandatory checkpoint |
| New session doesn't know what happened | `campaign.json` + `progress.md` + git log triple recovery |

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
                                                        ↑
                                              Separate agent context
                                              with calibrated skepticism
```

### Key files created

```
.harness/
├── campaign.json          # Campaign metadata and current state
├── features.json          # Feature list with immutable verification contracts
├── features-schema.json   # JSON Schema for validation
├── progress.md            # Human-readable session log
└── archive/               # Archived past campaigns
```

## Design principles

1. **File-driven state** — All cross-session state lives in `.harness/`, never in conversation memory
2. **Role separation** — Implementer and reviewer are physically separate agent contexts
3. **One feature at a time** — Complete, test, checkpoint, then move on
4. **JSON for machine state** — Resists accidental modification better than Markdown
5. **Immutable verification** — Feature acceptance criteria are locked at creation; agents cannot weaken them
6. **Calibrated skepticism** — Reviewer prompt explicitly counters the documented leniency bias

## License

MIT
