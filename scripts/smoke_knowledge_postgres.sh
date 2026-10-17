#!/usr/bin/env bash
# Own isolated database only. No shared volumes, identities, paid providers or image publication.
set -euo pipefail
image=${1:?exact locally built PostgreSQL image ID required}
receipt=${2:?external receipt directory required}
case "$image" in sha256:*) ;; *) echo 'An immutable local image ID is required' >&2; exit 2;; esac
mkdir -p "$receipt"
receipt=$(realpath "$receipt")
name="pv-api-knowledge-pg-20261017-$$"
network="$name-net"
volume="$name-data"
private=$(mktemp -d)
chmod 700 "$private"
cleanup() {
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  docker volume rm "$volume" >/dev/null 2>&1 || true
  rm -rf "$private"
}
trap cleanup EXIT
password=$(python3 -c 'import secrets; print(secrets.token_hex(24))')
umask 077
printf 'POSTGRES_USER=knowledge_test\nPOSTGRES_PASSWORD=%s\nPOSTGRES_DB=pv_knowledge_test\n' "$password" > "$private/postgres.env"
# Exclusive bridge with a loopback-only host binding. Docker's internal networks on this
# daemon do not expose their published port to the host-side Python integration runner.
docker network create "$network" >/dev/null
docker volume create "$volume" >/dev/null
mapfile -t image_command < <(docker image inspect --format '{{json .Config.Cmd}}' "$image" | python3 -c 'import json,sys; print("\n".join(json.load(sys.stdin)))')
if [ "${image_command[0]:-}" != postgres ]; then echo 'PostgreSQL image CMD is missing' >&2; exit 1; fi
docker run -d --name "$name" --network "$network" --user 999:999 \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  --memory 384m --cpus 1 --pids-limit 128 --shm-size 64m \
  --tmpfs /tmp:rw,nosuid,noexec,size=16m \
  --tmpfs /var/run/postgresql:rw,nosuid,noexec,uid=999,gid=999,mode=3775,size=16m \
  --mount "type=volume,source=$volume,target=/var/lib/postgresql" \
  --env-file "$private/postgres.env" -p 127.0.0.1:55439:5432 "$image" \
  "${image_command[@]}" -c shared_buffers=32MB -c max_connections=16 -c work_mem=2MB \
  -c maintenance_work_mem=32MB -c max_wal_size=128MB >/dev/null
ready=false
for _ in $(seq 1 60); do
  if python3 -c 'import socket; socket.create_connection(("127.0.0.1",55439),0.3).close()' 2>/dev/null \
    && docker exec "$name" pg_isready -q -U knowledge_test -d pv_knowledge_test; then ready=true; break; fi
  sleep 0.5
done
if [ "$ready" != true ]; then echo 'Isolated PostgreSQL did not become ready' >&2; exit 1; fi
export TEST_KNOWLEDGE_DSN="postgresql://knowledge_test:${password}@127.0.0.1:55439/pv_knowledge_test"
export KNOWLEDGE_PLAN_OUTPUT="$receipt/exact-vector-explain.json"
export KNOWLEDGE_PRIVATE_PLAN_OUTPUT="$receipt/private-query-explain.json"
uv run pytest tests/test_postgres_*.py -q > "$receipt/integration.log" 2>&1
uv run python -m tests.postgres_restore_fixture
uv run python - <<'PY'
import asyncio
import os
import psycopg

async def verify():
    async with await psycopg.AsyncConnection.connect(os.environ['TEST_KNOWLEDGE_DSN'], autocommit=True) as conn:
        expected = {'log_error_verbosity': 'terse', 'log_parameter_max_length': '0',
                    'log_parameter_max_length_on_error': '0', 'log_statement': 'none',
                    'log_min_error_statement': 'panic'}
        for name, value in expected.items():
            row = await (await conn.execute('SELECT current_setting(%s)', (name,))).fetchone()
            assert row == (value,), 'PostgreSQL logging privacy setting is missing'
        await conn.execute('CREATE TEMP TABLE log_privacy_parent(id text PRIMARY KEY)')
        await conn.execute('CREATE TEMP TABLE log_privacy_child(id text REFERENCES log_privacy_parent(id))')
        try:
            await conn.execute('INSERT INTO log_privacy_child VALUES(%s)', ('PV_PRIVATE_LOG_MARKER_20261017',))
        except psycopg.errors.ForeignKeyViolation:
            pass
        else:
            raise AssertionError('privacy probe must trigger a real FK failure')
        await conn.execute('CREATE TEMP TABLE log_privacy_check(value text CHECK(length(value)<1))')
        try:
            await conn.execute("INSERT INTO log_privacy_check VALUES('PV_PRIVATE_LOG_MARKER_20261017')")
        except psycopg.errors.CheckViolation:
            pass
        else:
            raise AssertionError('privacy probe must trigger a real check failure')

asyncio.run(verify())
PY
docker logs "$name" > "$private/postgres.log" 2>&1
if grep -Fq 'PV_PRIVATE_LOG_MARKER_20261017' "$private/postgres.log"; then
  echo 'Private constraint marker leaked into PostgreSQL logs' >&2; exit 1
fi
if ! grep -Eq 'violates foreign key constraint|violates check constraint' "$private/postgres.log"; then
  echo 'Expected PostgreSQL operational errors were not captured' >&2; exit 1
fi
printf 'real_fk_error=observed\nreal_check_error=observed\nprivate_marker=absent\nsettings=verified\n' > "$receipt/log-privacy.txt"
unset TEST_KNOWLEDGE_DSN
docker exec "$name" psql -U knowledge_test -d pv_knowledge_test -Atc \
  "SELECT current_setting('server_version'); SELECT extversion FROM pg_extension WHERE extname='vector';" > "$receipt/versions.txt"
docker exec "$name" pg_dump -U knowledge_test -d pv_knowledge_test -Fc > "$private/public-knowledge.dump"
docker exec "$name" createdb -U knowledge_test pv_knowledge_restore
docker exec -i "$name" pg_restore -U knowledge_test -d pv_knowledge_restore --exit-on-error < "$private/public-knowledge.dump"
query="SELECT version,manifest_sha256,vector_sha256 FROM knowledge.revisions ORDER BY version; SELECT count(*) FROM knowledge.chunks; SELECT count(*),md5(coalesce(string_agg(md5(id || csrf_token || encode(secret_digest,'hex')),'' ORDER BY id),'')) FROM assistant_private.sessions; SELECT count(*),md5(coalesce(string_agg(md5(content || details),'' ORDER BY seq),'')) FROM assistant_private.messages; SELECT count(*),md5(coalesce(string_agg(run_id || ':' || reserved_micro::text || ':' || coalesce(actual_micro::text,'unknown') || ':' || status,'' ORDER BY run_id),'')) FROM assistant_private.spend_ledger;"
docker exec "$name" psql -U knowledge_test -d pv_knowledge_test -Atc "$query" > "$receipt/before-restore.txt"
docker exec "$name" psql -U knowledge_test -d pv_knowledge_restore -Atc "$query" > "$receipt/after-restore.txt"
cmp "$receipt/before-restore.txt" "$receipt/after-restore.txt"
docker restart --time 10 "$name" >/dev/null
for _ in $(seq 1 60); do
  if docker exec "$name" pg_isready -q -U knowledge_test -d pv_knowledge_restore; then break; fi
  sleep 0.5
done
docker exec "$name" psql -U knowledge_test -d pv_knowledge_restore -Atc "$query" > "$receipt/after-restart.txt"
cmp "$receipt/before-restore.txt" "$receipt/after-restart.txt"
docker exec "$name" cat /sys/fs/cgroup/memory.current > "$receipt/local-memory-current-bytes.txt"
docker exec "$name" cat /sys/fs/cgroup/memory.peak > "$receipt/local-memory-peak-bytes.txt"
docker inspect --format '{{json .Config.User}} {{json .HostConfig.ReadonlyRootfs}} {{.HostConfig.Memory}} {{.HostConfig.NanoCpus}}' "$name" > "$receipt/hardening.txt"
docker stop --time 10 "$name" >/dev/null
docker inspect --format '{{.State.ExitCode}} {{.State.OOMKilled}}' "$name" > "$receipt/shutdown.txt"
if [ "$(cat "$receipt/shutdown.txt")" != '0 false' ]; then echo 'PostgreSQL shutdown failed' >&2; exit 1; fi
printf 'image=%s\nintegration=PASS\nrestore_hashes=MATCH\nrestart_hashes=MATCH\npaid_calls=0\ndeployment=NO\n' "$image" > "$receipt/result.txt"
echo 'Isolated PG/pgvector integration, role boundaries, dump/restore/restart and graceful shutdown PASS'
