# Public GraphRAG and private-state operator jobs

This is an application contract for vps-ops. Nothing here provisions Coolify, proxy, DNS,
shared monitoring or production. The storefront assistant remains disabled. The new profile
requires its own integrated CI and exact-image gates before any deployment recommendation.

## Ownership and trust boundaries

- PostgreSQL 18.6 with pgvector 0.8.7 is the production relational authority: public catalog
  projections live in `knowledge`; sessions, messages, runs, accounting and content-free
  operational metrics live in `assistant_private`. Backoffice identity stays in its separate
  database and is not copied into either schema.
- Neo4j Community 5.26 LTS contains only a rebuildable public projection. It never stores visitor
  messages, session identifiers, customer identity, orders or evaluation questions.
- Real semantic embeddings use OpenAI `text-embedding-3-small`, 1536 dimensions. Local fixture
  `hash64-v1` vectors have 64 dimensions and demonstrate mechanics, not semantic quality.
  Their version identities cannot be activated or queried as OpenAI embeddings.
- The public assistant is advisory. Retrieval does not authorize purchases, refunds, account
  changes, external browsing or execution of instructions found in catalog text.
- LangGraph runs a finite retrieve → answer graph without retries, checkpoints, store or cache.
  LangChain Documents carry validated public passages; LangSmith runtime tracing is disabled,
  including when inherited environment variables request tracing.

## Credentials by capability

Secrets belong in private operator configuration, never CLI arguments, Git, screenshots,
URLs or client-side configuration. Jobs do not load `.env` files implicitly.

| Process | Environment name | Capability |
| --- | --- | --- |
| Explicit SQL migration | `POSTGRES_MIGRATION_DSN` | Own project schemas and create the NOLOGIN capability groups; not an application credential |
| Explicit historical import | `POSTGRES_IMPORT_DSN` | Privileged, bounded import into an empty private target; no public indexing |
| Explicit public indexing | `POSTGRES_INDEXER_DSN` | Membership of `pequeverso_knowledge_indexer` |
| Index accounting | `POSTGRES_EMBEDDING_DSN` | Membership of `pequeverso_embedding_accounting`; shared totals readable, writes restricted to index reservations |
| HTTP private state | `POSTGRES_PRIVATE_DSN` | Membership of `pequeverso_private_runtime`; no knowledge-table access |
| HTTP public retrieval/sync | `POSTGRES_KNOWLEDGE_DSN` | Membership of `pequeverso_knowledge_runtime`; no private-table access |
| Graph connectivity | `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` | Private authenticated Bolt connectivity; credentials do not belong inside the URI |

vps-ops provisions distinct LOGIN identities, membership and secrets after the explicit schema
job. Runtime identities must not own tables, be superusers or inherit the index-accounting
identity. PostgreSQL row-level policy protects index-ledger writes in addition to grants.
Neo4j Community does not provide the same fine-grained role separation: do not describe a
read transaction hint as database-enforced read-only authorization. Keep Bolt private and
use the fixed application queries and bounded adapter interfaces.

## One project engine, two database bootstrap

The API-owned PostgreSQL/pgvector artifact is the common Pequeverso engine. vps-ops owns its
single lifecycle, network/HBA policy, secrets and capacity. Keep `pv_assistant` and `pv_iam`
as distinct databases (example names), with independent owners and backups; never reuse the
Portfolio engine. The backoffice owns its IAM migrations and runtime table grants.

Bootstrap is an explicit operator job, never HTTP startup:

1. Provision two databases with separate ownership and distinct non-administrative LOGINs.
   Provision credentials privately; no password literal belongs in an SQL recipe or CLI argument.
2. Use `REVOKE ALL ON DATABASE <database> FROM PUBLIC` on both application databases and unused
   `postgres`/`template1` databases of this dedicated project engine. This removes default
   CONNECT, TEMPORARY and CREATE privileges. Grant CONNECT only to each database's own job
   and runtime identities. Keep operator access explicit. Revoke PUBLIC CREATE on `public`.
3. Run API migrations with the separate migration credential: it must create the vector
   extension, schemas and NOLOGIN capability groups. This is privileged setup authority, never
   a runtime role. Run BO migrations with its distinct IAM owner, not an API credential.
4. Grant each API LOGIN exactly one capability from the table above, with no ADMIN OPTION.
   Never grant runtime membership of an owner or another capability. BO runtime must not own
   relations, create tables, read migration history or update/delete access-audit rows.
5. Verify denied cross-database connections with actual LOGINs, not just ACL inspection; verify
   allowed reads and denied TEMP, DDL and private/public cross-schema reads. Recheck grants
   after migration. Runtime identities must not inherit owner or administrative privileges.
6. Restore each database independently into an isolated target and compare complete row hashes.
   Database dumps do not contain cluster roles, credentials or HBA rules: provision those
   separately from the private operator secret inventory before restoration.

Local same-engine evidence on PostgreSQL18.6/pgvector0.8.7 passed API31 and BO18 database tests,
BO51 browser tests (three optional skips), six denied cross-database LOGINs, eight denied SQL
operations and five permitted least-privilege reads. A separate reviewer checked six real
LOGINs and denied cross/system CONNECT plus absence of administrative flags. Both database
restores matched full row hashes, and only the two application databases remained afterward.
The full database/browser suites used fixture administrative connections; the separate role
probes establish the reported capability checks. This does not establish a full browser run
under production runtime credentials, deployment capacity, production HBA rules or VPS restore.
See [dated evidence](verification/graphrag-2026-10-17.md) and the backoffice deployment contract.

## Commands from a clean checkout

Use the repository-pinned uv and Python 3.14.8. Python 3.15 is not selected because the frozen
GraphRAG dependencies do not all publish compatible wheels; no source-build workaround is
part of the reproducible image.

```sh
uv sync --frozen --no-build
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -q
uv run python -m contracts.export --check
```

Run jobs as modules from the project root. The `app.bootstrap` modules are also included in the
application image; use the same immutable image ID/digest selected for its HTTP process.
Do not pass secrets after `docker run -e NAME=` on a shared command line: use a private env file
or the operator's secret mechanism. Mount only the input and private receipt directories
needed by the job. Normal HTTP startup never performs migration or paid indexing.

```sh
uv run python -m app.bootstrap.knowledge_jobs migrate
uv run python -m app.bootstrap.knowledge_jobs index \
  --catalog catalog/catalog.v1.json \
  --expected-catalog-sha256 <reviewed-sha256> \
  --receipt /private-receipts/index-result.json
```

The indexing command defaults to `AI_PROVIDER=fixture`. OpenAI indexing additionally requires
`AI_PROVIDER=openai`, `ALLOW_PAID_AI=true`, a private `OPENAI_API_KEY` and explicit
`--allow-paid-indexing`. These are technical gates, not spending authorization. Verify the
owner's current authorization, official embedding prices, shared project budget and any
separate evaluation ledger before executing paid work. The standalone CLI enforces the application ledger, not the independent evaluation
envelope. It must not be used as an evaluation-budget bypass: the evaluation composition
must additionally reserve every SDK request against its aggregate guard before any paid batch. Do not reset an old ledger or automatically retry a failed job.

The operator job requires a matching SHA-256 before opening services. It creates its receipt
with exclusive creation and mode 0600 before network I/O; an existing receipt is never
replaced. A started but unfinished receipt means inspect both staged projections and the
private ledger before deciding whether an explicit retry is safe. It does not imply zero cost.
The final receipt contains public revision/count metadata, not prompts, messages or secrets.

## Index and activation sequence

1. Follow `.agents/skills/update-catalog/SKILL.md`: export from a pinned storefront commit
   reachable from `origin/main`, review facts and commit the authorized snapshot. Do not hand
   edit commercial data or ingest evaluation questions as knowledge.
2. Validate the catalog and construct a deterministic revision from its exact body hash,
   parser version and embedding provider/model/dimensions.
3. Acquire the dedicated public-index lock, then recover only abandoned index reservations.
   Generation and query accounting remain separate in the shared private ledger.
4. Reuse existing vectors only after canonical metadata, text and vector hashes validate.
   Otherwise encode once in batches bounded by 32 texts and 240,000 UTF-8 bytes. The SDK
   has no automatic retries. Reserve before dispatch and retain uncertain spend.
5. Stage PostgreSQL and Neo4j, compare their exact version/hash/count proof, validate the
   canonical stored manifest and mark prepared. Change the single PostgreSQL active pointer
   only after both projections agree. A failure keeps the previous active revision.
6. Run the actual HTTP profile with `APPLICATION_STORAGE=postgres` and
   `KNOWLEDGE_BACKEND=graphrag`. It has separate runtime DSNs and verifies the fetched catalog
   binds to the matching prepared revision. A failed source refresh marks synchronization
   unhealthy; a known unavailable projection refuses generation before any query embedding.

Dynamic commercial facts still come from the validated, sufficiently fresh catalog. An old
embedding or graph relationship cannot confirm a current price or availability. Retrieved
passages remain untrusted evidence, never instructions. Comparisons require evidence for
both explicitly identified products; retrieval annotations are not supplied as expected answers.

## Private-state migration and singleton lifecycle

SQLite remains an explicit fixture/historical source, not a second permanent production
relational authority. Import only a closed, quiescent snapshot without WAL/SHM/journal sidecars:

```sh
uv run python -m app.bootstrap.import_database \
  --snapshot /private-input/assistant.sqlite3 \
  --receipt /private-receipts/import-result.json \
  --source-quiescent
```

The import checks schema, counts and source hash, runs one PostgreSQL transaction, refuses
partial targets and records a content-free idempotence receipt. It never deletes the source
and never indexes imported conversations or the archived old catalog. Provision the target
schemas separately; verify private restore before retiring the historical source.

The HTTP process holds a dedicated PostgreSQL session advisory lock before recovering
abandoned runs or reservations. Import shares this exclusion key. A second process fails
startup instead of recovering another owner's active work. Loss of the ownership connection
makes readiness and new admission fail; there is no silent reacquisition or HA failover.
Use **one worker, one instance, stop-first with no overlap**. Existing streams require the
normal bounded drain/stop sequence; do not claim an instant cross-instance stream abort.

The image declares no anonymous data volume. Explicitly mount `/data` only for a SQLite
fixture/import workflow. Production persistence belongs to PostgreSQL and Neo4j's own
operator-managed volumes. Do not remove shared volumes as part of application cleanup.

## Verification and remaining deployment gates

Adapter tests, fixture vectors, database restore and local HTTP tests establish different
properties. Preserve original failures and exact source/image identities; do not combine them
into an unqualified production-ready claim. The required integrated gates include real
PostgreSQL/Neo4j roles, HTTP/SSE/CSRF/session isolation/history/cancellation, idempotent indexing,
restore before reindex, exact-image non-root/read-only health and shutdown with active streams.
Record memory and query plans under actual container limits without calling a shared-runner
measurement a VPS capacity benchmark.

PostgreSQL and Neo4j image security findings remain visible. In particular the recorded
`CVE-2026-6653` finding is an open deployment gate, and the Neo4j candidate is not security
approved merely because local functional tests pass. No global suppression, jar replacement,
APOC/GDS addition or unmeasured ANN index is part of this profile.

vps-ops owns HTTPS, routing, proxy/SSE behavior, secret provisioning, shared OTel/Prometheus/
Grafana infrastructure, backups and deployment. Main merging alone neither deploys these
services nor authorizes activating the storefront assistant.
