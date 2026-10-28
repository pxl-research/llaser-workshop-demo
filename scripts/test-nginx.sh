#!/usr/bin/env bash
# Check for nginx.local.conf: only localhost Host names (no DNS rebinding) and same-host Origins
# (no cross-site upload) get through to /api/.
# Usage: scripts/test-nginx.sh   (needs Docker)
set -euo pipefail
cd "$(dirname "$0")/.."
img=nginxinc/nginx-unprivileged:1.30.6-alpine
net=llaser-nginx-test
cleanup() { docker rm -f $net-proxy $net-backend >/dev/null 2>&1 || true; docker network rm $net >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup
docker network create $net >/dev/null
# Stand-in backend: the image's default page answers GET / with 200 and POST / with 405.
docker run -d --name $net-backend --network $net --network-alias backend $img >/dev/null
docker run -d --name $net-proxy --network $net -p 127.0.0.1::8080 \
  -v "$PWD/AI/AI-web-app/nginx.local.conf:/etc/nginx/conf.d/default.conf:ro" $img >/dev/null
port=$(docker port $net-proxy 8080 | cut -d: -f2)

code() { curl -s -o /dev/null -w '%{http_code}' "$@" "http://127.0.0.1:$port/api/"; }
for _ in $(seq 20); do [ "$(code)" != 000 ] && break; sleep 0.5; done

fail=0
expect() { got=$(code "${@:2}"); [ "$got" = "$1" ] || { echo "FAIL: want $1, got $got for: ${*:2}"; fail=1; }; }
expect 200
expect 200 -H 'Host: localhost:8080'
expect 421 -H 'Host: llaser.attacker.example'
expect 405 -X POST
expect 405 -X POST -H 'Origin: http://127.0.0.1:8080'
expect 405 -X POST -H 'Origin: http://localhost:8081'
expect 403 -X POST -H 'Origin: https://attacker.example'
expect 403 -X POST -H 'Origin: http://127.0.0.1.attacker.example'
expect 403 -X POST -H 'Origin: null'
[ $fail = 0 ] && echo "nginx: ok"
exit $fail
