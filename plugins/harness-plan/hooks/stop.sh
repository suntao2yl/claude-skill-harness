#!/usr/bin/env bash
# Harness autodrive Stop hook.
# Delegates to harness_autodrive.py --decide. Always exits 0 so a failure
# inside the helper never blocks Claude Code from shutting down.
#
# Locates `.harness/autodrive.json` anywhere within CLAUDE_PROJECT_DIR (up to
# depth 4) so harness-plan campaigns nested under e.g.
# `.engineering/implementation/.harness/` are picked up correctly. The chosen
# directory becomes the script's --project-root, so spawned sessions inherit
# the right cwd.

set +e

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Find the nearest .harness/autodrive.json under PROJECT_DIR.
# -maxdepth 4 covers the harness-engineering layout (.engineering/<phase>/.harness)
# without scanning the whole repo.
AUTODRIVE_JSON="$(find "$PROJECT_DIR" -maxdepth 4 -type f -path '*/.harness/autodrive.json' 2>/dev/null | head -n1)"
if [ -z "$AUTODRIVE_JSON" ]; then
  exit 0
fi
HARNESS_ROOT="$(dirname "$(dirname "$AUTODRIVE_JSON")")"

# CLAUDE_PLUGIN_ROOT is set by Claude Code when invoking the hook.
SCRIPT="${CLAUDE_PLUGIN_ROOT:-}/skills/harness-plan/scripts/harness_autodrive.py"
if [ ! -f "$SCRIPT" ]; then
  # Best-effort fallback for unusual install layouts.
  SCRIPT="$(dirname "$0")/../skills/harness-plan/scripts/harness_autodrive.py"
fi

if [ ! -f "$SCRIPT" ]; then
  echo "[autodrive] cannot locate harness_autodrive.py" >> "${HARNESS_ROOT}/.harness/autodrive.log"
  exit 0
fi

python3 "$SCRIPT" --project-root "$HARNESS_ROOT" --decide \
  >> "${HARNESS_ROOT}/.harness/autodrive.log" 2>&1

exit 0
