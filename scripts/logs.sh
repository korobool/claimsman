#!/usr/bin/env bash
# Tail the live claimsman tmux session on the current host.
set -euo pipefail
SESSION="${CLAIMSMAN_TMUX_SESSION:-claimsman}"
if tmux has-session -t "$SESSION" 2>/dev/null; then
  tmux attach -t "$SESSION"
else
  echo "no tmux session named $SESSION; falling back to /tmp/claimsman.log"
  tail -f /tmp/claimsman.log
fi
