# Active Contract Schema

Use this schema when creating `.harness/contract-schema.json` or when validating `.harness/current-contract.json`.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Harness Active Contract v2",
  "type": "object",
  "required": [
    "feature_id",
    "goal",
    "scope_in",
    "scope_out",
    "verification_claims",
    "verification_commands",
    "manual_checks",
    "review_policy",
    "execution_context",
    "created_at",
    "updated_at"
  ],
  "properties": {
    "feature_id": {
      "type": "string",
      "pattern": "^F[0-9]{3,4}$"
    },
    "goal": {
      "type": "string"
    },
    "scope_in": {
      "type": "array",
      "items": { "type": "string" }
    },
    "scope_out": {
      "type": "array",
      "items": { "type": "string" }
    },
    "verification_claims": {
      "type": "array",
      "items": { "type": "string" }
    },
    "verification_commands": {
      "type": "array",
      "items": { "type": "string" }
    },
    "manual_checks": {
      "type": "array",
      "items": { "type": "string" }
    },
    "review_policy": {
      "type": "string",
      "enum": ["selftest", "qa"]
    },
    "execution_context": {
      "type": "object",
      "properties": {
        "cwd": { "type": "string", "description": "Working directory for verification commands" },
        "timeout_seconds": { "type": "integer", "default": 300, "description": "Max seconds per verification command" }
      },
      "required": ["cwd"],
      "additionalProperties": false
    },
    "created_at": {
      "type": "string"
    },
    "updated_at": {
      "type": "string"
    },
    "command_history": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "original": { "type": "string" },
          "replacement": { "type": "string" },
          "timestamp": { "type": "string" }
        }
      },
      "default": [],
      "description": "Tracks verification command refinements during implementation."
    }
  },
  "additionalProperties": true
}
```

## Rules

- The active contract is for one feature only.
- `verification_claims`, `verification_commands`, and `manual_checks` are derived from immutable `verification`.
- `scope_in` and `scope_out` are required in `standard` and `heavy` mode. They may be empty in `lite`.
- `review_policy=qa` means the reviewer prompt may load `resources/reviewer-calibration.md`.
- The contract should stay small enough to hand to another session without loading the full campaign.
- `execution_context.cwd` defines where verification commands run; defaults to `campaign.project_root`.
- `execution_context.timeout_seconds` caps how long each verification command may run (default 300s).
