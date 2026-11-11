#!/usr/bin/env bash
# Runs an attack set against LLASER as it is set up now.
# The run is tagged with the current settings (model, defenses, system prompt),
# read from the backend, so the runs can be compared in the promptfoo UI.

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/scripts/promptfoo-lib.sh"

SET_NAME=workshop
RUN_NAME=""

usage() {
  cat <<'EOF'
Usage: ./005_promptfoo_run.sh [--quick | --full] <run-name>

Runs the workshop attack set (about 70 attacks, about 7 minutes) against LLASER
with its current settings, for example:
  ./005_promptfoo_run.sh baseline
  ./005_promptfoo_run.sh nlp-defense

Change one setting on the Controls page between runs, then compare the runs in the promptfoo UI.

Options:
  --quick  Run the quick attack set instead (about 12 attacks, about a minute), to check a change.
  --full   Run the full attack set instead (about 216 attacks, 45-60 minutes).
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick) SET_NAME=quick; shift ;;
    --full) SET_NAME=full; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "Unknown option: $1"; usage; exit 1 ;;
    *) RUN_NAME="$1"; shift ;;
  esac
done

if [[ -z "$RUN_NAME" ]]; then
  usage
  exit 1
fi
if [[ ! "$RUN_NAME" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]]; then
  echo "Start the run name with a letter or digit; then use letters, digits, '.', '_' and '-', at most 64."
  exit 1
fi

ATTACK_SET="$(attack_set_file "$SET_NAME")"
if [[ ! -f "$HOST_CONFIG_DIR/$ATTACK_SET" ]]; then
  echo "promptfoo/$ATTACK_SET is missing. Pull the latest version of the repo (git pull)."
  exit 1
fi

ensure_promptfoo_running

# Two runs with the same name cannot be told apart in the promptfoo UI.
USED_NAMES="$(in_promptfoo node "$CONFIG_DIR/run-names.mjs")"
if grep -qxF "$RUN_NAME" <<< "$USED_NAMES"; then
  echo "There already is a run named '$RUN_NAME'. Choose a name that says what you changed, for example '$RUN_NAME-2'."
  exit 1
fi

ensure_promptfoo_email

# One "name=value" per line, e.g. "defenses=nlp"; stops here when a defense is on but not working.
SETTINGS="$(in_promptfoo node "$CONFIG_DIR/run-tags.mjs")"

TAG_ARGS=(--tag "run=$RUN_NAME" --tag "attack_set=$SET_NAME")
while IFS= read -r tag; do
  TAG_ARGS+=(--tag "$tag")
done <<< "$SETTINGS"

echo "Run '$RUN_NAME' with the '$SET_NAME' attack set and these settings:"
echo "$SETTINGS" | sed 's/^/  /'
echo

# Exit code 100 means some attacks got through: that is a result, not an error.
ATTACKS_GOT_THROUGH=100
exit_code=0
in_promptfoo promptfoo redteam eval -c "$CONFIG_DIR/$ATTACK_SET" --no-share --description "$RUN_NAME" "${TAG_ARGS[@]}" || exit_code=$?
if [[ "$exit_code" -ne 0 && "$exit_code" -ne "$ATTACKS_GOT_THROUGH" ]]; then
  echo "The run failed (exit code $exit_code), see the output above."
  exit "$exit_code"
fi

PROMPTFOO_PORT="$(grep -E '^PROMPTFOO_PORT=' "$ROOT_DIR/.env" 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d "\"' " || true)"
echo
echo "Compare the runs: http://127.0.0.1:${PROMPTFOO_PORT:-3002}"
