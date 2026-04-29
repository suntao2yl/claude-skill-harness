# Features JSON Schema

Use this schema when creating `.harness/features-schema.json`.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Harness Feature List v2",
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
            "pattern": "^F[0-9]{3,4}$"
          },
          "name": {
            "type": "string",
            "maxLength": 80
          },
          "description": {
            "type": "string"
          },
          "verification": {
            "oneOf": [
              { "type": "string" },
              {
                "type": "object",
                "properties": {
                  "command": { "type": "string" },
                  "manual_check": { "type": "string" },
                  "expected": { "type": "string" }
                },
                "additionalProperties": false
              }
            ],
            "description": "IMMUTABLE after INIT unless the user changes it."
          },
          "status": {
            "type": "string",
            "enum": ["backlog", "pending", "in_progress", "done", "blocked", "skipped"]
          },
          "priority": {
            "type": "integer",
            "minimum": 1,
            "maximum": 5
          },
          "complexity": {
            "type": ["string", "null"],
            "enum": ["small", "medium", "large", null],
            "default": null,
            "description": "Optional size estimate. Small features get lite contracts in standard mode."
          },
          "dependencies": {
            "type": "array",
            "items": {
              "type": "string",
              "pattern": "^F[0-9]{3,4}$"
            },
            "default": []
          },
          "change_units": {
            "type": "array",
            "default": [],
            "description": "Optional sub-feature breakdown (Phase 4+). Only populated in standard/deep mode for non-trivial features. A feature transitions to done only when all its change_units are 'archived'.",
            "items": {
              "type": "object",
              "required": ["id", "title", "state"],
              "properties": {
                "id": {
                  "type": "string",
                  "pattern": "^CHG-[0-9]{3,}$"
                },
                "title": { "type": "string" },
                "state": {
                  "type": "string",
                  "enum": ["proposed", "speccing", "verifying", "archived"]
                },
                "spec_path": { "type": ["string", "null"] },
                "verification_evidence": { "type": ["string", "null"] },
                "files_touched": {
                  "type": "array",
                  "items": { "type": "string" },
                  "default": []
                }
              }
            }
          },
          "sessions": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "note": { "type": "string" },
                "timestamp": { "type": "string" }
              },
              "required": ["note", "timestamp"],
              "additionalProperties": false
            },
            "default": []
          },
          "blocked_reason": {
            "type": ["string", "null"],
            "default": null
          },
          "checkpoint": {
            "type": ["object", "null"],
            "default": null,
            "properties": {
              "completed_steps": {
                "type": "array",
                "items": { "type": "string" }
              },
              "next_step": {
                "type": "string"
              },
              "open_issues": {
                "type": "array",
                "items": { "type": "string" }
              },
              "files_touched": {
                "type": "array",
                "items": { "type": "string" }
              },
              "tests_run": {
                "type": "array",
                "items": { "type": "string" }
              },
              "last_updated": {
                "type": "string"
              },
              "last_verified_commit": {
                "type": ["string", "null"]
              },
              "selftest_retries": {
                "type": "integer",
                "default": 0,
                "description": "Number of consecutive self-test failures. Auto-block at 3."
              },
              "checkpoint_writes": {
                "type": "integer",
                "default": 0,
                "description": "Number of checkpoint writes in this feature. Used for session freshness signals."
              },
              "last_failure": {
                "type": ["object", "null"],
                "default": null,
                "description": "Structured record of the most recent selftest failure.",
                "properties": {
                  "command": { "type": "string" },
                  "error_summary": { "type": "string" },
                  "affected_files": { "type": "array", "items": { "type": "string" } },
                  "timestamp": { "type": "string" }
                }
              },
              "verification_runs": {
                "type": "integer",
                "default": 0,
                "description": "Number of quick-verify runs during implementation."
              },
              "manual_checks_completed": {
                "type": "array",
                "items": { "type": "string" },
                "default": [],
                "description": "Manual checks from the contract that have been verified."
              }
            },
            "required": [
              "completed_steps",
              "next_step",
              "open_issues",
              "files_touched",
              "tests_run",
              "last_updated",
              "last_verified_commit"
            ],
            "additionalProperties": true
          },
          "acceptance_checklist": {
            "type": ["array", "null"],
            "items": { "type": "string" },
            "default": null,
            "description": "Optional in lite mode; expected in standard and heavy mode."
          },
          "blocked_history": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "reason": { "type": "string" },
                "timestamp": { "type": "string" },
                "diagnostic": {
                  "type": ["object", "null"],
                  "properties": {
                    "command": { "type": ["string", "null"] },
                    "output": { "type": ["string", "null"] },
                    "suggested_fix": { "type": ["string", "null"] }
                  }
                }
              },
              "required": ["reason", "timestamp"]
            },
            "default": [],
            "description": "Capped at 10 most recent entries."
          },
          "archived_contract": {
            "type": ["object", "null"],
            "default": null,
            "description": "Snapshot of the contract at completion."
          }
        },
        "additionalProperties": false
      }
    }
  }
}
```

## v2 Notes

- `checkpoint_notes` is removed in favor of a structured `checkpoint` object.
- `progress.md` is no longer a required resume source.
- Scripts may migrate legacy `checkpoint_notes` into `checkpoint` on first write.

## Verification Rules

1. Write `verification` once during INIT.
2. Keep it objectively testable.
3. Do not weaken it to match implementation gaps.
4. Put extra implementation detail in `acceptance_checklist` or `current-contract.json`, not in `verification`.

## Good Examples

- `Run "pytest tests/test_auth.py -k test_login_flow" and confirm it passes.`
- `{ "command": "npx playwright test tests/auth.spec.ts", "manual_check": "Login redirects to /dashboard", "expected": "All tests pass and the redirect succeeds" }`

## Bad Examples

- `Feature works correctly`
- `Looks good`
- `No bugs`
