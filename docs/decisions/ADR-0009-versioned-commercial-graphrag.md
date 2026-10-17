# ADR-0009: Versioned commercial GraphRAG and bounded orchestration

Status: implementation in progress, 2026-10-17. Not deployment or activation authorization.

## Context and reference

The owner explicitly requests the same engineering standard as Portfolio: real PostgreSQL /
pgvector and Neo4j retrieval, useful LangGraph / LangChain components, and LangSmith evaluation.
The commercial objective remains helping an adult choose the appropriate product and reach its
authorized landing. More infrastructure does not establish better answers, scalability or sales.

The read-only reference is Portfolio API commit
`02b6f2784564669597fe8a4c2adf53bf807737a6`, especially `docs/graph-retrieval.md` and its
embedding, indexing and graph adapters. Adapt its invariants, not its career entities or identity.
Its hash64 fixtures are not semantic embeddings; its Neo4j security findings are not accepted
production artifacts. This decision supersedes the no-embedding choice in ADR-0002 only when
the new profile passes its acceptance gates. The current released implementation remains the
historical baseline until then.

## Data and activation

- PostgreSQL owns approved public catalog snapshots, immutable corpus revisions, chunk content
  hashes, embedding identity and the sole active knowledge pointer. Neo4j is a rebuildable public
  projection. SQLite keeps private sessions, messages, runs, spend and existing legacy catalog
  tables; no destructive migration or conversation-to-knowledge indexing is authorized.
- A revision identifies the exact catalog hash, published storefront commit, parser and embedding
  provider/model/dimensions. Index and query identities must match before query embeddings or
  generation. A turn retains its immutable catalog version; prices, references and answer rules
  use that same validated catalog, with the existing freshness policy.
- Public entities are Product, Resource, Document, Link and explicit Topic. Relationships come
  only from typed catalog fields: includes, has-document, has-link and has-topic. Each entity and
  relationship has source evidence and a JSON field pointer. Shared topics imply retrieval
  relevance, never suitability, medical benefit, compatibility, stock or a commercial promise.
- An explicit index job holds a PostgreSQL advisory lock, stages immutable chunks/vectors and
  one Neo4j projection transaction, and compares observed fingerprints/counts. Only after both
  verify may it mark the PG revision prepared and atomically activate the PG pointer. Staging
  alone is not activation. There is no distributed atomic-transaction claim.
- Same-version repeats are idempotent; failures retain the previous active revision. Changing
  corpus/parser/model/dimensions creates a new version. Retention and deletion are explicit
  operations; no automatic destructive pruning is introduced.
- Runtime `CatalogRepository.activate` binds the configured parser/embedding identity and accepts
  only the unique matching prepared revision, never an arbitrary latest revision. It cannot
  silently perform paid indexing. Snapshot mismatch fails closed before a new provider call.

## Retrieval and commercial grounding

Use PostgreSQL lexical search and an exact cosine baseline, then bounded graph expansion for
deterministic relationship cues. No routing LLM, generated SQL/Cypher, APOC, GDS or additional
vector framework is introduced. Fixed parameterized queries use bounded results, traversal
depth, connection pools and timeouts. Verify returned chunks and relationship provenance against
PG, including version, hashes and product scope, before packing evidence.

The small current catalog does not justify HNSW or IVFFlat by default. Compare candidate indexes
against the exact baseline only with measured recall, latency and memory on a declared corpus.
Use `EXPLAIN (ANALYZE, BUFFERS)` and Neo4j `EXPLAIN` / `PROFILE` only on isolated data. CI checks
correctness and query bounds, not fragile latency thresholds or promised VPS throughput.

The existing maximum 24KB provider request and mandatory commercial/policy evidence remain.
Graph matches select evidence; server rules still resolve product/price/link ids and validate
claims. Preserve structured follow-up references without putting visitor history in a public
index. A graph outage may degrade to verified PG evidence only when freshness/identity still
match; readiness must disclose the unavailable graph capability.

## Embeddings, budget and workflow

Semantic mode uses OpenAI `text-embedding-3-small`, 1536 dimensions. Fixture mode uses explicitly
labeled `hash64-v1`, 64 dimensions, only for transport and deterministic tests. Validate cardinality,
dimensions and finite nonzero vectors, and never mix modes. Production OpenAI configuration
requires semantic embeddings and fresh knowledge; a fixture index is not a production substitute.

Reserve embedding cost before each provider request, with purpose `index` or `query`, and settle
reported usage. All operations share the existing integer-microUSD budget and atomic SQLite
check-and-reserve. Missing usage retains its reservation. Existing `spend_ledger.run_id` has no
foreign key to conversation runs; distinct `embedding:<purpose>:<random-id>` identifiers contain
no visitor identity. Startup/index recovery must not refund or lose another worker's reservation;
late known settlement must remain possible. Automatic generation/provider retries remain off.

The LangGraph adapter has typed state and a finite retrieve → pack → answer → terminal workflow,
with explicit error/cancellation handling. LangChain components stay useful and adapter-local.
Domain/application ports remain standard-library values; no SDK, ORM or framework types enter
them. Existing session/CSRF/idempotency, canonical answer validation, SSE terminal events and
private history remain authoritative. No autonomous transactional tools are added.

Keep I/O out of synchronous `prepare`. If generation has been reserved but a retrieval failure
occurs before generation is provably attempted, its known generation usage is zero; embedding
accounting remains separate. Any possibly started generation retains conservative accounting
when its usage is unknown. Cancellation and stream closing must drain owned resources once.

## Privacy and operations

LangSmith runtime tracing remains explicitly disabled, including environment-driven tracing.
Do not wrap the OpenAI client with a tracer. First use is synthetic local evaluation with uploads
disabled and evaluator tracing disabled; no account, paid plan, remote dataset or production
conversation export is authorized. No graph checkpoints, shared memory store or persistent
workflow cache is introduced; private SQLite conversation persistence remains in place.

Neo4j Community does not provide enterprise role-based isolation. A read access mode is a
driver hint, not a database-enforced permission boundary. Require a dedicated project instance,
private authenticated access and fixed application queries, and document the actual privileges.
PostgreSQL runtime and index/migration privileges are separate. Do not reuse Portfolio users,
databases, volumes, keys or indexes.

Application-owned images and local isolated smoke/restore tests belong here. vps-ops owns
deployment, shared capacity, Coolify, reverse proxy and infrastructure monitoring. Exact image
security findings, backup/restore, readiness, graceful shutdown and measured local resource
profiles remain gates; they do not demonstrate production capacity or external recovery.

## Finite acceptance

1. Negative domain/architecture regressions: unsupported embedding identity, nonfinite/zero or
   mismatched vectors, stale hashes, unsupported relations, absent evidence, accidental SDK imports
   and client/server boundary violations. No broad layer or linter exception.
2. Real isolated PG/pgvector and Neo4j tests: staged-only refusal, idempotence, parallel indexing,
   failed graph stage preserving active, cross-version/model rejection, tampered provenance,
   bounded queries and previous-version rollback/rebuild.
3. Real HTTP/session/CSRF/SSE fixture tests including replay, visitor isolation, cancellation,
   provider errors and final-answer/history agreement; no automatic generation retry.
4. Preserve original evaluations and freeze a new strategy-comparison manifest before running it.
   Report lexical/vector/graph/hybrid separately. Fixture vectors do not establish semantic
   quality; model generation alone does not establish semantic embedding retrieval quality.
5. Real tests only within explicit existing authorization, current official prices and a hard
   aggregate budget/attempt guard. Never reset prior costs or imply a proposed budget increases
   the existing cap. Keep full answers private and publish only reviewed nonsensitive evidence.
6. Exact hardened images, scans/SBOM, persistence/restore and shutdown checks; independent review,
   protected CI/PRs and final compatible contracts/handoff. The store stays disabled throughout;
   v1.1.0 tags wait for the complete requested increment, without moving an existing tag.

## Primary documentation

- [PostgreSQL 18 query plans](https://www.postgresql.org/docs/18/using-explain.html)
- [pgvector exact and approximate search](https://github.com/pgvector/pgvector)
- [Neo4j query tuning](https://neo4j.com/docs/cypher-manual/current/planning-and-tuning/)
- [Neo4j user and authorization limits](https://neo4j.com/docs/operations-manual/current/authentication-authorization/manage-users/)
- [LangGraph StateGraph](https://reference.langchain.com/python/langgraph/graph/state/StateGraph)
- [LangGraph custom streaming](https://reference.langchain.com/python/langgraph/config/get_stream_writer)
- [LangGraph checkpoint controls](https://reference.langchain.com/python/langgraph/graph/state/StateGraph/compile)
- [LangSmith evaluation controls](https://reference.langchain.com/python/langsmith/evaluation/_arunner/aevaluate)
- [Explicit LangSmith tracing context](https://docs.langchain.com/langsmith/trace-without-env-vars)
- [OpenAI embedding model and price](https://developers.openai.com/api/docs/models/text-embedding-3-small)

These links explain capabilities and controls. Their presence is not evidence that this
implementation or a VPS deployment has passed the gates above.
