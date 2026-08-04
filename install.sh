#!/usr/bin/env bash
# Canonical Codex plugin installer plus an explicit Claude-compatible copy.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="codex"
PREFIX="${HOME}/.claude/skills"
DRY_RUN=0
FORCE=0

usage() {
  cat <<'EOF'
Usage:
  ./install.sh [--codex] [--dry-run]
  ./install.sh --claude [--prefix PATH] [--force] [--dry-run]

Codex uses the repository marketplace and its lightweight generated plugin root.
Claude mode copies the durable contract and handoff surface of the unified skill.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --codex) MODE="codex"; shift ;;
    --claude) MODE="claude"; shift ;;
    --prefix) PREFIX="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

run() {
  if (( DRY_RUN )); then
    printf 'DRY-RUN:'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

if [[ "$MODE" == "codex" ]]; then
  run python3 "$SCRIPT_DIR/scripts/sync_codex_plugin.py" --check
  run codex plugin marketplace add "$SCRIPT_DIR"
  run codex plugin add "harness@harness-marketplace"
  echo "Start a new Codex task, then invoke \$harness explicitly."
  exit 0
fi

SOURCE="$SCRIPT_DIR/skills/harness"
DEST="$PREFIX/harness"
if [[ -e "$DEST" && "$FORCE" -ne 1 ]]; then
  echo "Destination exists: $DEST" >&2
  echo "Re-run with --force to replace it, or choose another --prefix." >&2
  exit 1
fi

if [[ -e "$DEST" ]]; then
  BACKUP="${DEST}.backup.$(date -u +%Y%m%dT%H%M%SZ)"
  run mv "$DEST" "$BACKUP"
  echo "Existing Claude skill moved to $BACKUP"
fi
run mkdir -p "$PREFIX"
run cp -R "$SOURCE" "$DEST"
echo "Claude-compatible delivery ledger installed at $DEST"
