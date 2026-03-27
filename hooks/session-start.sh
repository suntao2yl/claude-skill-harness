#!/usr/bin/env bash
# Harness auto-resume hook for Claude Code SessionStart
# Detects an active campaign and injects context into the session.
#
# Install: Add to ~/.claude/settings.json or .claude/settings.json:
#   "hooks": {
#     "SessionStart": [{
#       "matcher": "*",
#       "hooks": [{
#         "type": "command",
#         "command": "/path/to/hooks/session-start.sh"
#       }]
#     }]
#   }

set -euo pipefail

CAMPAIGN_FILE="${CLAUDE_PROJECT_DIR:-.}/.harness/campaign.json"

# No campaign — silent exit
if [ ! -f "$CAMPAIGN_FILE" ]; then
  exit 0
fi

# Read campaign state with portable tools
goal=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('goal',''))" "$CAMPAIGN_FILE" 2>/dev/null || echo "")
if [ -z "$goal" ]; then
  exit 0
fi

total=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('total_features',0))" "$CAMPAIGN_FILE" 2>/dev/null || echo "0")
completed=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('completed_features',0))" "$CAMPAIGN_FILE" 2>/dev/null || echo "0")
current=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('current_feature','') or 'none')" "$CAMPAIGN_FILE" 2>/dev/null || echo "none")
mode=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('mode','standard'))" "$CAMPAIGN_FILE" 2>/dev/null || echo "standard")
last_session=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('last_session_date','unknown'))" "$CAMPAIGN_FILE" 2>/dev/null || echo "unknown")

# Count blocked features
FEATURES_FILE="${CLAUDE_PROJECT_DIR:-.}/.harness/features.json"
blocked_count=0
if [ -f "$FEATURES_FILE" ]; then
  blocked_count=$(python3 -c "
import json,sys
d=json.load(open(sys.argv[1]))
print(sum(1 for f in d.get('features',[]) if f.get('status')=='blocked'))
" "$FEATURES_FILE" 2>/dev/null || echo "0")
fi

# Build context summary
context="[harness] Active campaign detected.
Goal: ${goal}
Progress: ${completed}/${total} features completed (mode: ${mode})
Current feature: ${current}
Blocked: ${blocked_count}
Last session: ${last_session}

Run /harness to resume the campaign, or /harness status for details."

# Output as JSON for Claude Code hook protocol
python3 -c "
import json, sys
print(json.dumps({'additionalContext': sys.argv[1]}))
" "$context"
