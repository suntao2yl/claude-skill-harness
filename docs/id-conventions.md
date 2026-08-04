# ID Conventions

Only acceptance criteria need stable ids in the 3.0 ledger.

## Acceptance ids

For new contracts, prefer `A` followed by at least three digits:

```text
A001
A002
A0100
```

Rules:

1. An id must match `[A-Za-z0-9][A-Za-z0-9._-]{0,63}` and be unique within one
   `.harness/ledger.json`; `A001`, `A002`, and so on are the recommended form.
2. Keep the id after completion or migration. An approved criterion is not
   edited in place.
3. Never reuse a removed id.
4. Preserve gaps; they are part of the audit history.
5. Checkpoint evidence refers to acceptance ids, not criterion text.

## Historical ids

Older migrated state retains valid legacy ids when that is necessary to
preserve traceability. Migration must not silently renumber a criterion.
