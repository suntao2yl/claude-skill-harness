# Session Summary Schema

Use this schema when creating `.harness/session-summary.json`.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Harness Session Summary v2",
  "type": "object",
  "required": [
    "campaign_goal",
    "mode",
    "current_feature",
    "last_completed_feature",
    "progress_counts",
    "resume_steps",
    "known_failures",
    "environment_status",
    "last_session_date",
    "last_session_commit"
  ],
  "properties": {
    "campaign_goal": {
      "type": "string"
    },
    "mode": {
      "type": "string",
      "enum": ["lite", "standard", "heavy"]
    },
    "current_feature": {
      "type": ["string", "null"]
    },
    "last_completed_feature": {
      "type": ["string", "null"]
    },
    "progress_counts": {
      "type": "object",
      "required": ["total", "completed", "pending", "in_progress", "done", "blocked", "skipped"],
      "properties": {
        "total": { "type": "integer" },
        "completed": { "type": "integer" },
        "pending": { "type": "integer" },
        "in_progress": { "type": "integer" },
        "done": { "type": "integer" },
        "blocked": { "type": "integer" },
        "skipped": { "type": "integer" }
      },
      "additionalProperties": false
    },
    "resume_steps": {
      "type": "array",
      "items": { "type": "string" }
    },
    "known_failures": {
      "type": "array",
      "items": { "type": "string" }
    },
    "open_issues": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Open issues from the current feature's checkpoint, folded in so the hook avoids reading features.json."
    },
    "environment_status": {
      "type": "string"
    },
    "last_session_date": {
      "type": "string"
    },
    "last_session_commit": {
      "type": ["string", "null"]
    }
  },
  "additionalProperties": false
}
```

## Rules

- `session-summary.json` is the default resume source for new sessions and the session-start hook.
- `resume_steps` should be short and action-oriented.
- `known_failures` should carry only unresolved blockers or failing baseline checks.
- Keep this file compact; it replaces most of the old need to read `progress.md` at startup.
