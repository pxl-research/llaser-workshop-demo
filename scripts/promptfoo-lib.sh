#!/usr/bin/env bash
# Shared helpers for the 00x_promptfoo_*.sh scripts. Source it, do not run it.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose --project-directory "$ROOT_DIR")

# The promptfoo folder of the repo: ./promptfoo on the host, mounted read-only in the container.
HOST_CONFIG_DIR="$ROOT_DIR/promptfoo"
CONFIG_DIR=/home/promptfoo/config
# The promptfoo-data volume in the container: runs and settings.
DATA_DIR=/home/promptfoo/.promptfoo

# The attack sets are generated once by the workshop hosts and committed to the repo:
# "quick" (from redteam-quick.yaml), "workshop" (from redteam.yaml) and "full" (from redteam-full.yaml).
# Both helpers return a path relative to the promptfoo folder.
attack_set_file() {
  local set_name="$1"
  echo "attack-sets/$set_name.yaml"
}

redteam_config_file() {
  local set_name="$1"
  case "$set_name" in
    quick) echo "redteam-quick.yaml" ;;
    full) echo "redteam-full.yaml" ;;
    *) echo "redteam.yaml" ;;
  esac
}

# Runs a command inside the running promptfoo container.
# In a terminal it gets a terminal too, so promptfoo shows its progress bar;
# without one (CI, or output captured by a script) it runs with -T.
in_promptfoo() {
  if [[ -t 0 && -t 1 ]]; then
    "${COMPOSE[@]}" exec promptfoo "$@"
  else
    "${COMPOSE[@]}" exec -T promptfoo "$@"
  fi
}

# Starts promptfoo next to LLASER when it is not running yet, and stops if LLASER is down.
ensure_promptfoo_running() {
  if ! docker info >/dev/null 2>&1; then
    echo "Docker is not reachable. Start Docker and try again."
    exit 1
  fi
  if [[ -z "$("${COMPOSE[@]}" ps --status running -q backend)" ]]; then
    echo "LLASER is not running. Start it first: ./001_start_llaser.sh"
    exit 1
  fi
  if [[ -z "$("${COMPOSE[@]}" ps --status running -q promptfoo)" ]]; then
    echo "Starting promptfoo..."
    "${COMPOSE[@]}" up -d promptfoo
  fi
}

# promptfoo cloud generates and grades the attacks, and asks for an e-mail address once (free tier).
# It is kept in the promptfoo-data volume.
ensure_promptfoo_email() {
  if in_promptfoo promptfoo config get email 2>/dev/null | grep -q "@"; then
    return
  fi
  local email
  read -r -p "E-mail address for promptfoo cloud (it grades the answers): " email
  in_promptfoo promptfoo config set email "$email"
}
