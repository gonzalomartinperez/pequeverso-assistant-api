# Handoff to vps-ops: Pequeverso applications

Current application profile: **2026-10-19, GraphRAG candidate**. This replaces the earlier
SQLite production handoff. Dated image measurements and legacy SQLite recovery procedures
remain in [the deployment contract](../deployment-contract.md) and Git history; they are
not current production topology or approval. No images are published and no API/backoffice
service is deployed by this work. vps-ops owns Coolify, proxy, DNS, secrets, infrastructure
allocation, monitored backups and deployment. The storefront assistant remains disabled. The [October19 native image handoff](../verification/final-native-images-2026-10-19.md)
identifies exact local images, retained findings and outstanding acceptance work.

## Current topology and project isolation

| Component | Responsibility and placement |
| --- | --- |
| Storefront `pequeverso` | Hostinger builds `main`, owner-confirmed. Home links to the Grafismo Fonético landing or the existing affiliate redirect to the producer; Hotmart handles purchase. No VPS frontend, iframe or `/embed` service |
| `pequeverso-assistant-api` | Future private-network application container; only `/api/v1/*` exposed through its future public host |
| API PostgreSQL 18.6 + pgvector 0.8.7 | Production relational authority: public `knowledge` and private `assistant_private` schemas with distinct capability identities |
| API Neo4j Community 5.26 LTS | Versioned rebuildable **public-only** projection, private Bolt/HTTP, no customer or conversation data |
| `pequeverso-backoffice` | Separate authenticated host; OAuth, owner/viewer permissions and server-side consumption of private operations data |
| Backoffice identity database on the same project PostgreSQL 18.6 service | Separate database, credentials and migration/backup custody; never part of public retrieval |

The coordinated target is **one PostgreSQL service instance for the Pequeverso project**,
with **two distinct databases**: assistant public/private state in one, backoffice identity in
the other. Each has separate ownership, runtime credentials, CONNECT/schema/table privileges,
migration authority, backups and restore custody. These are logical database boundaries, not
physically isolated servers. The API-owned PostgreSQL/pgvector artifact is the common project
engine; the backoffice still owns its IAM migrations. vps-ops owns the single service lifecycle,
resource allocation and deployment. No application starts a competing database controller.

Cross-database admission and table access must be explicitly denied to the other runtime
identity; revoke PUBLIC database privileges, including CONNECT, TEMPORARY and CREATE, and
grant each runtime only its own CONNECT and documented schema/table capabilities. A local same-engine drill covers API31,
BO18 and BO51 browser tests, independent database restores with matching row hashes, and
separate least-privilege role probes. The full suites used fixture administrative connections;
this is not a production-runtime-role browser test or VPS-capacity approval. Follow the
[bootstrap custody and acceptance steps](../knowledge-operations.md#one-project-engine-two-database-bootstrap). This
choice is not provisioning approval. **Never share a PostgreSQL or Neo4j
instance with Portfolio or another project.**
SQLite remains an isolated fixture profile and a quiescent, non-destructive historical import
source. The production API has no anonymous `/data` volume and never auto-migrates PostgreSQL
at HTTP startup. Redis and LangGraph checkpoint storage are not part of this finite workflow.

## Artifact, process and storage contract

All three recipes use the repository root as their build context. The app uses root
`.dockerignore`; PostgreSQL has its own adjacent deny-by-default filter allowing only LICENSE
and NOTICE.md; Neo4j allows only those notices and its colocated `neo4j.conf`. No local Compose
is implemented here, and production composition remains owned by vps-ops/Coolify.

- Build from the approved exact application commit with `infra/docker/app/Dockerfile` and the frozen
  lockfile; use immutable image digests for rollout. Local IDs in
  [the dated evidence](../verification/graphrag-2026-10-17.md) are not published manifests or
  final release identities. API/backoffice `main` merges do not deploy; storefront `main`
  merges publish through Hostinger, so its disabled-build and post-deploy checks are mandatory.
- API: port **8000/tcp**, UID/GID **65532**, read-only root, cap-drop ALL, no-new-privileges,
  bounded `/tmp` tmpfs, rotated container logs. `APPLICATION_STORAGE=postgres` together with
  `KNOWLEDGE_BACKEND=graphrag`; no production SQLite mount. Runtime code owns no host resources.
- API PostgreSQL: port **5432/tcp**, UID/GID **70:70** (current Alpine image; historical Debian used999:999), persistent mount
  **`/var/lib/postgresql`** (PostgreSQL 18 layout), bounded writable `/var/run/postgresql`
  and `/tmp` tmpfs. Use the project `infra/docker/postgres/Dockerfile` exact image and privacy logging CMD;
  do not replace it with a less restrictive command. No public database port.
- Neo4j: private **7687/tcp** Bolt and **7474/tcp** HTTP, UID/GID **7474**, persistent **`/data`**;
  reviewed bounded runtime/log tmpfs, read-only root, no plugins, native JNA library installed
  read-only at image build. Use `infra/docker/neo4j/Dockerfile` and its configuration. Community READ routing
  is **not database-enforced read-only authorization**: use a project-isolated instance and
  secret, fixed application queries and private network boundaries.
- Backoffice: port **3000/tcp**, UID/GID **65532**, read-only stateless image. Its repository
  owns the exact image, IAM migration command, PostgreSQL volume contract and acceptance proof.
- **One API instance and worker, stop-first, no overlap.** A dedicated PostgreSQL advisory
  ownership connection is acquired before abandoned-run recovery; a second owner fails
  startup. Lease loss blocks readiness/admission without silent re-acquisition. A shared DB
  does not make the process HA. Retain at least **40 seconds container stop grace** for stream,
  run-registry and telemetry cleanup; confirm under actual VPS load before activation.

Local fixture ceilings are API/SQLite 256 MiB/0.5 CPU, API/GraphRAG 512 MiB/1 CPU,
API PostgreSQL 384 MiB/1 CPU and Neo4j 768 MiB/1 CPU. Backoffice fixture acceptance uses 384 MiB/1 CPU. These are separately tested
functional cgroups, **not approved reservations, throughput figures or combined VPS sizing**.
Database/index/restore peaks, simultaneous application load, disk growth and actual capacity
remain vps-ops gates. Do not add these figures and label the result production capacity.

## Migration, indexing, backup and rollback custody

Use [knowledge operations](../knowledge-operations.md) for exact commands and capabilities:

1. Run the explicit `python -m app.bootstrap.knowledge_jobs migrate` job from the selected
   application image with **`POSTGRES_MIGRATION_DSN`**, then provision distinct LOGIN identities
   with the documented NOLOGIN capability memberships. Migration authority is never runtime
   authority. The backoffice runs its own separate IAM migration from its own exact image.
2. If historical SQLite exists, first stop its writer and take a closed, verified snapshot
   without WAL/SHM sidecars. `python -m app.bootstrap.import_database --snapshot ... --receipt
   ... --source-quiescent` uses **`POSTGRES_IMPORT_DSN`**. It refuses a populated target,
   preserves source data and accounting, and is not an automatic destructive migration.
3. Index only the pinned authorized public catalog with `python -m app.bootstrap.knowledge_jobs
   index --catalog ... --expected-catalog-sha256 ... --receipt ...`. Use
   **`POSTGRES_INDEXER_DSN`**, **`POSTGRES_EMBEDDING_DSN`** and private Neo4j credentials. Jobs
   are fixture-only by default; semantic indexing additionally needs owner-approved spending,
   a private key and the explicit paid-indexing flag. The standalone CLI enforces the
   application ledger, not the independent local evaluation envelope. Evaluation indexing
   must additionally pass through the reviewed aggregate evaluation envelope before any
   paid batch; selecting the ordinary CLI does not enforce that separate cap.
4. PostgreSQL staging/vector reuse and Neo4j staging must agree on version, parser, model,
   dimensions, canonical hashes and counts before the single PostgreSQL active pointer moves.
   Failure leaves the old active revision. This is coherent staged activation, not distributed
   PostgreSQL/Neo4j ACID. No evaluation questions or private state enter the projection.
5. Runtime uses distinct **`POSTGRES_PRIVATE_DSN`** and **`POSTGRES_KNOWLEDGE_DSN`**, neither
   owner/indexer credentials. Neo4j credentials stay server-side. Normal startup performs no
   schema migration, semantic indexing, provider retry or rebuild after a restore.
6. Back up the API PostgreSQL private state/ledger and public revision proofs together with
   separately identified backoffice identity backups. Keep encrypted off-server copies,
   recovery credentials and tested hashes/checksums. Neo4j is rebuildable, but its restore or
   rebuild must match the approved PostgreSQL/catalog revision before readiness; never report
   a reindex as successful restoration of the original dump.
7. Stop all writers before an incompatible image rollback; confirm migration/reader and
   catalog/history compatibility. A pre-GraphRAG SQLite image cannot read production PG state.
   Never restore a whole old database over intervening conversations or spend. Snapshot
   recovery begins with the API disabled until post-snapshot spend is reconciled or
   conservatively retained. vps-ops owns the actual backup schedule, restore drill and rollout.

No automatic public-version pruning, volume deletion, private-ledger purge, global Docker
prune or vendor-jar removal is authorized. Monitor database/WAL/index/backup bytes, free disk,
container log bounds and retained known-good image digests. Deleted pages or image whiteouts
are not proof of physical erasure or disk reclamation.

## Health, routes and private operations

| Endpoint | Contract |
| --- | --- |
| API `/health/live` | Internal process liveness |
| API `/health/ready` | Internal private DB + ownership + synchronized catalog + matching public PG/Neo knowledge readiness |
| API `/api/v1/*` | Public session/chat contract **v1 revision 1.5**, no prefix stripping |
| API `/internal/v1/ops/summary` | Private bearer-token, content-free aggregates, schema revision **1.2** |
| API `/internal/v1/ops/telemetry`, `/internal/v1/ops/metrics` | Private, opt-in telemetry schema **1.0** and Prometheus metrics; default off |
| Backoffice `/healthz`, `/readyz` | Internal liveness and migrated IAM database readiness |

The proposed public API host is `assistant.pequeverso.com`; backoffice needs its own sign-in
host. Hostnames are not DNS/deployment instructions. Public routing exposes only `/api/*`;
health, database ports and `/internal/*` must remain inaccessible outside the private network.
Backoffice consumes aggregates **server-side** after its `read_operations` permission check.
Prometheus/Grafana/OTLP complement that custom UI and never replace the accounting ledger or
prove OpenAI availability. vps-ops selects and operates its monitoring components; this repo
provides only opt-in application signals and integration examples.

Preserve SSE on `POST /api/v1/messages`: no buffering or compression; allow at least90s for
streamed response/write, independently of request-body read deadlines. Runs end at60s and
heartbeats occur every15s. Propagate disconnects. Do not force a client HTTP version; TLS,
HTTP/2/3 and upstream proxy timeouts belong to vps-ops. A local loopback test is not a TLS or
public-proxy acceptance test.

Origins are exact, credentials allowed: `ALLOWED_ORIGINS=["https://pequeverso.com"]` (the
owner-confirmed apex; www redirects). Forward OPTIONS without adding proxy CORS headers.
Host-only `__Host-pv_assistant` cookie: Secure, HttpOnly, SameSite=Lax, no Domain. Mutations
require allowlisted Origin and per-session CSRF; sensitive responses are no-store. Configure
trusted proxy peer CIDRs explicitly; application uvicorn proxy headers stay off.

Optional product analytics collection/read and the independent backoffice read flag default
OFF; country receipt also defaults OFF/unknown. Production classification is independent of
assistant enablement. Before any opt-in, follow the [analytics contract and required edge
proof](../product-analytics.md): CF-only origin access, exact trusted peers, overwritten headers
and spoof/bypass rejection must be demonstrated by vps-ops. Configuration and a local fixture
do not establish deployed edge provenance. Migration006 restore remains a separate pending gate.

## Secrets, budgets and activation

All secrets are injected privately by vps-ops/Coolify, never build args, browser code, URLs,
logs or screenshots. [Knowledge operations](../knowledge-operations.md) lists database role
custody. Runtime secret names include **`OPENAI_API_KEY`**, **`CLIENT_HASH_KEY`**,
**`OPS_READ_TOKEN`**, the two runtime DSNs and **`NEO4J_PASSWORD`**; job-only migration/import/
index-accounting credentials must not be supplied to HTTP. Backoffice owns its separate auth,
IAM and OAuth secrets. Share only the ops read token between API and backoffice as needed.

The only generation configuration is GPT-6 Luna / medium; semantic embeddings use
text-embedding-3-small /1536. No model fallback, automatic generation retry or arbitrary web
search. Optional Hotmart procedural retrieval is server-owned, default off and limited to
[three exact public articles](../official-web-evidence.md), without buyer/account credentials.
Python **3.14.8** is intentional: the CP315 frozen graph-dependency install failed on missing
wheels for **PyYAML 6.0.3, uuid-utils 0.17.1 and zstandard 0.25.0**. This is not a Docker/Python
3.15 availability claim and Pequeverso has no Lingua dependency. Locks/digests are authoritative.

The project budget is USD10/month with configured daily cutoff, atomic worst-case reservations
and safety margin. Index/query embeddings and generation share it; unknown spend stays
reserved. These are conservative application estimates, not provider invoices or an assumed
account-level hard cap. Local evaluations use a separately owner-authorized append-only envelope; historical
USD1/650-attempt receipts are dated evidence, not the current evaluation allowance or a
production spending authorization. Keep their original counters and
[source-specific scope](../verification/graphrag-2026-10-17.md).

Storefront activation requires a separate owner-approved rebuild after VPS acceptance:
`NEXT_PUBLIC_ASSISTANT_ENABLED` stays absent/false now, with no launcher, runtime or API traffic.
Verify `npm run check:assistant-disabled` and `build-info.json` assistant=disabled in the
publishable build, then post-deploy checks. API `ASSISTANT_ENABLED=false` is an independent
kill switch, not permission to enable the storefront. HTTPS/CORS/cookies, real proxy SSE and
cancellation, real OAuth/roles, isolated restore, monitored availability, capacity and image
security gates must all be accepted before an activation recommendation. No main merge,
skill, build, LTS badge or this handoff grants deployment or activation authority.
