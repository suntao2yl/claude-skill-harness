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
            "pattern": "^F[0-9]{3}$",
            "description": "Feature ID, format: F001, F002, etc."
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
            "type": "string",
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
            "items": { "type": "string", "pattern": "^F[0-9]{3}$" },
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
   │          └→ blocked (external dependency or unresolvable issue)
   │
   └→ skipped (user decides to skip)
```

- `pending → in_progress`: Only when all dependencies are `done`
- `in_progress → done`: Only after self-test passes AND reviewer gives PASS verdict
- `in_progress → blocked`: When an issue is discovered that requires user intervention
- `pending → skipped`: Only by explicit user request

## Verification Field Rules

The `verification` field is the most important field in the schema. Rules:

1. **Written once during INIT** — becomes the "sprint contract" for this feature
2. **Agent MUST NOT modify it** — prevents the evaluator-leniency trap
3. **Must be objectively testable** — "looks good" is NOT valid verification
4. **Specific commands preferred** — e.g., `pytest tests/test_auth.py -k test_login_flow` > `auth works`

### Good verification examples:
- `Run 'pytest tests/test_combat.py' — all tests pass including test_damage_calculation`
- `Start server, POST to /api/match/create with 2 players, verify 200 response with match_id`
- `In Godot, click tile (3,4), verify TileInfoPanel shows terrain type and movement cost`

### Bad verification examples:
- `Feature works correctly` (not testable)
- `Code looks clean` (subjective)
- `No bugs` (unfalsifiable)
