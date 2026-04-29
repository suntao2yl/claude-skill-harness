#!/usr/bin/env bash
# Harness autodrive Stop hook.
# Delegates to harness_autodrive.py --decide. Always exits 0 so a failure
# inside the helper never blocks Claude Code from shutting down.

set +e

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Quick gate: if there is no autodrive config in this project, do nothing.
if [ ! -f "${PROJECT_DIR}/.harness/autodrive.json" ]; then
  exit 0
fi

# CLAUDE_PLUGIN_ROOT is set by Claude Code when invoking the hook.
SCRIPT="${CLAUDE_PLUGIN_ROOT:-}/skills/harness-plan/scripts/harness_autodrive.py"
if [ ! -f "$SCRIPT" ]; then
  # Best-effort fallback for unusual install layouts.
  SCRIPT="$(dirname "$0")/../skills/harness-plan/scripts/harness_autodrive.py"
fi

if [ ! -f "$SCRIPT" ]; then
  echo "[autodrive] cannot locate harness_autodrive.py" >> "${PROJECT_DIR}/.harness/autodrive.log"
  exit 0
fi

python3 "$SCRIPT" --project-root "$PROJECT_DIR" --decide \
  >> "${PROJECT_DIR}/.harness/autodrive.log" 2>&1

exit 0
