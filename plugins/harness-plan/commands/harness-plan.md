---
description: Long-running task harness for multi-session campaigns.
argument-hint: '[goal|status|review|focus F007|add "feature description"|skip F003|reset]'
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent, EnterPlanMode, TaskCreate, TaskUpdate, TaskList, TaskGet, AskUserQuestion
---

Use the `harness-plan` skill now.

Interpret this slash command as:

```text
/harness-plan $ARGUMENTS
```

Route `$ARGUMENTS` through the skill's Command Router exactly:

- no arguments: resume the active campaign, or report that no `.harness/` campaign exists
- quoted free-form goal: start INIT for a new campaign
- `status`: run the harness summary path
- `review`: run the current feature's configured review path
- `focus F007`: focus that feature, preserving the in-progress conflict checks
- `add "feature description"`: add a feature and refresh the summary
- `skip F003`: mark that feature skipped through the transition script
- `reset`: archive and clean only through the reset flow

Do not answer with generic usage text. Execute the routed workflow in the current repository.
