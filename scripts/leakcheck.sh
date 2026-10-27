#!/usr/bin/env bash
# Leak check for the public repo: prints every hit and exits 1 if there is any.
# Usage: scripts/leakcheck.sh [rev...]
#   rev...    commits to scan instead of the working tree, e.g. $(git rev-list --all)
names='ts\.net|tailnet|pxl\.be|llaser_demo2/'
secrets="sk-or-v1-[0-9a-f]{16,}|(^|[^A-Za-z0-9])sk-(proj-|ant-)?[A-Za-z0-9_-]{32,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|BEGIN [A-Z ]*PRIVATE KEY|(API_KEY|TOKEN|SECRET|PASSWORD)[\"']?[[:space:]]*[=:][[:space:]]*[\"']?[A-Za-z0-9_./+-]{20,}"
ips='(^|[^0-9.])(10\.[0-9]{1,3}|172\.(1[6-9]|2[0-9]|3[01])|192\.168|100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7]))\.[0-9]{1,3}\.[0-9]{1,3}([^0-9.]|$)'
email='[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
hits=$(
  git grep -nIiE "$names" "$@" -- . ':!docs/plans' ':!scripts/leakcheck.sh'
  git grep -nIE "$secrets" "$@" -- . ':!scripts/leakcheck.sh'
  git grep -nIE "$ips" "$@" -- . ':!AI/AI-web-app/package-lock.json'
  git grep -nIoE "$email" "$@" -- . ':!AI/AI-web-app/package-lock.json' | grep -viE '@example\.(org|com|net)$'
)
if [ -n "$hits" ]; then echo "$hits"; exit 1; fi
echo "leakcheck: clean"
