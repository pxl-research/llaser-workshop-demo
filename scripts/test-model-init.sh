#!/usr/bin/env bash
# Check for the model-init service: install, skip when present, wrong password, wrong SHA-256.
# Usage: scripts/test-model-init.sh   (needs Docker and openssl; builds the frontend image)
set -euo pipefail
cd "$(dirname "$0")/.."
export LLASER_TAG=model-init-test MODEL_URL=https://example.invalid/model-test.tar.gz.enc
dc() { docker compose -p llaser-model-init-test "$@"; }
work=$(mktemp -d)
cleanup() { dc down -v >/dev/null 2>&1 || true; rm -rf "$work" models/model-test.tar.gz.enc; }
trap cleanup EXIT

# A fake model, encrypted the way the facilitator encrypts the real one.
head -c 100000 /dev/urandom > "$work/model.onnx"
echo '{"fake": true}' > "$work/tokenizer.json"
mkdir -p models
tar -czf - -C "$work" model.onnx tokenizer.json |
  openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -md sha256 -salt -pass pass:test-pw -out models/model-test.tar.gz.enc
sha=$(shasum -a 256 models/model-test.tar.gz.enc | cut -d' ' -f1)
want=$(shasum -a 256 "$work/model.onnx" | cut -d' ' -f1)

dc build -q frontend
run() { dc run --rm -e MODEL_SHA256="$1" -e MODEL_PASSWORD="$2" model-init 2>&1; }
installed() { dc run --rm --entrypoint sha256sum model-init /model/model.onnx 2>/dev/null | cut -d' ' -f1; }
fail() { echo "FAIL: $1"; exit 1; }

run "$sha" wrong-pw && fail "wrong password must fail"
[ -z "$(installed)" ] || fail "wrong password must not install anything"
run 0000 test-pw && fail "wrong SHA-256 must fail"

out=$(run "$sha" test-pw) || fail "install: $out"
[ "$(installed)" = "$want" ] || fail "installed model.onnx differs"
out=$(run "$sha" test-pw) || fail "second run: $out"
echo "$out" | grep -q "already installed" || fail "second run must skip: $out"
echo "model-init: ok"
