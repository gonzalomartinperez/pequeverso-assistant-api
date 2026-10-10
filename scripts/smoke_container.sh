#!/usr/bin/env bash
# Container smoke test: build (or reuse) the image, run it read-only as non-root with a data volume,
# exercise readiness, session, streamed answer, restart persistence and graceful shutdown.
#   scripts/smoke_container.sh [image]
set -euo pipefail

IMAGE="${1:-pequeverso-assistant-api:smoke}"
NAME="pv-assistant-smoke-$$"
VOLUME="pv-assistant-smoke-data-$$"
PORT="${SMOKE_PORT:-18080}"
MEMORY="${SMOKE_MEMORY:-256m}"
CPUS="${SMOKE_CPUS:-0.5}"
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
  docker run -d --name "$NAME" --read-only --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
    --memory "$MEMORY" --memory-swap "$MEMORY" --cpus "$CPUS" --pids-limit 64 \
    --log-driver local --log-opt max-size=10m --log-opt max-file=3 \
    --cap-drop ALL --security-opt no-new-privileges \
    -v "$VOLUME:/data" -p "127.0.0.1:$PORT:8000" -e ENVIRONMENT=test \
    -e AI_PROVIDER=fixture -e ALLOW_PAID_AI=false -e FIXTURE_CHUNK_DELAY_MS=10 \
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
test "$(docker inspect -f '{{.HostConfig.ReadonlyRootfs}}' "$NAME")" = true
curl --connect-timeout 5 --max-time 70 -fsS "http://127.0.0.1:$PORT/health/live" | grep -q '"status":"ok"'
curl --connect-timeout 5 --max-time 70 -fsS "http://127.0.0.1:$PORT/health/ready" | grep -q '"status":"ready"'

session="$(curl --connect-timeout 5 --max-time 70 -fsS -c "$JAR" -b "$JAR" -H "Origin: $ORIGIN" -H 'Content-Type: application/json' \
  -X POST "http://127.0.0.1:$PORT/api/v1/session" -d '{}')"
csrf="$(printf '%s' "$session" | python3 -c 'import json,sys; print(json.load(sys.stdin)["csrf_token"])')"

stream="$(curl --connect-timeout 5 --max-time 70 -fsS -N -c "$JAR" -b "$JAR" -H "Origin: $ORIGIN" -H 'Content-Type: application/json' \
  -H "X-CSRF-Token: $csrf" -H 'Idempotency-Key: smoke-000001' \
  -X POST "http://127.0.0.1:$PORT/api/v1/messages" -d '{"content":"¿Qué incluye el kit?"}')"
grep -q 'event: run.started' <<<"$stream"
grep -q 'event: message.delta' <<<"$stream"
grep -q 'event: run.completed' <<<"$stream"

code="$(curl --connect-timeout 5 --max-time 70 -sS -o /dev/null -w '%{http_code}' -H 'Origin: https://evil.example' -H 'Content-Type: application/json' \
  -X POST "http://127.0.0.1:$PORT/api/v1/session" -d '{}')"
test "$code" = 403 || { echo "origin not enforced: $code" >&2; exit 1; }

# Private ops API: token required, aggregates only, no conversation text.
code="$(curl --connect-timeout 5 --max-time 70 -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/internal/v1/ops/summary")"
test "$code" = 401 || { echo "ops endpoint without token: $code" >&2; exit 1; }
ops="$(curl --connect-timeout 5 --max-time 70 -fsS -H "Authorization: Bearer $OPS_TOKEN" "http://127.0.0.1:$PORT/internal/v1/ops/summary")"
printf '%s' "$ops" | python3 -c '
import json, sys
s = json.load(sys.stdin)
assert s["service"]["synthetic"] is True and s["windows"][0]["runs"]["completed"] == 1, s
assert "incluye" not in json.dumps(s)
'

# Online backup includes committed WAL writes; compare the spend ledger before restoration.
docker exec "$NAME" python -c '
import sqlite3
from contextlib import closing
with closing(sqlite3.connect("file:/data/assistant.sqlite3?mode=ro", uri=True)) as source, closing(sqlite3.connect("/data/smoke-backup.sqlite3")) as backup:
    assert source.execute("PRAGMA user_version").fetchone()[0] == 2
    source.execute("SELECT actual_micro,reserved_micro FROM spend_ledger LIMIT 1").fetchall()
    source.backup(backup)
    assert backup.execute("PRAGMA user_version").fetchone()[0] == 2
    assert backup.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    expected = source.execute("SELECT count(*),sum(coalesce(actual_micro,reserved_micro)) FROM spend_ledger").fetchone()
    assert backup.execute("SELECT count(*),sum(coalesce(actual_micro,reserved_micro)) FROM spend_ledger").fetchone() == expected
    assert expected[0] == 1 and expected[1] > 0
'

stats="$(docker stats --no-stream --format '{{.MemUsage}} cpu={{.CPUPerc}}' "$NAME")"

# Graceful stop, then a restart on the same volume keeps the conversation.
started="$(date +%s)"
docker stop -t 20 "$NAME" >/dev/null
stopped_in="$(( $(date +%s) - started ))"
test "$stopped_in" -le 15 || { echo "graceful stop exceeded 15 seconds: $stopped_in" >&2; exit 1; }
test "$(docker inspect -f '{{.State.ExitCode}}' "$NAME")" = 0
test "$(docker inspect -f '{{.State.OOMKilled}}' "$NAME")" = false
docker rm "$NAME" >/dev/null
# Restore the backup into the stopped, disposable smoke volume (never a production volume).
docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges \
  -v "$VOLUME:/data" --entrypoint python "$IMAGE" -c '
from pathlib import Path
for suffix in ("-wal", "-shm"):
    Path("/data/assistant.sqlite3" + suffix).unlink(missing_ok=True)
Path("/data/smoke-backup.sqlite3").replace("/data/assistant.sqlite3")
'
start
restored="$(curl --connect-timeout 5 --max-time 70 -fsS -c "$JAR" -b "$JAR" -H "Origin: $ORIGIN" -H 'Content-Type: application/json' \
  -X POST "http://127.0.0.1:$PORT/api/v1/session" -d '{}')"
count="$(printf '%s' "$restored" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["messages"]))')"
test "$count" = 2
# Verify restored spend remains charged rather than resetting the budget.
restored_ops="$(curl --connect-timeout 5 --max-time 70 -fsS -H "Authorization: Bearer $OPS_TOKEN" "http://127.0.0.1:$PORT/internal/v1/ops/summary")"
printf '%s' "$restored_ops" | python3 -c '
import json,sys
from decimal import Decimal
s=json.load(sys.stdin)
assert Decimal(s["budget"]["month_spend"]["confirmed"]) > 0
'
python3 scripts/container_fixture_probe.py --url "http://127.0.0.1:$PORT" --container "$NAME"
test "$(docker inspect -f '{{.State.OOMKilled}}' "$NAME")" = false

echo "container smoke passed: uid=65532 read-only rootfs, stream ok, ops summary ok, backup restore kept $count messages and charged ledger, stop took ${stopped_in}s, idle ${stats}"
