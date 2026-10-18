# Changelog

## 1.0.0 — Source release, 2026-10-17

This version identifies the software source baseline. It does not indicate a deployed API,
a production-accepted infrastructure configuration, or an activated storefront assistant.
The public HTTP/SSE contract remains v1 revision 1.5; source and wire-contract versions are
independent.

### Included capabilities

- Advisory shopping conversations with sessions, CSRF protection, streamed responses,
  cancellation, idempotent recovery, persisted history and visitor isolation. Commercial
  references resolve to the authorized public catalog; the assistant cannot execute orders,
  payments, refunds or account changes.
- Canonical public catalog snapshots, chunks and embeddings in PostgreSQL/pgvector, with a
  versioned Neo4j relationship projection and hybrid retrieval. LangGraph orchestration
  remains behind application ports. Projection integrity and freshness are checked before
  generation; catalog-only packing is explicit rather than falsely reported as retrieved
  passages sent to the provider.
- Separate PostgreSQL public and private capabilities for catalog retrieval, indexing,
  conversations, operational aggregates and budget accounting. Stop-first runtime ownership,
  explicit migrations, a read-only SQLite import procedure and legacy fixture support.
- Backend-only provider credentials, bounded OpenAI generation and embedding requests,
  shared accounting before dispatch, conservative treatment of unknown costs and no automatic
  generation retries. The native storefront assistant remains disabled pending authorized
  backend deployment and verification.
- Bounded public-information provenance answers, with an immediate clarification when the
  product is ambiguous. The local policy preserves authorization, rate limits, redaction and
  persisted history without dispatching a generation. Affiliate prompt guidance requests the
  canonical disclosure once; server-side disclosure and commercial validation remain enforced.
- Reproducible hardened application and database image recipes, health/readiness checks,
  graceful streaming shutdown, persistence and restore procedures. Deployment, shared server
  infrastructure and production acceptance remain the responsibility of vps-ops.
- Fixture-first evaluation through actual HTTP/SSE and isolated stores, including SDK mock
  transport checks and an immutable shared evaluation envelope. Resumed unknown spend,
  concurrent evaluator ownership and index failures fail closed without resetting accounting.
- MIT licensing for the software, with the exclusions and third-party scope in
  [NOTICE.md](NOTICE.md).

### Acceptance boundaries

A source release does not establish real-model answer correctness, sales conversion,
more than 200 new live GraphRAG queries, VPS capacity, effective production restore or security
acceptance. Preserve the original and post-correction evaluation receipts; fixture scores
are not real-model quality evidence. Open deployment gates and operator steps remain in
[the deployment contract](docs/deployment-contract.md),
[knowledge operations](docs/knowledge-operations.md) and
[the vps-ops handoff](docs/handoffs/vps-ops.md).

The version-number update itself changes no application behavior, catalog facts, dependency
versions, wire contracts, image recipes or activation settings. The separately reviewed
provenance and prompt changes above require their own behavioral verification; source metadata
and deterministic fixtures do not establish real-model quality.
