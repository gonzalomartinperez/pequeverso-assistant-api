# Deployment contract (handoff to vps-ops / Coolify)

vps-ops and Coolify own production orchestration: proxy, DNS, TLS, secrets, volumes, backups,
schedules and rollouts. This repository owns the image, its runtime behavior and this contract.
Nothing here is deployed; no Compose file in this repository is a production authority.

## Image

| Item | Value |
|---|---|
| Build | `docker build --build-arg SERVICE_REVISION=<sha> -t pequeverso-assistant-api:<sha> .` from a clean checkout of an exact commit (context allowlisted by `.dockerignore`). An empty `SERVICE_REVISION` is allowed; the ops summary then reports `revision: null` |
| Base | `python:3.13-slim` and `ghcr.io/astral-sh/uv:0.12.10`, both pinned by digest; dependencies from `uv.lock` (`uv sync --frozen --no-dev`) |
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
  (the app serves `/api/v1/...`; FastAPI `root_path` is empty). Everything else on that host goes
  to the web app.
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
| `TRUSTED_PROXY_CIDRS` | Proxy network, e.g. `["10.0.0.0/8"]` | config |
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
  Use `sqlite3 /data/assistant.sqlite3 ".backup '/backup/assistant-<date>.sqlite3'"` (online-safe),
  or stop the container and copy the three files together. Losing the volume loses conversations
  (by design short-lived) and resets the month's spend counter; keep the OpenAI project's hard
  limit as the backstop.
- **Restart:** runs left active by a crash are marked failed at startup; their pending ledger
  reservations become `unreported` and stay counted as estimated spend.

## Rollout and rollback

- **Deploy:** pull the image by digest, then start it. Readiness goes green once the migrations are
  applied and the bundled catalog is loaded (a few seconds).
- **Rollback:** redeploy the previous image digest on the same volume. The current schema is
  migration 002 (additive: new ledger columns, `run_metrics` table, `catalog_state.last_failure_at`).
  An image built before 002 runs against a 002 database because it never reads the new columns
  and its `INSERT`s omit them (defaults apply); it will not record run metrics. Rolling back
  *data* to 001 needs the pre-deploy backup. Take a backup before every deploy that adds a
  migration.
- **Graceful stop:** `SIGTERM`, then up to 15 s to finish streams; active runs end as
  cancelled.
- **Kill switch:** `ASSISTANT_ENABLED=false` or stopping the container. The web app shows
  "unavailable" and the store keeps selling.

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
