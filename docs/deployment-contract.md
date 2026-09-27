# Deployment contract (handoff to vps-ops / Coolify)

vps-ops and Coolify own production orchestration: proxy, DNS, TLS, secrets, volumes, backups,
schedules and rollouts. This repository owns the image, its runtime behavior and this contract.
Nothing here is deployed; no Compose file in this repository is a production authority.

## Image

| Item | Value |
|---|---|
| Build | `docker build -t pequeverso-assistant-api:<sha> .` from a clean checkout of an exact commit (context allowlisted by `.dockerignore`) |
| Base | `python:3.13-slim` and `ghcr.io/astral-sh/uv:0.12.10`, both pinned by digest; dependencies from `uv.lock` (`uv sync --frozen --no-dev`) |
| User | `65532:65532`; runs with a read-only root filesystem, `--cap-drop ALL`, `no-new-privileges` (verified by `scripts/smoke_container.sh`) |
| Writable paths | `/data` (volume), `/tmp` (tmpfs) |
| Process | `uvicorn app.main:app --workers 1 --no-proxy-headers --no-access-log --timeout-graceful-shutdown 15` |
| Port | `8000/tcp` (HTTP, plain; TLS terminates at the proxy) |
| Size / resources (measured locally, fixture mode) | ~53 MB image; ~55 MiB RSS idle; graceful stop ≈ 1 s. Suggested limits: 256 MiB memory, 0.5 CPU. Live-model load was not measured |

**Single instance only.** Active-run cancellation and the concurrency limit are in-process, and
SQLite has one writer. Do not run replicas or more workers. Horizontal scaling would need a
shared store (a new ADR).

## Health

| Endpoint | Meaning | Use |
|---|---|---|
| `GET /health/live` | Process is up | Liveness |
| `GET /health/ready` | DB reachable and a valid catalog active. Body adds `catalog.revision` and `catalog.price_status` | Readiness, Docker `HEALTHCHECK` (built in), Coolify health check |

Health paths are internal; the public proxy routes only `/api/*`.

## Routing and proxy (SSE)

- Route `https://assistant.pequeverso.com/api/*` → container `:8000` **with the path unchanged**
  (the app serves `/api/v1/...`; FastAPI `root_path` is empty). Everything else on that host goes
  to the web app.
- SSE: disable response buffering and compression for `/api/v1/messages` (the app sends
  `X-Accel-Buffering: no` and `Cache-Control: no-cache, no-transform`). Read timeout ≥ 60 s; the
  app sends a keep-alive comment every 15 s and bounds each run to 45 s. Propagate client
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
| `OPENAI_MODEL` / `OPENAI_REASONING_EFFORT` | `gpt-6-luna` / `low` | config |
| `MONTHLY_BUDGET_USD` / `DAILY_BUDGET_USD` / `BUDGET_SAFETY_MARGIN` | `10.00` / `1.00` / `0.10` (design target; not a billing setting). Also set a hard limit in the OpenAI project | config |
| `ALLOWED_ORIGINS` | `["https://assistant.pequeverso.com"]` | config |
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
  catalog snapshots.
- **Migrations** are versioned SQL (`migrations/NNN_*.sql`, tracked with `PRAGMA user_version`),
  applied automatically at startup inside a transaction. There is no separate migration job.
  A new image never edits an old migration.
- **Backup:** the ledger is the only data worth keeping long term (it enforces the monthly budget).
  Use `sqlite3 /data/assistant.sqlite3 ".backup '/backup/assistant-<date>.sqlite3'"` (online-safe),
  or stop the container and copy the three files together. Losing the volume loses conversations
  (by design short-lived) and resets the month's spend counter; keep the OpenAI project's hard
  limit as the backstop.
- **Restart:** runs left active by a crash are marked failed at startup; their reservations stay
  counted.

## Rollout and rollback

- **Deploy:** pull the image by digest, then start it. Readiness goes green once the migrations are
  applied and the bundled catalog is loaded (a few seconds).
- **Rollback:** redeploy the previous image digest on the same volume. This is safe as long as
  the newer image added no migration; the current schema is migration 001. If a future
  release adds a migration, its PR states whether the previous image tolerates it. Otherwise
  restore the pre-deploy backup.
- **Graceful stop:** `SIGTERM`, then up to 15 s to finish streams; active runs end as
  cancelled.
- **Kill switch:** `ASSISTANT_ENABLED=false` or stopping the container. The web app shows
  "unavailable" and the store keeps selling.

## Browser and origin assumptions

- Storefront `pequeverso.com` embeds `https://assistant.pequeverso.com/embed` in an iframe
  (same-site). The web app owner sets `frame-ancestors https://pequeverso.com` on `/embed`. The API
  sends JSON and SSE only and needs no framing.
- The API allows CORS only for `ALLOWED_ORIGINS`. In the proposed same-origin topology CORS is not
  used at all; do not add the storefront origin unless it must call the API directly.
- Cookies are host-only on `assistant.pequeverso.com`. No Domain attribute and no
  `SameSite=None`.

## Verification after deployment (owner-run)

1. `GET /health/ready` through the internal network: `status: ready`, catalog revision as
   expected.
2. `POST /api/v1/session` from the web origin: `201`, `__Host-pv_assistant` cookie `Secure;
   HttpOnly; SameSite=Lax`.
3. One question through the proxy: incremental `message.delta` events arrive before
   `run.completed` (no buffering).
4. Only with paid use authorized: the ledger shows a settled row (`actual_micro` set).
