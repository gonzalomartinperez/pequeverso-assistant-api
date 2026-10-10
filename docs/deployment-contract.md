# Deployment contract (handoff to vps-ops / Coolify)

vps-ops and Coolify own production orchestration: proxy, DNS, TLS, secrets, volumes, backups,
schedules and rollouts. This repository owns the image, its runtime behavior and this contract.
Nothing here is deployed; no Compose file in this repository is a production authority.

## Image

| Item | Value |
|---|---|
| Build | `docker build --build-arg SERVICE_REVISION=<sha> -t pequeverso-assistant-api:<sha> .` from a clean checkout of an exact commit (context allowlisted by `.dockerignore`). An empty `SERVICE_REVISION` is allowed; the ops summary then reports `revision: null` |
| Base | `python:3.13-slim` and `ghcr.io/astral-sh/uv:0.12.21`, both pinned by digest; dependencies from `uv.lock` (`uv sync --frozen --no-dev`) |
| User | `65532:65532`; runs with a read-only root filesystem, `--cap-drop ALL`, `no-new-privileges` (verified by `scripts/smoke_container.sh`) |
| Writable paths | `/data` (volume), `/tmp` (tmpfs) |
| Process | `uvicorn app.main:app --workers 1 --no-proxy-headers --no-access-log --timeout-graceful-shutdown 15` |
| Port | `8000/tcp` (HTTP, plain; TLS terminates at the proxy) |
| Size / resources (measured locally 2026-10-05, fixture mode) | 235 MB uncompressed image (`docker images`); ~56 MiB RSS idle; graceful stop ≈ 1 s. Suggested limits: 256 MiB memory, 0.5 CPU. Live-model load was not measured |

**Single instance only.** Active-run cancellation and the concurrency limit are in-process, and
SQLite has one writer. Do not run replicas or more workers. Horizontal scaling would need a
shared store (a new ADR).

## Health

| Endpoint | Meaning | Use |
|---|---|---|
| `GET /health/live` | Process is up | Liveness |
| `GET /health/ready` | DB reachable and a valid catalog active. Body adds `catalog.revision` and `catalog.price_status` | Readiness, Docker `HEALTHCHECK` (built in), Coolify health check |

Health paths are internal; the public proxy routes only `/api/*`.

## Private operations API

`GET /internal/v1/ops/summary` (schema `contracts/ops.schema.json`, example
`contracts/examples/ops.summary.json`) serves aggregate health, catalog freshness, run counts,
latency percentiles, token usage and spend (confirmed / estimated / pending) to the backoffice.

- Exists only when `OPS_READ_TOKEN` is set (≥ 32 chars in production); otherwise `404`.
- `Authorization: Bearer <OPS_READ_TOKEN>`; wrong or missing token → `401 unauthorized`.
- **Never route `/internal/*` publicly.** Only the backoffice container calls it, over the
  private Docker network (e.g. `http://pequeverso-assistant-api:8000`). The token is defense in
  depth, not a reason to expose the path.
- Read-only, `Cache-Control: no-store`, no conversation content, session ids, client keys or
  e-mail addresses.

## Routing and proxy (SSE)

- Route `https://assistant.pequeverso.com/api/*` → container `:8000` **with the path unchanged**
  (the app serves `/api/v1/...`; FastAPI `root_path` is empty). Do not route any other paths
  on that host; the private backoffice uses a separate host.
- SSE: disable response buffering and compression for `/api/v1/messages` (the app sends
  `X-Accel-Buffering: no` and `Cache-Control: no-cache, no-transform`). Read timeout ≥ 90 s; the
  app sends a keep-alive comment every 15 s and bounds each run to 60 s (`RUN_TIMEOUT_SECONDS`;
  medium reasoning effort needs more headroom than the previous 45 s). Propagate client
  disconnects upstream (the app cancels the model call on disconnect).
- Forward `X-Forwarded-For` and set `TRUSTED_PROXY_CIDRS` to the proxy's network. The app walks the
  chain right to left and ignores the header from untrusted peers (uvicorn proxy headers are off
  on purpose).
- Request bodies are capped at 16 KiB in the app; a proxy limit of 64 KiB is enough.

## Environment and secrets

| Variable | Production value | Kind |
|---|---|---|
| `ENVIRONMENT` | `production` (enables fail-closed validation) | config |
| `ASSISTANT_ENABLED` | `true`, or `false` as a kill switch (API answers `assistant_disabled`; the store is unaffected) | config |
| `AI_PROVIDER` / `ALLOW_PAID_AI` | `openai` / `true`: only after the owner authorizes paid use. Production refuses fixture answers while enabled | config |
| `OPENAI_API_KEY` | Key of a **separate Pequeverso OpenAI project** (never the portfolio's) | **secret** |
| `OPENAI_MODEL` / `OPENAI_REASONING_EFFORT` | `gpt-6-luna` / `medium` (owner decision; verified as supported in OpenAI's model page 2026-10-05) | config |
| `MAX_OUTPUT_TOKENS` | `4000` (includes reasoning tokens; tune after the authorized live evaluation) | config |
| `OPS_READ_TOKEN` | ≥ 32 random chars, shared only with the backoffice container | **secret** |
| `SERVICE_REVISION` | Set at build time (image `ARG`); not a runtime secret | build |
| `MONTHLY_BUDGET_USD` / `DAILY_BUDGET_USD` / `BUDGET_SAFETY_MARGIN` | `10.00` / `1.00` / `0.10` (design target; not a billing setting). Also set a hard limit in the OpenAI project | config |
| `ALLOWED_ORIGINS` | `["https://pequeverso.com"]`: the storefront that hosts the native assistant (exact origin; add `https://www.pequeverso.com` only if the store serves pages there, which today it redirects to the apex) | config |
| `SESSION_COOKIE_SECURE` | `true` (required by production validation) | config |
| `CLIENT_HASH_KEY` | ≥ 32 random chars (HMAC key for pseudonymous rate limiting) | **secret** |
| `TRUSTED_PROXY_CIDRS` | Exact approved proxy peer CIDRs, e.g. `["10.0.0.4/32"]` (example only) | config |
| `DATABASE_PATH` | `/data/assistant.sqlite3` (image default) | config |
| `CATALOG_URL` | unset (bundled snapshot). Set only if the storefront publishes the catalog document | config |
| `CATALOG_PRICE_MAX_AGE_HOURS` | `168` | config |

Validation refuses to start with unsafe combinations: a paid provider without opt-in and key,
fixture answers in production, non-https or localhost origins, insecure cookies, a missing or
short `CLIENT_HASH_KEY`, or a daily budget above the monthly one.

## Persistence and migrations

- **Volume `/data`** holds one SQLite database (WAL mode: `assistant.sqlite3`, `-wal`, `-shm`).
  It contains sessions (24 h retention), messages, runs, the spend ledger, rate counters and
  catalog snapshots, plus content-free run metrics (90-day retention) for operations.
- **Migrations** are versioned SQL (`migrations/NNN_*.sql`, tracked with `PRAGMA user_version`),
  applied automatically at startup inside a transaction. There is no separate migration job.
  A new image never edits an old migration.
- **Backup:** the ledger is the only data worth keeping long term (it enforces the monthly budget).
  Use Python sqlite3 from the same image (online backup recipe below),
  or stop the container and copy the three files together. Losing the volume loses conversations
  (by design short-lived) and resets the month's spend counter: keep the assistant disabled
  until safe restoration and spend reconciliation. Verified provider controls are defense in
  depth, never a substitute for the ledger.
- **Restart:** runs left active by a crash are marked failed at startup; their pending ledger
  reservations become `unreported` and stay counted as estimated spend.

## Rollout and rollback

- **Deploy:** pull the image by digest, then start it. Readiness goes green once the migrations are
  applied and the bundled catalog is loaded (a few seconds).
- **Rollback:** redeploy the previous image digest on the same volume only after checking
  the schema. The current schema is migration 002. An image built before 002 can read the
  additive columns and tables, but **not** messages stored with the new `language_unsupported`
  notice, so it would fail to load those sessions. Rolling back across 002 therefore needs one
  of: restoring the pre-deploy backup, or deleting conversations first
  (`DELETE FROM sessions;`, which removes only short-lived chats; the ledger and metrics stay).
  The old image also does not record run metrics, and its ledger rows keep status `pending`
  until the newer image starts again, which maps them back to `settled`/`unreported`. Take a
  backup before every deploy that adds a migration.
- **Graceful stop:** `SIGTERM`, then up to 15 s to finish streams; active runs end as
  cancelled.
- **Kill switch:** `ASSISTANT_ENABLED=false` or stopping the container. The native storefront
  assistant shows "unavailable" and the store keeps selling.

## Browser and origin assumptions (native storefront assistant)

The storefront (`https://pequeverso.com`, static export on its current hosting) renders the
assistant natively and calls this API **cross-origin** at the API's own HTTPS origin
(proposed `https://assistant.pequeverso.com`, pending owner approval and DNS). There is no
iframe and no same-origin `/api` on the storefront: its static hosting has no verified proxy
capability, and the VPS proxy belongs to vps-ops.

- **CORS:** exact `ALLOWED_ORIGINS` (`https://pequeverso.com`), `Access-Control-Allow-Credentials:
  true`, methods `GET, POST, DELETE`, request headers `Content-Type, X-CSRF-Token,
  Idempotency-Key, X-Request-ID`, exposed `X-Request-ID, X-Run-ID, Retry-After`, preflight
  cached 600 s. Never a wildcard. The proxy must pass `OPTIONS` through and must not add its own
  CORS headers.
- **Cookies:** host-only `__Host-pv_assistant` on the API host, `Secure; HttpOnly;
  SameSite=Lax; Path=/`. `pequeverso.com` and `assistant.pequeverso.com` are the same *site*, so
  the browser sends the Lax cookie on the store's credentialed `fetch`; they are different
  *origins*, so CORS, the Origin check and the CSRF token all still apply. No `Domain`
  attribute and no `SameSite=None`. A browser that blocks all cookies gets a new session per
  page load (the assistant still answers; history is not restored).
- **CSRF:** Origin allowlist on every mutation + per-session token returned in the
  `POST /session` body (kept in memory by the store, never in storage or URLs).
- **Storefront CSP:** its `connect-src` must allow the API origin when the assistant is enabled
  (storefront handoff).
- **Kill switches:** the storefront build flag (requires a storefront rebuild) and
  `ASSISTANT_ENABLED=false` here (instant; the store shows "unavailable" and keeps selling).

## Verification after deployment (owner-run)

1. `GET /health/ready` through the internal network: `status: ready`, catalog revision as
   expected.
2. `POST /api/v1/session` with `Origin: https://pequeverso.com`: `201`, `Access-Control-Allow-Origin` echoes the store origin with credentials allowed, `__Host-pv_assistant` cookie `Secure;
   HttpOnly; SameSite=Lax`.
3. One question through the proxy: incremental `message.delta` events arrive before
   `run.completed` (no buffering).
4. Only with paid use authorized: the ledger shows a settled row (`actual_micro` set).

## Bounded runtime and disk operations (2026-10-10)

The application image does not set host quotas. vps-ops must carry the tested runtime policy
into its own reviewed configuration; these commands are a local isolation recipe, not a deploy.
The smoke uses 256 MiB memory, no additional swap, 0.5 CPU, 64 PIDs, and a 64 MiB tmpfs at
`/tmp` with `noexec,nosuid,nodev`. The root is read-only; only the named `/data` volume persists.
Docker's `local` log driver rotates at 10 MiB × 3 files (compression may use less); stdout is
already content-free structured JSON, and uvicorn access logging is disabled.

```bash
# Operator supplies an approved digest, private network and configuration separately.
# In isolated synthetic acceptance: AI_PROVIDER=fixture and ALLOW_PAID_AI=false.
# Production can keep ASSISTANT_ENABLED=false; no paid-provider opt-in is implied.
docker run --name pv-api-isolated --read-only \
  --memory 256m --memory-swap 256m --cpus 0.5 --pids-limit 64 \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
  --cap-drop ALL --security-opt no-new-privileges \
  --log-driver local --log-opt max-size=10m --log-opt max-file=3 \
  --network "$PV_API_PRIVATE_NETWORK" --env-file "$PV_API_CONFIG_FILE" \
  --mount type=volume,src="$PV_API_DATA_VOLUME",dst=/data "$PV_API_IMAGE_DIGEST"
```

A bind-mounted data directory must be owned by uid/gid 65532; a new named volume inherits the
image's ownership. Do not run a startup root chown or give the service access to the Docker
socket. Keep the default Docker seccomp profile. Never place SQLite on NFS/network storage,
share it across replicas or make `/data` ephemeral. Readiness requires the database and active
catalog; healthy/readiness does **not** mean the storefront is enabled or the model validated.

### Ledger durability and backup/restore

WAL uses `synchronous=FULL`: each committed transaction syncs the WAL before acknowledging it.
This strengthens committed ledger durability across host failure, provided the filesystem and
storage honor sync requests. It does not certify the VPS power-loss behavior or replace backups;
see [SQLite synchronous](https://sqlite.org/pragma.html#pragma_synchronous). It costs more write
latency than NORMAL; local fixture measurements are only a small-workload baseline.

The runtime has Python's sqlite3, not the sqlite3 CLI. An online backup can therefore be made
with the **same image**, without installing tools in the runtime:

```bash
# Exact running local/approved container; /data belongs to that service alone.
docker exec "$PV_API_CONTAINER" python -c '
from contextlib import closing
import sqlite3
with closing(sqlite3.connect("file:/data/assistant.sqlite3?mode=ro", uri=True)) as source, closing(sqlite3.connect("/data/assistant-backup.sqlite3")) as backup:
    assert source.execute("PRAGMA user_version").fetchone()[0] == 2
    source.execute("SELECT actual_micro,reserved_micro FROM spend_ledger LIMIT 1").fetchall()
    source.backup(backup)
    assert backup.execute("PRAGMA user_version").fetchone()[0] == 2
    assert backup.execute("PRAGMA quick_check").fetchone()[0] == "ok"
'
# Transfer the single consistent backup to encrypted off-server retention via vps-ops.
# Remove its local staging copy only after verifying the transfer and its retention policy.
```

The smoke restores its online backup into a stopped **disposable** volume, starts the same
image, and verifies both conversation continuity and charged spend. In production, restore into
an isolated new volume first; verify quick_check, schema/user_version, ledger month sums,
readiness and synthetic session before considering an authorized switchover. Start recovery with
`ASSISTANT_ENABLED=false`: a historical snapshot omits spend incurred after the backup. Keep
paid turns disabled until the owner reconciles that interval against provider usage and existing
ledger/run evidence, or accounts for it conservatively in the remaining budget. Unknown spend
is not zero; a provider project budget must not be assumed to be an enforced hard cap. The
[official OpenAI spend-limit guide](https://developers.openai.com/api/docs/guides/spend-limits)
distinguishes spend alerts from an explicitly enforced hard limit; enforcement can lag and
slightly overshoot. No Pequeverso project configuration or enforcement was inspected here. The
smoke proves restoration of its just-taken snapshot, not production RPO or spend reconciliation.
Never replace a live database file or copy only the main file while WAL writes are active. Image rollback does
not restore or reset ledger data. Preserve the backup taken before a migration.

### Monitoring without new infrastructure

Use existing private ops summary and internal health probes; no public metrics endpoint or
collector is introduced (ADR-0005). An authorized operator can inspect Docker health,
`State.OOMKilled`, cgroup `memory.events`, memory/CPU/PIDs and free space through its existing
host tooling. Proposed warnings: memory sustained ≥ 80% of 256 MiB, any OOM, not-ready for two
probe intervals, month spend ≥ 80% cutoff, stale price/catalog fetch failure. Collect aggregate
counts and latencies, never conversation bodies or secrets.

Volume monitoring must include `assistant.sqlite3`, `-wal`, `-shm` and backup staging files.
SQLite deleted pages are reused but the database need not shrink; run no automatic VACUUM or
ledger purge. Review sustained WAL > 64 MiB (long readers can delay checkpoint), volume > 1 GiB,
less than 1 GiB free host space or less than 20% free: warn and diagnose, never delete ledger
rows to recover space. Reserve room for at least two backup copies and the working database;
actual retention/RPO/RTO and disk allocation are vps-ops/owner decisions. Spend and catalog
snapshots are not a substitute for a verified off-server restore drill.

The builder and runtime are separate; uv and developer packages never ship. Dependency layers
are keyed by pyproject/uv.lock. Revision metadata comes after filesystem layers so rebuilding
only SERVICE_REVISION reuses them. Build intermediate caches are host-owned, not runtime
volumes: inspect `docker system df`, retain current and known-good rollback image digests, and
remove only explicitly retired image tags/cache under the operator's policy. Never use a
blanket system/volume prune; application data and other projects are out of scope.

For reproducible local verification: `scripts/smoke_container.sh [exact-image]`. The fixture
probe checks an explicit local container with AI_PROVIDER=fixture/ALLOW_PAID_AI=false and four
concurrent streams. Its cgroup-v2 peak includes page cache and differs from Docker's reported
cache-subtracted idle usage. This is not a live-provider benchmark or capacity guarantee.

### Image security maintenance

Both Python stages are pinned to the same official Python 3.13.16 amd64 image digest
`sha256:8fb4cfa1a2616d7b8e0c2175cc6ad68f5729c34ea8488c0b360d2934b7be9024`.
The inspected base includes Debian libpcre2 10.46-1~deb13u3 and OpenSSL/libssl/provider
3.5.7-1~deb13u3, fixing the previously scanned patchable HIGH findings
CVE-2026-103111 and CVE-2026-84782. See the
[Debian PCRE2 advisory](https://security-tracker.debian.org/tracker/CVE-2026-103111),
[Debian OpenSSL advisory](https://security-tracker.debian.org/tracker/CVE-2026-84782), and
[Python 3.13.16 release notes](https://www.python.org/downloads/release/python-31316/).

The runtime removes global pip and its vendored packages; the isolated, frozen `/opt/venv`
contains application dependencies and does not need an installer. This removes the unused
vendored msgpack/setuptools/urllib3 findings rather than changing application lockfiles.
The builder retains its tools. Scan each exact candidate image and retain the report/SBOM;
these targeted changes do not imply that all OS advisories are fixed or that deployment is
authorized. Unfixed advisories require explicit review before activation.
