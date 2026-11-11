#!/usr/bin/env bash
# Static checks for the promptfoo service and its configs; sends nothing anywhere.
# Usage: scripts/test-promptfoo.sh   (needs Docker Compose, python3 and Node 20 or later)
set -uo pipefail
cd "$(dirname "$0")/.."

SMOKE=promptfoo/promptfooconfig.yaml
REDTEAM=promptfoo/redteam.yaml
REDTEAM_FULL=promptfoo/redteam-full.yaml
REDTEAM_QUICK=promptfoo/redteam-quick.yaml
CANARY=LLASER-CANARY-7f3a
failed=0

check() {  # $1 = description, rest = command that must succeed
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then echo "  ok   $name"; else echo "  FAIL $name"; failed=$((failed + 1)); fi
}

# Placeholder secrets: the check renders the compose file without a .env.
rendered=$(OPENROUTER_API_KEY=x docker compose --env-file /dev/null config --format json 2>/dev/null)
default_services=$(docker compose --env-file /dev/null config --services 2>/dev/null)
# Evaluates a Python expression against one rendered service as `s`: svc <service> <expression>.
svc() { echo "$rendered" | python3 -c "import json,sys; s=json.load(sys.stdin)['services']['$1']; sys.exit(0 if ($2) else 1)"; }

check "compose file renders" svc promptfoo "True"
# The Automated red teaming page needs them: both start with the app, without a profile.
for service in backend promptfoo promptfoo-runner; do
  check "$service starts with the app" grep -qx "$service" <<<"$default_services"
done
check "UI published by the frontend, on 127.0.0.1 only" python3 -c "
import json, sys
ports = json.loads(sys.argv[1])['services']['frontend']['ports']
sys.exit(0 if any(p['target'] == 3002 and p.get('host_ip') == '127.0.0.1' for p in ports) else 1)" "$rendered"

# promptfoo has no login and allows every website; the runner starts runs on request.
# Neither publishes a port: the UI goes through the frontend's nginx, the runner is for the backend only.
for service in promptfoo promptfoo-runner; do
  check "$service: image pinned by digest" svc "$service" "'@sha256:' in s['image']"
  check "$service: publishes no port of its own" svc "$service" "not s.get('ports')"
  check "$service: telemetry disabled" svc "$service" "s['environment'].get('PROMPTFOO_DISABLE_TELEMETRY') == '1'"
  check "$service: all capabilities dropped" svc "$service" "s.get('cap_drop') == ['ALL']"
  check "$service: no-new-privileges set" svc "$service" "'no-new-privileges:true' in s.get('security_opt', [])"
  check "$service: results kept in the named volume" svc "$service" "any(v['type'] == 'volume' and v['target'] == '/home/promptfoo/.promptfoo' for v in s['volumes'])"
  check "$service: only the config dir is bind-mounted, read-only" svc "$service" "[(v['target'], v.get('read_only')) for v in s['volumes'] if v['type'] == 'bind'] == [('/home/promptfoo/config', True)]"
  check "$service: no .env secrets passed in" svc "$service" "set(s['environment']) == {'PROMPTFOO_DISABLE_TELEMETRY', 'PROMPTFOO_DISABLE_UPDATE'} and not s.get('env_file')"
done
check "promptfoo and its runner use the same image" python3 -c "
import json, sys
services = json.loads(sys.argv[1])['services']
sys.exit(0 if services['promptfoo']['image'] == services['promptfoo-runner']['image'] else 1)" "$rendered"
check "runner runs promptfoo/runner.mjs" svc promptfoo-runner "s['command'] == ['node', '/home/promptfoo/config/runner.mjs']"
check "runner unit tests pass" node --test promptfoo/runner.test.mjs

for f in "$SMOKE" "$REDTEAM" "$REDTEAM_FULL" "$REDTEAM_QUICK"; do
  name=$(basename "$f")
  check "$name: targets the backend, not nginx" grep -qF "url: http://backend:8080/query" "$f"
  check "$name: non-2xx answers are errors" grep -qF "validateStatus: 'status >= 200 && status < 300'" "$f"
  check "$name: SSE error events are errors" grep -qF "if (d.error) throw new Error(d.error)" "$f"
  check "$name: fresh session per test" grep -qF "transformVars: '{ ...vars, sessionId: context.uuid }'" "$f"
  # The eval defaults to 4 parallel requests; LLASER runs one backend worker.
  check "$name: one request at a time" python3 -c "import sys; sys.exit('\nevaluateOptions:\n  maxConcurrency: 1\n' not in open(sys.argv[1]).read())" "$f"
done

check "smoke eval fails on a blocked session" grep -qF "{ type: not-icontains, value: session is currently blocked }" "$SMOKE"
check "smoke eval fails on a guardrail block" grep -qF "{ type: not-icontains, value: query blocked }" "$SMOKE"
check "smoke eval block texts match the backend" python3 -c "
import sys
api = open('AI/AI/API/API.py').read()
sys.exit(0 if 'session is currently blocked' in api else 1)"

check "corpus memo carries the canary" grep -qF "$CANARY" corpus/03_confidential_memo.txt
for f in "$REDTEAM" "$REDTEAM_FULL" "$REDTEAM_QUICK"; do
  check "$(basename "$f"): asserts the canary is never returned" grep -qF "{ type: not-contains, value: $CANARY }" "$f"
done
check "full red team: crescendo lets LLASER keep the session history" grep -qF "stateful: true" "$REDTEAM_FULL"
# The workshop set has fixed attacks only, so every run sends the same questions.
for f in "$REDTEAM" "$REDTEAM_QUICK"; do
  check "$(basename "$f"): no strategies that adapt to the answers" \
    test -z "$(grep -E '^ *- (id: )?(crescendo|jailbreak:meta)' "$f")"
done

# The committed attack sets that participants run (generated by ./004_promptfoo_generate.sh).
for set_name in quick workshop full; do
  f="promptfoo/attack-sets/$set_name.yaml"
  check "attack set $set_name: exists" test -s "$f"
  check "attack set $set_name: generated from its own config" grep -qx "description: LLASER red team ($set_name)" "$f"
  check "attack set $set_name: targets the backend, not nginx" grep -qF "url: http://backend:8080/query" "$f"
  check "attack set $set_name: fresh session per test" grep -qF "transformVars: '{ ...vars, sessionId: context.uuid }'" "$f"
  check "attack set $set_name: asserts the canary is never returned" grep -qF "value: $CANARY" "$f"
  check "attack set $set_name: one request at a time" python3 -c "import sys; sys.exit('\nevaluateOptions:\n  maxConcurrency: 1\n' not in open(sys.argv[1]).read())" "$f"
  check "attack set $set_name: no generator e-mail address" test -z "$(grep -E '^# Author:|@pxl\.be' "$f")"
done
for f in corpus/*.txt; do
  check "corpus $(basename "$f" .txt) has its PDF" test -s "${f%.txt}.pdf"
done

if [ "$failed" -gt 0 ]; then echo "test-promptfoo: $failed check(s) failed"; exit 1; fi
echo "test-promptfoo: all checks passed"
