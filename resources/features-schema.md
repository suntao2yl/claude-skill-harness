# Features JSON Schema

Use this schema when creating `.harness/features-schema.json` during campaign initialization.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Harness Feature List",
  "description": "Machine-owned feature tracking for campaign orchestration. Verification fields are IMMUTABLE once created — only the user may modify them.",
  "type": "object",
  "required": ["features"],
  "properties": {
    "features": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "name", "description", "verification", "status", "priority"],
        "properties": {
          "id": {
            "type": "string",
            "pattern": "^F[0-9]{3,4}$",
            "description": "Feature ID, format: F001, F002, ... F9999"
          },
          "name": {
            "type": "string",
            "maxLength": 80,
            "description": "Short imperative title"
          },
          "description": {
            "type": "string",
            "description": "What this feature does and why it matters"
          },
          "verification": {
            "oneOf": [
              {
                "type": "string",
                "description": "Simple verification: a single testable statement"
              },
              {
                "type": "object",
                "description": "Structured verification for complex or E2E checks",
                "properties": {
                  "command": {
                    "type": "string",
                    "description": "Test command to run"
                  },
                  "manual_check": {
                    "type": "string",
                    "description": "Human-readable behavior to verify (browser, UI, etc.)"
                  },
                  "expected": {
                    "type": "string",
                    "description": "Expected outcome"
                  }
                },
                "additionalProperties": false
              }
            ],
            "description": "IMMUTABLE. Concrete test criteria. Must be objectively verifiable. DO NOT MODIFY after creation."
          },
          "status": {
            "type": "string",
            "enum": ["pending", "in_progress", "done", "blocked", "skipped"],
            "description": "Current feature status"
          },
          "priority": {
            "type": "integer",
            "minimum": 1,
            "maximum": 5,
            "description": "1=highest, 5=lowest"
          },
          "dependencies": {
            "type": "array",
            "items": { "type": "string", "pattern": "^F[0-9]{3,4}$" },
            "default": [],
            "description": "Feature IDs that must be done before this one"
          },
          "sessions": {
            "type": "array",
            "items": { "type": "string" },
            "default": [],
            "description": "Session log entries recording work done"
          },
          "blocked_reason": {
            "type": "string",
            "description": "Why this feature is blocked (only when status=blocked)"
          },
          "checkpoint_notes": {
            "type": ["string", "null"],
            "default": null,
            "description": "Structured recovery notes for in_progress features. Updated periodically during implementation. Records: completed steps, next action, open issues. Enables reliable session handoff."
          },
          "acceptance_checklist": {
            "type": ["array", "null"],
            "items": { "type": "string" },
            "default": null,
            "description": "Detailed checklist expanding the immutable verification into concrete checkable items. Generated during PICK phase after plan approval. Does NOT replace verification — supplements it."
          }
        },
        "additionalProperties": false
      }
    }
  }
}
```

## Status Transitions

```
pending → in_progress → done
   │          │
   │          ├→ blocked (3 failed review cycles, external dependency, or unresolvable issue)
   │          │     └→ pending (when blocker is resolved, re-enters queue)
   │          │
   │          └→ (mid-session interrupt: stays in_progress with checkpoint_notes for recovery)
   │
   └→ skipped (user decides to skip)
```

- `pending → in_progress`: Only when all dependencies are `done`
- `in_progress → done`: Only after self-test passes AND reviewer gives PASS verdict
- `in_progress → blocked`: When an issue cannot be resolved after 3 attempts or requires external intervention
- `blocked → pending`: When the user confirms the blocker is resolved
- `pending → skipped`: Only by explicit user request

## Verification Field Rules

The `verification` field is the most important field in the schema. Rules:

1. **Written once during INIT** — becomes the "sprint contract" for this feature
2. **Agent MUST NOT modify it** — prevents the evaluator-leniency trap
3. **Must be objectively testable** — "looks good" is NOT valid verification
4. **Specific commands preferred** — e.g., `pytest tests/test_auth.py -k test_login_flow` > `auth works`
5. **Supports two formats** — simple string for straightforward checks, structured object for E2E or multi-step verification

### Good verification examples:
- `Run 'pytest tests/test_combat.py' — all tests pass including test_damage_calculation`
- `Start server, POST to /api/match/create with 2 players, verify 200 response with match_id`
- `In Godot, click tile (3,4), verify TileInfoPanel shows terrain type and movement cost`
- `{ "command": "npx playwright test tests/auth.spec.ts", "manual_check": "Login page renders, form submits, redirects to dashboard", "expected": "All tests pass" }`

### Bad verification examples:
- `Feature works correctly` (not testable)
- `Code looks clean` (subjective)
- `No bugs` (unfalsifiable)

## Checkpoint Notes Format

When updating `checkpoint_notes` during implementation, use this structure:

```
Completed: [list of done steps]
Next: [what to do next]
Issues: [any open problems or blockers]
```

This is free-form text, not parsed programmatically, but following a consistent format helps future sessions recover quickly.
