#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESET=0

usage() {
  cat <<'EOF'
Usage: ./002_stop_llaser.sh [--reset]

Stops the LLASER workshop app, including promptfoo if it runs.

Options:
  --reset  Also delete the volumes: uploaded documents, chat memory,
           the installed NLP model and the promptfoo runs.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --reset)
      RESET=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
done

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not reachable. Start Docker and try again."
  exit 1
fi

DOWN_ARGS=()
if [[ "$RESET" -eq 1 ]]; then
  DOWN_ARGS+=(--volumes)
  echo "Stopping LLASER and deleting its volumes..."
else
  echo "Stopping LLASER (documents, chat memory, model and promptfoo runs are kept)..."
fi

docker compose --project-directory "$ROOT_DIR" down ${DOWN_ARGS[@]+"${DOWN_ARGS[@]}"}
