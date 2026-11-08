#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$ROOT_DIR/.env"
WITH_PROMPTFOO=0
SKIP_BUILD=0
NO_CACHE=0

usage() {
  cat <<'EOF'
Usage: ./001_start_llaser.sh [--promptfoo] [--no-build] [--no-cache]

Builds the backend and frontend images from the local source and (re)starts the
LLASER workshop app. Every start rebuilds, so code changes are always in the
running containers; unchanged code reuses the Docker layer cache and is quick.

Options:
  --promptfoo  Also start promptfoo (UI on http://127.0.0.1:3002).
  --no-build   Start the existing images without rebuilding.
  --no-cache   Force a full rebuild (ignore the Docker layer cache).
EOF
}

require_file() {
  local file_path="$1"
  local help_text="$2"

  if [[ ! -f "$file_path" ]]; then
    echo "Missing required file: $file_path"
    echo "$help_text"
    exit 1
  fi
}

# Reads one setting from .env without loading the secrets in it.
env_value() {
  local name="$1"
  local default="$2"
  local value
  value="$(grep -E "^${name}=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- | tr -d "\"' " || true)"
  echo "${value:-$default}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --promptfoo)
      WITH_PROMPTFOO=1
      shift
      ;;
    --no-build)
      SKIP_BUILD=1
      shift
      ;;
    --no-cache)
      NO_CACHE=1
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

require_file "$ENV_FILE" \
  "Copy .env.example to .env and fill in the empty values (see README.md, step 3)."

COMPOSE=(docker compose --project-directory "$ROOT_DIR")
if [[ "$WITH_PROMPTFOO" -eq 1 ]]; then
  COMPOSE+=(--profile promptfoo)
fi

if [[ "$SKIP_BUILD" -eq 0 ]]; then
  echo "Building backend and frontend images from local source..."
  BUILD_ARGS=()
  if [[ "$NO_CACHE" -eq 1 ]]; then
    BUILD_ARGS+=(--no-cache)
    echo "(full rebuild: --no-cache)"
  fi
  "${COMPOSE[@]}" build ${BUILD_ARGS[@]+"${BUILD_ARGS[@]}"} backend frontend
else
  echo "Skipping image build (--no-build)."
fi

echo "Starting LLASER..."
# Images are only pulled when missing locally (promptfoo, or --no-build without a local build),
# never over the images just built.
"${COMPOSE[@]}" up -d --no-build

LLASER_PORT="$(env_value LLASER_PORT 8080)"
PROMPTFOO_PORT="$(env_value PROMPTFOO_PORT 3002)"
APP_URL="http://127.0.0.1:${LLASER_PORT}"

if command -v curl >/dev/null 2>&1; then
  echo "Waiting for ${APP_URL}/api/health ..."
  for _ in $(seq 1 30); do
    if curl -fsS "${APP_URL}/api/health" >/dev/null 2>&1; then
      echo "Backend is responding."
      break
    fi
    sleep 2
  done
fi

cat <<EOF

LLASER workshop app is running.

App:              ${APP_URL}
Readiness:        ${APP_URL}/api/ready
NLP model install: docker compose logs -f model-init
EOF

if [[ "$WITH_PROMPTFOO" -eq 1 ]]; then
  cat <<EOF
promptfoo UI:     http://127.0.0.1:${PROMPTFOO_PORT}
Smoke eval:       docker compose exec promptfoo promptfoo eval -c /home/promptfoo/config/promptfooconfig.yaml
EOF
fi

cat <<'EOF'

To stop:
  ./002_stop_llaser.sh

EOF
