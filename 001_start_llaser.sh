#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$ROOT_DIR/.env"
BUILD=0
NO_CACHE=0

usage() {
  cat <<'EOF'
Usage: ./001_start_llaser.sh [--build [--no-cache]]

Starts the LLASER workshop app with the published images, promptfoo included:
the same as docker compose up -d, after downloading the newest published images.

Options:
  --build     Build the backend and frontend from the local source instead (for developers).
  --no-cache  With --build: force a full rebuild (ignore the Docker layer cache).
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
  value="$(grep -E "^${name}=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- | tr -d "\"' \r" || true)"
  echo "${value:-$default}"
}

# A build puts the NLP model from this folder (gitignored) into the backend image.
MODEL_DIR="$ROOT_DIR/AI/AI/API/models/malicious_prompt_detector"

# For --build only: copies the NLP model out of the published backend image, which contains it.
copy_model_from_published_image() {
  local container="llaser-model-copy-$$"
  echo "Copying the NLP model out of the published backend image..."
  "${COMPOSE[@]}" pull backend
  docker create --name "$container" "$("${COMPOSE[@]}" config --images | grep '/backend:')" >/dev/null
  mkdir -p "$(dirname "$MODEL_DIR")"
  docker cp "$container:/app/AI/API/models/malicious_prompt_detector" "$MODEL_DIR"
  docker rm "$container" >/dev/null
}

build_from_source() {
  if [[ ! -f "$MODEL_DIR/model.onnx" ]]; then
    copy_model_from_published_image
  fi
  echo "Building backend and frontend images from local source..."
  local build_args=()
  if [[ "$NO_CACHE" -eq 1 ]]; then
    build_args+=(--no-cache)
  fi
  "${COMPOSE[@]}" build ${build_args[@]+"${build_args[@]}"} backend frontend
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build)
      BUILD=1
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

if [[ "$BUILD" -eq 1 ]]; then
  build_from_source
else
  echo "Downloading the newest published images..."
  # Also replaces images that an earlier --build made under the same name.
  # Without internet, start with the images that are already on this laptop.
  if ! "${COMPOSE[@]}" pull; then
    echo "Could not download the newest images; starting with the images already on this laptop."
  fi
fi

echo "Starting LLASER..."
# --no-build: never build here. Without --build, the published images are used, and they contain the NLP model.
"${COMPOSE[@]}" up -d --no-build
# The runner's code (promptfoo/runner.mjs) is mounted, not built into an image: restart it so a change is
# picked up. A run it was doing stops; start it again from the page.
"${COMPOSE[@]}" restart promptfoo-runner

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
promptfoo UI:     http://127.0.0.1:${PROMPTFOO_PORT}
Red team runs:    ./003_promptfoo_check.sh, then ./005_promptfoo_run.sh baseline (see README.md)
EOF

cat <<'EOF'

To stop:
  ./002_stop_llaser.sh

EOF
