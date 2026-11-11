#!/usr/bin/env bash
# Check for nginx.local.conf: only localhost Host names (no DNS rebinding) and same-host Origins
# (no cross-site requests) get through, both to the app's /api/ and to the promptfoo UI on port 3002.
# Usage: scripts/test-nginx.sh   (needs Docker)
set -euo pipefail
cd "$(dirname "$0")/.."
img=nginxinc/nginx-unprivileged:1.30.6-alpine
net=llaser-nginx-test
remove_containers() {
  docker rm -f $net-proxy $net-backend $net-promptfoo >/dev/null 2>&1 || true
  docker network rm $net >/dev/null 2>&1 || true
}
remove_containers  # leftovers of an interrupted earlier run
standin_dir=$(mktemp -d)
trap 'remove_containers; rm -rf "$standin_dir"' EXIT
docker network create $net >/dev/null

# Stand-in backend: the image's default page answers GET / with 200 and POST / with 405.
docker run -d --name $net-backend --network $net --network-alias backend $img >/dev/null

# Stand-in promptfoo on port 3000: like the real one, it allows every website.
cat > "$standin_dir/promptfoo.conf" <<'EOF'
server {
  listen 3000;
  location / {
    add_header Access-Control-Allow-Origin * always;
    return 200 "promptfoo\n";
  }
}
EOF
chmod a+r "$standin_dir/promptfoo.conf"
start_promptfoo_standin() {
  docker run -d --name $net-promptfoo --network $net --network-alias promptfoo \
    -v "$standin_dir/promptfoo.conf:/etc/nginx/conf.d/default.conf:ro" $img >/dev/null
}
start_promptfoo_standin

docker run -d --name $net-proxy --network $net -p 127.0.0.1::8080 -p 127.0.0.1::3002 \
  -v "$PWD/AI/AI-web-app/nginx.local.conf:/etc/nginx/conf.d/default.conf:ro" $img >/dev/null
app_port=$(docker port $net-proxy 8080 | cut -d: -f2)
promptfoo_port=$(docker port $net-proxy 3002 | cut -d: -f2)

# HTTP status of a request; the first argument is the URL, the rest are curl options.
code() { local url="$1"; shift; curl -s -o /dev/null -w '%{http_code}' "$@" "$url"; }
app="http://127.0.0.1:$app_port/api/"
promptfoo="http://127.0.0.1:$promptfoo_port/api/results"
for _ in $(seq 20); do [ "$(code "$app")" != 000 ] && [ "$(code "$promptfoo")" = 200 ] && break; sleep 0.5; done

fail=0
expect() {  # $1 = expected status, $2 = URL, rest = curl options
  local want="$1" url="$2"; shift 2
  local got; got=$(code "$url" "$@")
  [ "$got" = "$want" ] || { echo "FAIL: want $want, got $got for: $url $*"; fail=1; }
}

echo "app /api/"
expect 200 "$app"
expect 200 "$app" -H 'Host: localhost:8080'
expect 421 "$app" -H 'Host: llaser.attacker.example'
expect 405 "$app" -X POST
expect 405 "$app" -X POST -H 'Origin: http://127.0.0.1:8080'
expect 405 "$app" -X POST -H 'Origin: http://localhost:8081'
expect 403 "$app" -X POST -H 'Origin: https://attacker.example'
expect 403 "$app" -X POST -H 'Origin: http://127.0.0.1.attacker.example'
expect 403 "$app" -X POST -H 'Origin: null'

echo "promptfoo UI on port 3002"
expect 200 "$promptfoo"
expect 200 "$promptfoo" -H 'Origin: http://127.0.0.1:3002'
expect 421 "$promptfoo" -H 'Host: promptfoo.attacker.example'
expect 403 "$promptfoo" -H 'Origin: https://attacker.example'
expect 403 "$promptfoo" -X POST -H 'Origin: https://attacker.example'
expect 403 "$promptfoo" -X OPTIONS -H 'Origin: https://attacker.example' -H 'Access-Control-Request-Method: POST'
if curl -s -D - -o /dev/null "$promptfoo" | grep -qi '^access-control-allow-origin'; then
  echo "FAIL: promptfoo's Access-Control-Allow-Origin header reaches the browser"; fail=1
fi

echo "promptfoo not running"
docker rm -f $net-promptfoo >/dev/null
expect 503 "$promptfoo"
expect 200 "$app"
start_promptfoo_standin
for _ in $(seq 20); do [ "$(code "$promptfoo")" = 200 ] && break; sleep 0.5; done
expect 200 "$promptfoo"

[ $fail = 0 ] && echo "nginx: ok"
exit $fail
