#!/usr/bin/env bash
# Container smoke test: build (or reuse) the image, run it read-only as non-root with a data volume,
# exercise readiness, session, streamed answer, restart persistence and graceful shutdown.
#   scripts/smoke_container.sh [image]
set -euo pipefail

IMAGE="${1:-pequeverso-assistant-api:smoke}"
NAME="pv-assistant-smoke-$$"
VOLUME="pv-assistant-smoke-data-$$"
PORT="${SMOKE_PORT:-18080}"
ORIGIN="http://localhost:3000"
JAR="$(mktemp)"
OPS_TOKEN="smoke-ops-token-$(python3 -c 'import secrets; print(secrets.token_hex(16))')"

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker volume rm "$VOLUME" >/dev/null 2>&1 || true
  rm -f "$JAR"
}
trap cleanup EXIT

if [[ $# -eq 0 ]]; then
  docker build -q --build-arg SERVICE_REVISION="$(git rev-parse HEAD)" -t "$IMAGE" . >/dev/null
fi

start() {
  docker run -d --name "$NAME" --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
    -v "$VOLUME:/data" -p "127.0.0.1:$PORT:8000" -e ENVIRONMENT=test \
    -e OPS_READ_TOKEN="$OPS_TOKEN" "$IMAGE" >/dev/null
  for _ in $(seq 1 60); do
    if [[ "$(docker inspect -f '{{.State.Health.Status}}' "$NAME")" == healthy ]]; then return 0; fi
    sleep 1
  done
  docker logs "$NAME" | tail -20
  echo "container never became healthy" >&2
  return 1
}

start
test "$(docker exec "$NAME" id -u)" = 65532
curl -fsS "http://127.0.0.1:$PORT/health/ready" | grep -q '"status":"ready"'

session="$(curl -fsS -c "$JAR" -b "$JAR" -H "Origin: $ORIGIN" -H 'Content-Type: application/json' \
  -X POST "http://127.0.0.1:$PORT/api/v1/session" -d '{}')"
csrf="$(printf '%s' "$session" | python3 -c 'import json,sys; print(json.load(sys.stdin)["csrf_token"])')"

stream="$(curl -fsS -N -c "$JAR" -b "$JAR" -H "Origin: $ORIGIN" -H 'Content-Type: application/json' \
  -H "X-CSRF-Token: $csrf" -H 'Idempotency-Key: smoke-000001' \
  -X POST "http://127.0.0.1:$PORT/api/v1/messages" -d '{"content":"¿Qué incluye el kit?"}')"
grep -q 'event: run.started' <<<"$stream"
grep -q 'event: message.delta' <<<"$stream"
grep -q 'event: run.completed' <<<"$stream"

code="$(curl -sS -o /dev/null -w '%{http_code}' -H 'Origin: https://evil.example' -H 'Content-Type: application/json' \
  -X POST "http://127.0.0.1:$PORT/api/v1/session" -d '{}')"
test "$code" = 403 || { echo "origin not enforced: $code" >&2; exit 1; }

# Private ops API: token required, aggregates only, no conversation text.
code="$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/internal/v1/ops/summary")"
test "$code" = 401 || { echo "ops endpoint without token: $code" >&2; exit 1; }
ops="$(curl -fsS -H "Authorization: Bearer $OPS_TOKEN" "http://127.0.0.1:$PORT/internal/v1/ops/summary")"
printf '%s' "$ops" | python3 -c '
import json, sys
s = json.load(sys.stdin)
assert s["service"]["synthetic"] is True and s["windows"][0]["runs"]["completed"] == 1, s
assert "incluye" not in json.dumps(s)
'

stats="$(docker stats --no-stream --format '{{.MemUsage}} cpu={{.CPUPerc}}' "$NAME")"

# Graceful stop, then a restart on the same volume keeps the conversation.
started="$(date +%s)"
docker stop -t 20 "$NAME" >/dev/null
stopped_in="$(( $(date +%s) - started ))"
docker rm "$NAME" >/dev/null
start
restored="$(curl -fsS -c "$JAR" -b "$JAR" -H "Origin: $ORIGIN" -H 'Content-Type: application/json' \
  -X POST "http://127.0.0.1:$PORT/api/v1/session" -d '{}')"
count="$(printf '%s' "$restored" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["messages"]))')"
test "$count" = 2

echo "container smoke passed: uid=65532 read-only rootfs, stream ok, ops summary ok, restart kept $count messages, stop took ${stopped_in}s, idle ${stats}"
