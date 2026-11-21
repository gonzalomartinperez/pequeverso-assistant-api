# Changelog

All notable changes are recorded here in the [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
format; versions follow [Semantic Versioning](https://semver.org/). Add entries under
`[Unreleased]` in the PR that makes the change. A release PR on `develop` bumps `version` in
`pyproject.toml` and moves the entries under `## [X.Y.Z] - YYYY-MM-DD`; after the promotion to `main`,
`.github/workflows/release.yml` tags `vX.Y.Z` and publishes that section (ADR-0018). The 1.0.0
entry below predates this format and is kept as written.

## [Unreleased]

### Added

- ADR-0013 (v1 error envelope and RFC 9457 mapping) and ADR-0014 (allowlist JSON log formatter);
  Confirmation sections in ADR-0001 to ADR-0009.
- Quality net (master plan M2): coverage and diff-coverage gates, golden set v1 with cassette
  replay, red-team pack, Hypothesis properties, mutation lane, SSE load harness, security matrix
  and fault-injection tests, scorecard and nightly workflow.
- `LOG_STREAM` setting; evaluation and operator CLIs (including the import and knowledge jobs)
  now log to stderr so their stdout stays machine output. The `run` event carries `prompt_version`.
- Internal health aliases `/healthz` and `/readyz` with `version` and `schema_version`, and the
  generated environment schema `contracts/env.schema.json` (ADR-0019). The image `HEALTHCHECK` now
  calls `/healthz`; `/health/live` and `/health/ready` are unchanged.

- Contract revision 1.6: `contracts/openapi.json` documents the product-analytics ingest
  operation, and the new `contracts/openapi.internal.json` covers health and private operations;
  the oasdiff gate checks both. No wire change apart from the advertised revision.

### Changed

- `httpx`, `httpcore` and `openai` loggers run at WARNING, and third-party records below WARNING
  are counted into one content-free `external_events` line instead of being printed. The
  official help reader and the span exporter take the injected `Clock` (no `datetime.now`
  outside bootstrap).
- One `ci.yml` with change classification and the `ci-gate` aggregate; weekly grouped dependency
  updates (master plan M1).

### Security

- certifi 2026.10.23 (GHSA-6q48-6c7w-9gw2); container image gates, SBOM and reproducibility check.

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
- Local public-catalog scope answers distinguish other visitors' private conversations from
  public product information, without making claims about own-history retention or provider
  processing. Mixed requests preserve the existing conversation and safety paths.
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
[the deployment contract](docs/reference/deployment-contract.md),
[knowledge operations](docs/how-to/knowledge-operations.md) and
[the vps-ops handoff](docs/reference/handoffs/vps-ops.md).

The version-number update itself changes no application behavior, catalog facts, dependency
versions, wire contracts, image recipes or activation settings. The separately reviewed
provenance and prompt changes above require their own behavioral verification; source metadata
and deterministic fixtures do not establish real-model quality.
