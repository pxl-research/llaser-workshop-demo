#!/usr/bin/env bash
# Step 1 of the promptfoo exercise: checks that promptfoo reaches LLASER.
# Sends 3 harmless questions; all 3 must get an answer that is not blocked.

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/scripts/promptfoo-lib.sh"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  echo "Usage: ./003_promptfoo_check.sh"
  echo "Checks that promptfoo reaches LLASER (3 harmless questions). Run it with the defenses off."
  exit 0
fi

ensure_promptfoo_running

echo "Sending 3 harmless questions to LLASER..."
if in_promptfoo promptfoo eval -c "$CONFIG_DIR/promptfooconfig.yaml" --no-share --no-progress-bar; then
  echo
  echo "promptfoo reaches LLASER. Next: ./005_promptfoo_run.sh baseline"
else
  echo
  echo "The check failed. If an answer says 'query blocked', switch the defenses off and run this again."
  exit 1
fi
