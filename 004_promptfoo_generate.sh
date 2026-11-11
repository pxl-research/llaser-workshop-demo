#!/usr/bin/env bash
# For the workshop hosts, not for participants: generates an attack set and saves it
# in promptfoo/attack-sets/, ready to commit. Participants run the committed sets with 005.
# Generation runs on promptfoo cloud and needs an e-mail address (free tier) or a logged-in account.

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/scripts/promptfoo-lib.sh"

SET_NAME=workshop

usage() {
  cat <<'EOF'
Usage: ./004_promptfoo_generate.sh [--quick | --full]

For the workshop hosts. Generates an attack set and saves it in the repo:
  --quick    promptfoo/redteam-quick.yaml -> promptfoo/attack-sets/quick.yaml     (about 12 tests)
  (default)  promptfoo/redteam.yaml       -> promptfoo/attack-sets/workshop.yaml  (about 70 tests)
  --full     promptfoo/redteam-full.yaml  -> promptfoo/attack-sets/full.yaml      (about 216 tests)

A new set replaces the old one: runs on the old set no longer compare with runs on the new one.
The description of the app and every generated attack go to promptfoo cloud.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick) SET_NAME=quick; shift ;;
    --full) SET_NAME=full; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage; exit 1 ;;
  esac
done

CONFIG="$(redteam_config_file "$SET_NAME")"
ATTACK_SET="$(attack_set_file "$SET_NAME")"
GENERATED_IN_VOLUME="$DATA_DIR/generated-$SET_NAME.yaml"

ensure_promptfoo_running
ensure_promptfoo_email

echo "Generating the '$SET_NAME' attack set from promptfoo/$CONFIG (a few minutes)..."
in_promptfoo promptfoo redteam generate -c "$CONFIG_DIR/$CONFIG" -o "$GENERATED_IN_VOLUME" --force

# The container can only write to its volume, so copy the set into the repo from there.
# promptfoo writes the generator's e-mail address in the header ("# Author: ..."); keep it out of the repo.
mkdir -p "$HOST_CONFIG_DIR/attack-sets"
in_promptfoo cat "$GENERATED_IN_VOLUME" | grep -v '^# Author:' > "$HOST_CONFIG_DIR/$ATTACK_SET"

echo
echo "Saved promptfoo/$ATTACK_SET. Check it, then commit it."
