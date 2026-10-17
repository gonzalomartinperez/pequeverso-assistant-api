# Deployment contract (handoff to vps-ops / Coolify)

vps-ops and Coolify own production orchestration: proxy, DNS, TLS, secrets, volumes, backups,
schedules and rollouts. This repository owns the image, its runtime behavior and this contract.
Nothing here is deployed; no Compose file in this repository is a production authority.

## Image

| Item | Value |
|---|---|
| Build | `docker build --build-arg SERVICE_REVISION=<sha> -t pequeverso-assistant-api:<sha> .` from a clean checkout of an exact commit (context allowlisted by `.dockerignore`). An empty `SERVICE_REVISION` is allowed; the ops summary then reports `revision: null` |
| Base | `python:3.14.8-slim-trixie` and `ghcr.io/astral-sh/uv:0.13.0`, both pinned by digest; dependencies from `uv.lock` (`uv sync --frozen --no-dev`) |
| User | `65532:65532`; runs with a read-only root filesystem, `--cap-drop ALL`, `no-new-privileges` (verified by `scripts/smoke_container.sh`) |
| Writable paths | `/data` (volume), `/tmp` (tmpfs) |
| Process | `uvicorn app.main:app --workers 1 --no-proxy-headers --no-access-log --timeout-graceful-shutdown 15` |
| Port | `8000/tcp` (HTTP, plain; TLS terminates at the proxy) |
| Size / resources (measured locally 2026-10-13, fixture mode) | Exact combined candidate: 57,024,366 bytes; idle memory 69.27 MiB, cgroup peak 89,403,392 bytes. Core smoke stop 2.02 s. Tested limits: 256 MiB memory, no additional swap, 0.5 CPU, 64 PIDs. Current container stop grace: at least **40 s**; see separately identified active-stream evidence below. No VPS capacity claim |

Current local acceptance belongs to combined application commit
`cf19c3beac8e51bcb4ed805af7d92a99c42f8ce6`, image
`sha256:0691367b0a86087d2fc0904f7507e16aa77d8599d6bcd8b953343fc5472cde8d`.
See [the phased exact-image evidence](verification/post-tools-2026-10-13.md).
The combined head normally merges reviewed runtime/dependency PR52 and the finite final
language/citation fix. Later squash integrations or documentation changes do not relabel this
local image as a main release build. BuildKit is required by the pinned Dockerfile frontend and
cache mounts; the local acceptance used verified official Buildx 0.38.0 with the existing Docker
driver. vps-ops selects its compatible build tooling and rebuilds/smokes the exact release commit.
No image has been published or deployed.

### Historical acceptance — 2026-10-10 (superseded)

These measurements belong to local linux/amd64 image
`sha256:bcaec035a74f8e738e0cdc63062ec64d9ed9efa9e47721b08f1cffc0f36ea9aa`,
built from candidate `255feebd5589eb78ca05ba8b6a2b14e8fa575c70`. The application tree
matches develop squash `6fc5d92d63bbb8f71bce8916f324b86ae0f9237d`; subsequent documentation
changes do not relabel this digest as a release-built image. It was not published or deployed.
The local acceptance receipt used fixture mode, no paid calls, a read-only root, dropped
capabilities, no new privileges, a 64 MiB `/tmp` tmpfs and rotated local logs. Four concurrent
fixture streams completed in 404–532 ms; live-model load and VPS capacity were not measured.

Active-stream SIGTERM exited with code 0, without OOM. Before restarting, an independent
volume snapshot already contained three cancelled runs, one completed run and three
`unreported` reservations; unknown spend remained reserved and no partial assistant answer
was persisted. Restart restored five messages. The disconnected transport had no terminal
SSE frame: these checks establish persisted state, not guaranteed terminal delivery. Carry
the then-minimum 30-second container grace into Coolify/Compose. The current observability-capable
candidate requires at least 40 seconds instead; verify it under VPS load.

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
  `X-Accel-Buffering: no` and `Cache-Control: no-cache, no-transform`). Allow at least90s for
  the streaming response/write; this is **not** a request-body read deadline. The app sends a
  keep-alive comment every15s and bounds each run to60s (`RUN_TIMEOUT_SECONDS`; medium
  reasoning effort needs more headroom than the previous45s). Propagate client disconnects
  upstream (the app cancels the model call on disconnect).
- The inspected vps-ops `main` `2b310f2ee86e600f13c87a29806569adb3e8e10e` input at
  `infra/edge/coolify-traefik.yaml` proposes request `readTimeout: 15s`, response
  `writeTimeout: 135s` and upstream `responseHeaderTimeout: 135s`. These are distinct controls:
  Traefik's [entrypoint timeouts](https://doc.traefik.io/traefik/reference/install-configuration/entrypoints/)
  cover reading the complete request and writing the response respectively. SSE does not
  require raising the request-body read timeout. vps-ops owns the final reviewed proxy settings
  and verifies actual incremental delivery/cancellation; these source inputs are not deployed.
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
| `MONTHLY_BUDGET_USD` / `DAILY_BUDGET_USD` / `BUDGET_SAFETY_MARGIN` | `10.00` / `1.00` / `0.10` (design target; not a billing setting). Verify actual project billing controls separately; budget alerts are not assumed hard caps | config |
| `ALLOWED_ORIGINS` | `["https://pequeverso.com"]`: the storefront that hosts the native assistant (exact origin; add `https://www.pequeverso.com` only if the store serves pages there, which today it redirects to the apex) | config |
| `SESSION_COOKIE_SECURE` | `true` (required by production validation) | config |
| `CLIENT_HASH_KEY` | ≥ 32 random chars (HMAC key for pseudonymous rate limiting) | **secret** |
| `TRUSTED_PROXY_CIDRS` | Exact approved proxy peer CIDRs, e.g. `["10.0.0.4/32"]` (example only) | config |
| `DATABASE_PATH` | `/data/assistant.sqlite3` (image default) | config |
| `CATALOG_URL` | unset (bundled snapshot). Set only if the storefront publishes the catalog document | config |
| `CATALOG_PRICE_MAX_AGE_HOURS` | `168` | config |
| `OFFICIAL_HELP_ENABLED` | `false` (default). Optional three fixed public Hotmart procedure reads; fixture mode never uses their network adapter. Review [source/egress limits](official-web-evidence.md) before a separately authorized enablement | config |

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
- **Graceful stop:** Uvicorn first allows15 s for connections, then cancels unfinished
  response tasks. Application shutdown subsequently cancels admission, drains retained
  response/run cleanup for up to10 s and closes SQLite afterwards. Interrupted runs persist
  cancelled and retain unknown-cost reservations; exceptional drain failure falls back to
  conservative abandoned-run recovery. Allow at least 40s container stop grace for the current observability-capable image and verify
  it under real VPS load. Do not promise completion within15 s or delivery of a terminal
  SSE frame over a torn-down connection. The pre-fix image could leave runs active until
  restart; the real-socket SIGTERM regression checks persisted state before restarting.
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
Set the current container stop timeout to at least 40 seconds: Docker's default 10 seconds is shorter
than the tested active-stream shutdown. vps-ops must retain this policy in Coolify or Compose
(`stop_grace_period: 40s`), then verify it under VPS load.
Docker's `local` log driver rotates at 10 MiB × 3 files (compression may use less); stdout is
already content-free structured JSON, and uvicorn access logging is disabled.

```bash
# Operator supplies an approved digest, private network and configuration separately.
# In isolated synthetic acceptance: AI_PROVIDER=fixture and ALLOW_PAID_AI=false.
# Production can keep ASSISTANT_ENABLED=false; no paid-provider opt-in is implied.
docker run --name pv-api-isolated --read-only --stop-timeout 40 \
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

### Monitoring and application-owned telemetry

Use the private ops summary and internal health probes. ADR-0005 describes the earlier
monitoring baseline; ADR-0007 adds optional authenticated private metrics and content-free OTLP
export. Shared collectors, Prometheus and Grafana are selected and deployed by vps-ops, not
this repository. The application does not expose a public metrics endpoint.
An authorized operator can inspect Docker health,
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

### Historical image security maintenance — 2026-10-10 (superseded base)

Both Python stages are pinned to the same official Python 3.13.16 amd64 image digest
`sha256:8fb4cfa1a2616d7b8e0c2175cc6ad68f5729c34ea8488c0b360d2934b7be9024`.
The inspected base includes Debian libpcre2 10.46-1~deb13u3 and OpenSSL/libssl/provider
3.5.7-1~deb13u3, fixing the previously scanned patchable HIGH findings
CVE-2026-103111 and CVE-2026-84782. See the
[Debian PCRE2 advisory](https://security-tracker.debian.org/tracker/CVE-2026-103111),
[Debian OpenSSL advisory](https://security-tracker.debian.org/tracker/CVE-2026-84782), and
[Python 3.13.16 release notes](https://www.python.org/downloads/release/python-31316/).

The runtime removes global pip, its vendored packages and the ensurepip bundled installer wheel; the isolated, frozen `/opt/venv`
contains application dependencies and does not need an installer. This removes the unused
vendored msgpack/setuptools/urllib3 findings rather than changing application lockfiles.
The builder retains its tools. Scan each exact candidate image and retain the report/SBOM;
these targeted changes do not imply that all OS advisories are fixed or that deployment is
authorized. Unfixed advisories require explicit review before activation.

The pinned base still carries liblzma5 5.8.1-1+deb13u1. A single explicit runtime package
upgrade pins `liblzma5=5.8.1-1+deb13u2` from signed Debian security repositories and removes apt
lists in the same layer. This fixes [DSA-6549-1](https://security-tracker.debian.org/tracker/DSA-6549-1),
whose [upstream advisory](https://github.com/tukaani-project/xz/security/advisories/GHSA-5qpq-xqfv-j9pg)
is HIGH even though the Debian scanner record is UNKNOWN. No general distro upgrade or
application dependency update is performed. Repository metadata is live, not a frozen snapshot;
the exact version fails the build if unavailable. Retain the approved built image by digest and
revisit its pinned base/package when rebuilding, rather than silently choosing another version.
Removing an installer from inherited base layers uses whiteouts: it reduces exposed runtime
files, not the physical bytes of shared image layers. Preserve shared layers and a rollback
image; do not pursue size reduction by stripping required libraries.


## Optional application telemetry and current Python candidate

[Application observability](observability/README.md) owns the optional private JSON/Prometheus
endpoints, manual traces and provisioning transfer artifacts. Infrastructure owns the collector,
Grafana, Prometheus, private scrape credentials and deployment. Observability is off by default;
never route `/internal/*` publicly. A telemetry-off API remains fully functional. Provider
availability is unknown unless separately verified: no paid probes or manufactured uptime.

The new candidate uses stable Python 3.14.8, from official linux/amd64
`python:3.14.8-slim-trixie@sha256:cfe2e24a75302a15934d37c2d86412893c0aa934dc3a97cbb439d04c01890ca9`
verified2026-10-12, with uv0.13.0 pinned in builder and CI. Host setup pins3.14.8;
strict mypy targets3.14. Ruff retains the existing3.13-compatible syntax policy, which runs
unchanged on3.14 and avoids unrelated automatic syntax rewrites. It is not a second runtime.
Exact-candidate image and full checks must pass before acceptance; earlier Python3.13/container
measurements above remain historical and are not measurements of this candidate.

Python3.15.0 was [released stable on2026-10-09](https://www.python.org/downloads/release/python-3150/),
but official Docker tags3.15.0,3.15.0-slim and3.15.0-slim-trixie returned no manifest on2026-10-12.
These are date-scoped local registry observations, not a universal Python3.15 limitation.
Pequeverso has no Lingua dependency; the portfolio Lingua-wheel blocker is not applicable.
Local uv0.12.10 likewise had no3.15.0 managed download. The owner explicitly allowed stable3.14
instead. No RC, ad hoc source build or untested3.15 image is substituted. Reconsider3.15 only
once a stable official digest and compatible wheels are available, then independently run
all checks, socket/model revalidation and exact-image hardening/restore/shutdown tests.
Python uses its release support lifecycle; no separate "LTS" distribution is claimed.


With optional tracing enabled, budget the15-second Uvicorn drain, up to10-second response
cleanup and bounded exporter shutdown separately. Set a40-second container stop grace for
this candidate; the30-second minimum above belongs to the historical tracing-off image.
Validate the actual active-stream and unreachable-collector stop duration for the release
image and under VPS load. Queued traces may be dropped during shutdown; application run
persistence remains a separate requirement.


## Earlier application candidate on 2026-10-12 (superseded route classification)

Source `05ecae7a6b41cbf4445f0514c0e1d05eb11eb344`; exact local image
`sha256:ba395b5cbbb0dead33ea0573b61f2754c3c94c3488795192d1792509c6a45ed6`
(56,671,567bytes, UID 65532, Python 3.14.8). Tested read-only root,256MiB/no additional swap,
0.5CPU,64PIDs,64MiB tmpfs, dropped capabilities and no-new-privileges. Core fixture HTTP/SSE,
auth/CORS/private ops, online backup and restored history/charged ledger passed. Four concurrent
fixture turns took850–988ms; idle memory64.97MiB, peak cgroup82,100,224bytes; idle stop2.436s.
These shared-WSL numbers do not establish VPS capacity or live-model container load.

Optional actual local OTLP capture validated safe attributes and authenticated private W3C
parenting. With the collector blocked and a fixture stream active, SIGTERM stopped17.244s,
exit 0/no OOM. Read-only inspection before restart found completed1/canceled1 and
settled1/unreported1, retaining uncertain spend; SQLite quick_check passed. After restart history
had three messages/one assistant and no partial answer. The outgoing SSE ended EOF without a
terminal event during process drain; client recovery must tolerate that. Keep current40s grace.

Diagnostic optional-container startup measured10.129/14.962/11.541s against a60s observation
window. Two older candidate probes missed20s; those negative observations were preserved, not
reclassified as successful. No healthcheck or test timeout was weakened. The default shipped
smoke gate remains the application-owned one in scripts/smoke_container.sh.

Trivy 0.75.0/checksum-verified, isolated vulnerability database updated 2026-10-12T19:08:28Z:
164OS package rows/71CVEs,44high rows,0critical/0Python findings,0 published fixed versions;
CycloneDX126 components. This is residual OS risk, not an acceptance decision or a certificate
of security. The source uses signed Debian security packages and removes unnecessary pip/
ensurepip artifacts, but cannot promise a vulnerability-free image. Preserve the scan and
review it again when vps-ops selects/builds/publishes its actual deployment digest.

No image was published and no VPS/proxy/collector stack deployed. Real-model development
results and their separate cost/semantic limits are in
[the evaluation record](verification/real-model-2026-10-12.md). They do not authorize activation.


## Historical route-classification candidate on 2026-10-12

Source `f2958b6efb2dc6bc099647a86aaa44dac1816fef`; exact local image
`sha256:48435fc564ff353b9590e9ebed033425d23615815f29a9d69112b88e0b76bf57`,
56,671,696 bytes, UID 65532, Python 3.14.8. This candidate corrects the telemetry allowlist for
FastAPI's lazily included routes; it changes neither commercial behavior nor the public contract.
The earlier 05ecae7/ba395 results remain historical, with known-route classification coverage
explicitly superseded. No digest is relabeled as a later release build.

Shipped core smoke passed in 58.971 s: non-root, read-only, session/CSRF/HTTP/SSE/private auth,
online backup/restore, conversation continuity and spend-ledger recovery. An isolated collector
verified 11 actual spans across 9 names, including health, private operations, sessions, messages,
the templated cancel route and a bounded unknown label. Authenticated private requests inherited
the expected parent; public or unauthorized requests did not. No visitor path, query, raw run id,
credential or conversation content appeared in the exported labels/attributes.

An active fixture SSE stream with a blocked collector stopped in 19.077 s with exit 0, no OOM. Before
restart, readonly SQLite inspection found one completed run, one cancelled run, one settled
ledger entry and one unreported reservation; quick_check was `ok`. Restart restored 3 messages,
including one complete assistant answer. Transport ended with EOF without a terminal frame:
clients must recover stored state and cannot rely on a terminal frame during process drain.
Keep at least 40 s container stop grace and test it under actual VPS load.

Local idle memory was 66.17 MiB; cgroup peak 82,812,928 bytes. Four concurrent fixture turns
took 773–820 ms and idle stop took 4.938 s. Diagnostic cold starts measured 19.004, 13.529 and 15.092 s
under a 60 s observation limit; older 20 s failures remain preserved. These shared-WSL results
are not an isolated speed comparison, live-provider capacity or a production SLA.

Trivy 0.75.0 with its own vulnerability database updated 2026-10-12T19:08:28Z retained the same
164 OS package rows / 71 unique CVEs: 44 HIGH, 58 MEDIUM, 61 LOW, 1 UNKNOWN, 0 critical/Python
findings and no published fixed versions in that database. The CycloneDX SBOM contains 126
components. Scanner results remain visible and do not constitute production risk acceptance.
Before deployment, rebuild and smoke the exact approved release commit, review its current
security inventory and complete the vps-ops activation gates.

## Historical commercial-guard candidate on 2026-10-13

Source `6afb5f380303847b26cabfcf424e07ddc344e177`, exact local image
`sha256:76b5bcd440d43628276bb12efd1358a9ede4c7a2276cf38c394c8d402839141b`,
56,831,248 bytes, Python 3.14.8, UID 65532:65532. The image was not published or deployed.
[PR49](https://github.com/gonzalomartinperez/pequeverso-assistant-api/pull/49) introduced
checked cumulative streaming prefixes and terminal-tail cancellation/deadline/known-usage
regressions. [PR50](https://github.com/gonzalomartinperez/pequeverso-assistant-api/pull/50)
applies the same catalog guarantee recognizer with optional web evidence enabled, disabled
or unavailable, including positive reminder probes. Neither changes public v1 revision1.4.

The shipped container smoke passed non-root/read-only, live/readiness, session/Origin/CSRF,
HTTP/SSE, private operations authorization, online backup/restore with two retained messages
and charged ledger, four concurrent fixture streams and graceful stop. No OOM occurred.
Cgroup peak was 83,767,296 bytes under 256 MiB; core stop took 1.954 s. These fixture measurements
do not establish real-provider load, proxy behavior, VPS capacity or a production SLA.

The separate active-SSE/blocked-collector probe belongs to source
`68c97bb2fe2937f43c26e4c830310c4919fb73cb`, image
`sha256:5a8526adaf0cf2cbda6213a098a2dc5576bc2cb0dea280ddf72e1419644ce8e4`.
With a stalled local collector, bounded export failures did not prevent live/readiness HTTP 200.
Cancel returned 202 and persisted no partial assistant; a second active stream stopped with
exit 0, no OOM, in 7.508 s. During shutdown readiness was observed as 200 then unreachable,
not 503. PR50 changes merchant-policy checks, not that lifecycle code; this earlier probe is
not relabeled as a test of the later digest. Keep at least 40 s stop grace and test the exact
selected release image through the actual VPS proxy before activation.

An offline Trivy 0.75.0 scan on 2026-10-13 used vulnerability DB updated 2026-10-12T19:08:28Z:
164 OS package rows, 71 unique CVEs (44 HIGH, 58 MEDIUM, 61 LOW, 1 UNKNOWN), no critical or
Python findings, and 126 CycloneDX components. No finding had a published fixed version in
that database. This inventory is not risk acceptance or a vulnerability-free guarantee;
vps-ops must review current findings and the separately selected PostgreSQL image before
deployment. Application scans do not certify the host, shared services or production security.


## Verified final-corrections candidate on 2026-10-13

[PR51](https://github.com/gonzalomartinperez/pequeverso-assistant-api/pull/51) integrates explicit
page-count validation, exact request packing, effective-source citation filtering, local recognition
of confirmed French reply commands and processing-window safeguards. Public schemas and v1
revision1.4 remain unchanged. The [post-tool evidence](verification/post-tools-2026-10-13.md)
preserves the original halted evaluation separately from fixes and subsequent phases.

Source `3f230f46524011fe34a3fe14715bb342d75c2d32`; exact local image
`sha256:e783762c446e3bafc0dd5bff0608725786a3da6587413bb730b3ea5642814a8b`,
56,834,339 bytes, Python 3.14.8, UID 65532:65532. Core smoke passed non-root/read-only,
health/readiness, session/Origin/CSRF, HTTP/SSE, private operations authorization, online
backup/restore with two retained messages and charged ledger, four concurrent fixture streams
and graceful stop. Peak 84,242,432 bytes under 256 MiB; stop 1.619 s; idle 66.55 MiB; no OOM.
These shared-WSL fixtures do not establish actual provider load, VPS headroom or proxy behavior.
The earlier active-stream/blocked-collector measurement remains tied to 68c97bb/5a8526a;
keep at least 40 s grace and verify the exact selected deployment image under the real proxy.

An exact-image offline Trivy 0.75.0 scan retained 164 OS package rows / 71 unique CVEs, 44 HIGH,
0 critical/Python findings and 126 SBOM components, using the DB updated 2026-10-12T19:08:28Z.
No published fixed versions were reported in that database. Findings remain visible, without
production risk acceptance; separately selected PostgreSQL/monitoring/host services need their
own security review. The image is local only, not published or deployed.

One initial build used an incorrectly transcribed SERVICE_REVISION and was discarded as
acceptance evidence before any smoke. The selected image above was rebuilt with the verified
full Git SHA; its inspected SERVICE_REVISION matches that SHA exactly. No earlier digest is
relabeled as this build. vps-ops must rebuild and smoke its exact approved release commit.
## Shared runtime baseline

See [runtime-baseline.md](runtime-baseline.md) for the 2026-10-13 shared cohort and image
acceptance. Actual committed locks and Dockerfiles supersede historical version/size samples;
no production publication, deployment or live OAuth/provider check is implied.

## Affiliate catalog rollout and rollback (2026-10-17)

HTTP revision1.5 is additive; the internal catalog is not forward compatible with older strict
readers. Deploy the new reader before activating the two-product catalog. The new reader can
load the previous single-product snapshot. Before deployment retain the previous image, exact
catalog JSON/hash and a coherent SQLite backup (including conversations and accounting); do
not delete or blindly restore a shared volume. An old reader rejects the new affiliate fields.
SQLite startup loads the active snapshot; it does not automatically search all five historical
snapshots for one compatible with an old reader. Its packaged old snapshot can recover only
when refresh succeeds; otherwise readiness remains unavailable. Plan an explicit catalog
rollback preserving newer conversations/accounting, rather than assuming an image rollback
alone restores compatibility. vps-ops owns execution and production verification.

The persisted message JSON is also not forward compatible: revision1.5 stores optional
kind/format/disclosure on product references, including core cards. Historical1.4 readers
construct ProductRef directly and reject unknown keys. A1.5 reader accepts historical1.4
messages with defaults; the reverse requires an explicit, validated data migration or a
compatible reader. Do not promise image-only rollback, erase conversations/ledger, or restore
an old full database over newer accounting. Validate rollback on an isolated copy and obtain
a deliberate data-preservation plan before production activation.
