# Handoff to vps-ops: Pequeverso assistant API and backoffice

Answers the "Concrete request to the application agent" in vps-ops
`docs/handoffs/pequeverso-assistant.md` (inspected at vps-ops `develop` `04be619`). This is a
handoff, not an authorization: no image is published, and no DNS record, route, database,
secret, Coolify resource or paid provider use exists or is approved by this document. vps-ops
remains the only infrastructure authority; nothing here modifies vps-ops.

## Topology change since the vps-ops planning record

The inventory still describes one web service serving `/` and `/embed` plus `/api/` on
`assistant.pequeverso.com`. That frontend no longer serves a public chat:

| Component | Repository | Hosting | Public? |
|---|---|---|---|
| Storefront with the **native** assistant (disabled by default; no iframe) | `gonzalomartinperez/pequeverso` | Unchanged: its current Hostinger hosting. Consumes **no** VPS resources or Hostinger Node slots | Yes |
| Assistant API | `gonzalomartinperez/pequeverso-assistant-api` | VPS, Coolify | `/api/*` only |
| Private backoffice (OAuth, owner/viewer, ops dashboard) | `gonzalomartinperez/pequeverso-assistant-backoffice` (renamed from `pequeverso-assistant-web` on 2026-10-05; GitHub redirects the old name, which the vps-ops inventory still uses) | VPS, Coolify | Only behind its own sign-in |
| Backoffice PostgreSQL (identity and access only) | — | VPS, private network, project volume | Never |

So the planned `web` service becomes the **backoffice** on a **separate host** and the iframe,
`frame-ancestors` and `/embed` requirements disappear. The storefront talks to the API
cross-origin from the browser.

## Answers to the six requests

1. **Images.** Not published. Each repository builds from `Dockerfile` at a reviewed commit;
   CI builds the exact image and smoke-tests it (API: `scripts/smoke_container.sh`; backoffice:
   `scripts/smoke-image.sh`). Both are `linux/amd64`, non-root (API uid 65532; backoffice uid
   1000), read-only root with tmpfs, `--cap-drop ALL`, `no-new-privileges`. Ports: API
   `8000/tcp`, backoffice `3000/tcp`. Measured idle memory (local, fixture data): API ~56 MiB,
   backoffice ~64–77 MiB; image sizes ~235 MB and ~97 MB uncompressed. Proposed limits: API 0.5
   CPU / 256 MiB, backoffice 1 CPU / 384 MiB (request 0.1 CPU / 128 MB). Live-model load is not
   measured. Publication to a private registry by digest needs separate authorization.
2. **Health and persistence.**
   - API: `GET /health/live` (liveness), `GET /health/ready` (database + valid catalog; Docker
     `HEALTHCHECK` built in). State: one SQLite file in WAL mode on volume `/data` (sessions 24 h,
     spend ledger, content-free run metrics 90 days, catalog snapshots). Migrations run
     automatically at startup inside a transaction. **Single instance, one worker.** Backup:
     Python sqlite3 `Connection.backup` from the same image (online-safe; concrete recipe in
     `docs/deployment-contract.md`) before each deploy and daily; the spend ledger is the data worth keeping (it enforces the monthly budget).
   - Backoffice: `GET /healthz` (liveness), `GET /readyz` (config + PostgreSQL + migrated
     tables). Stateless container; PostgreSQL holds operator identities, encrypted OAuth tokens,
     sessions, invitations and an id-only audit. Migrations are a **one-shot** command of the same
     image digest (`node scripts/db-migrate.ts`), additive, advisory-locked, idempotent; run them
     before starting a new digest. Backups: daily encrypted `pg_dump -Fc`, off-server, restore
     drill before activation. Tested with PostgreSQL 17.6 and 18.4.
   - Rollback: previous digest on the same data. Across API migration 002 see
     `docs/deployment-contract.md` (needs the backup or clearing conversations). Image rollback
     never restores data.
3. **Paths and streaming.** API routes include `/api` (`/api/v1/...`), `root_path` empty: route
   `/api/*` **unchanged** (no stripping). SSE on `POST /api/v1/messages`: no buffering, no
   compression, read timeout ≥ 90 s (runs end at 60 s; keep-alive comment every 15 s),
   propagate client disconnects. `/health/*` and `/internal/*` must **never** be routed publicly.
4. **Origins (proposals, pending owner approval and DNS).** Storefront origin
   `https://pequeverso.com` (apex; `www` redirects there). API: `https://assistant.pequeverso.com`
   (inventory's proposed domain), `/api/*` only. Backoffice: a separate host, e.g.
   `backoffice.assistant.pequeverso.com` (example only). Cross-origin contract (storefront → API):
   exact `ALLOWED_ORIGINS=["https://pequeverso.com"]`, credentials allowed, preflight answered by
   the API (the proxy must pass `OPTIONS` and add **no** CORS headers of its own); host-only
   `__Host-pv_assistant` cookie (`Secure; HttpOnly; SameSite=Lax`), no `Domain`, no
   `SameSite=None`; Origin allowlist + per-session CSRF token on every mutation. No browser-held
   OpenAI key. Private responses are `no-store`; never cache at the proxy/CDN.
5. **Storefront disable switch.** Build-time `NEXT_PUBLIC_ASSISTANT_ENABLED` (absent or `false`
   = no assistant code in the export, verified by `npm run check:assistant-disabled`, which the
   store's build and Deploy workflow run). Changing it requires a storefront rebuild and release;
   vps-ops cannot flip it. The API has an instant kill switch: `ASSISTANT_ENABLED=false` (the
   store then shows "unavailable" and keeps selling). API outage, budget exhaustion or a missing
   widget never affect product browsing or the Hotmart checkout (store e2e covers the disabled
   build; the enabled suite covers unavailable states).
6. **Secrets and metrics.** Proposed secret names:
   `pequeverso-assistant-openai` (OpenAI key of a **separate Pequeverso project**, never the
   portfolio's), `pequeverso-assistant-client-hash-key`, `pequeverso-assistant-ops-read-token`
   (shared by API and backoffice), `pequeverso-backoffice-auth-secret`,
   `pequeverso-backoffice-database-url`, `pequeverso-backoffice-google-oauth`,
   `pequeverso-backoffice-github-oauth`. Budget: USD 10/month (configurable), enforced per request
   with atomic worst-case reservations, a 10 % margin and a daily cap; spend is reported as
   confirmed / estimated / pending; when cost is unknown the reservation stays counted; when the
   budget is exhausted the API refuses new questions (`budget_exhausted`). Also set a hard limit
   in the OpenAI project. Aggregate metrics: the private `GET /internal/v1/ops/summary` (bearer
   token) — schema `contracts/ops.schema.json`; no Prometheus endpoint yet (ADR-0005). Proposed
   alerts if vps-ops scrapes later: month spend ≥ 80 % / 100 % of the cutoff, catalog
   `price_status=unverified`, `last_failure` set, readiness failing. No conversation content,
   e-mail, cookie or secret is ever in logs or metrics.

## Networks and routing (proposal)

| Network | Members |
|---|---|
| `pequeverso-assistant-production-ingress` (reserved) | Coolify's proxy, API, backoffice |
| new internal network (proposal) | backoffice, API (for `/internal/v1/ops`), backoffice PostgreSQL |

Set `TRUSTED_PROXY_CIDRS` (API) and `TRUSTED_PROXY_IPS` (backoffice) to the exact proxy
container address(es). Volumes (proposal): `pequeverso-assistant-production-api-data` (`/data`),
`pequeverso-assistant-production-backoffice-pg`. Never attach portfolio services.

## Acceptance before activation (isolated, synthetic, no paid calls)

1. Both images by digest: health, readiness, non-root, read-only, migrations.
2. From an HTTPS host page on `https://pequeverso.com`-equivalent test origin: preflight,
   credentialed session, CSRF, incremental SSE timing through the proxy, stop/disconnect,
   disallowed origin refused (403), `/internal/*` and `/health/*` unreachable from outside.
3. Backoffice: real OAuth apps (owner-created), owner sign-in, invitation, revocation, HSTS,
   `__Secure-` cookies through TLS; ops summary reachable only on the internal network.
4. Simulate API loss and `budget_exhausted`: storefront browsing and checkout continue (no real
   purchase).
5. Backups taken and one restore drill for both data stores.

Activation itself (DNS, Coolify resources, enabling the storefront flag, paid model use) needs
the owner's explicit, separate authorization.

## Runtime budget and disk handoff update (2026-10-10)

Carry the API's reviewed bounded runtime recipe from `docs/deployment-contract.md` into future
vps-ops configuration: 256 MiB / 0.5 CPU, no extra swap, 64 PIDs, 64 MiB hardened `/tmp`,
read-only root, uid65532, cap-drop ALL/no-new-privileges and rotating local logs (10 MiB × 3).
The application remains one process/worker and does not change proxy, network or deployment
state. Use the committed smoke and its exact-image evidence, not an assumed aggregate limit.

SQLite WAL now requests FULL synchronization for committed ledger durability. Online backup
uses Python sqlite3 already in the same image; the smoke performs a real restore into its own
stopped disposable volume and rechecks charged spend. Recovery from an older backup starts
with ASSISTANT_ENABLED=false until post-snapshot spend is reconciled or conservatively accounted
for; unknown usage is never zero and project budget settings are not an assumed hard cap.
Storage must honor fsync; the VPS has not
been subjected to a power-loss test. Keep encrypted off-server backups and a separate restore
exercise. Monitor data/WAL/staged-backup bytes, host free space, image/cache usage and bounded
container logs; never purge financial history or prune other projects to satisfy a disk alert.
No monitoring service is added: existing private ops and internal readiness supply aggregates,
while Docker/host metrics belong to vps-ops. Neither release nor this handoff enables the
storefront, publishes an image or authorizes an infrastructure action.
