# Versioned public graph retrieval

PostgreSQL owns the public catalog snapshot, active pointer, chunks, lexical search and exact
pgvector search. Neo4j is a rebuildable projection of explicit public catalog relationships.
It never holds visitor conversations, credentials, orders, prompts or a second active pointer.
The production private-store and lifecycle composition are specified in ADR-0009.

`app/adapters/catalog/knowledge.py` validates the original catalog through the injected canonical
parser. It derives stable product/resource/document/link chunks and Product → Resource,
Document, Link or Topic edges from published fields and product scopes. Topic labels are exact
published strings. No LLM extraction, inferred health benefits, hidden offers, image alt text,
evaluation questions or private memory enter the searchable projection. Whole clauses must fit
the 8,000 UTF-8 byte chunk bound; oversize input fails instead of truncating a policy.

The knowledge fingerprint binds the exact catalog bytes, parser version and embedding
provider/model/dimensions. Production semantic embeddings use `text-embedding-3-small` (1536D).
The 64D hash adapter is exclusively synthetic fixture data; it does not demonstrate semantic
quality or provide a production fallback.

`HybridKnowledgeRetrieval` checks catalog freshness and matching PG/graph projections before
query embedding. It verifies every returned chunk version/hash against PG, verifies graph edge
provenance against PG and checks that one/two-hop paths connect an actual search seed to the
returned evidence. Product scopes prevent core merchant policies leaking to affiliates; both
explicitly named products require canonical comparison anchors. Activation races fail safely.
Only an outage after a successful preflight may degrade to verified PG evidence, with an
explicit flag. A known missing/stale projection never starts a paid query embedding.

The model does not generate SQL or Cypher. Graph traversal uses fixed parameterized queries,
at most two hops, bounded anchors/paths/results and a two-second read transaction timeout.
Neo4j Community grants broad database powers to authenticated users: READ routing is not
read-only authorization. Use a dedicated Pequeverso instance, credentials and network; never
share Portfolio or private application databases with this projection.

## Local fixture image and recovery

`Dockerfile.neo4j` pins the registry-verified 5.26.32 Community index
`sha256:0a6e7aedf54a531f76286032d4365ead65b11cca05e4a15cdf23b8e53d6db02b`.
It is a **fixture candidate with an open production security blocker**. Existing upstream
CRITICAL/HIGH findings require a fresh exact-image scan and disposition before deployment;
neither these tests nor an LTS label waive that gate. No image is published by this workflow.

The smoke uses UID/GID 7474, read-only root filesystem, dropped capabilities, no-new-privileges,
one CPU, 768MiB memory, no swap and bounded tmpfs paths. Heap is 256MiB, page cache 64MiB,
direct-memory limit 64MiB and transaction-memory limits are explicit. These are local fixture
limits, not measured VPS requirements. The private bridge exposes only loopback ports 17689
and 17479; a bridge is not an outbound firewall.

The unchanged vendor JNA jar supplies its matching native library at image-build time. The
native resource is installed read-only, with its SHA-256 retained; vendor jar/license stay
intact. The two JNA properties also apply to `neo4j-admin`, allowing `/tmp` to remain noexec.
The unnecessary Browser/unmanaged-extension modules are excluded. No jar is patched, removed
or replaced to hide vulnerability findings.

```bash
docker buildx build --load --provenance=false -f Dockerfile.neo4j -t pv-neo-fixture .
docker image inspect pv-neo-fixture --format '{{.Id}}'
uv run python scripts/smoke_knowledge_neo4j.py \
  --image sha256:<exact-local-image-id> \
  --receipt /absolute/external/new-receipt-directory \
  --private-dir /absolute/external/private-fixture-directory
```

The smoke covers real Bolt staging/idempotence, induced transaction failure/rollback, version
isolation, explicit path provenance, tamper detection, clean shutdown and offline dump/load.
After loading into a fresh volume it reads the original projection before any reindexing.
TCP liveness is not readiness: cold JVM compilation may reject early reads under the unchanged
two-second limit. Bounded read-only polling records those failures and requires the exact
restored stamp/counts. It never retries a model generation or rebuilds data to make recovery pass.
Only resources created by that invocation are removed; synthetic auth is deleted and full
service/test logs and the public-only dump remain under a private host directory.

The [dated verification record](verification/graphrag-2026-10-17.md) preserves original and
subsequent retrieval results, exact image identities, real CI and remaining semantic/security gates.

## Strategy evidence

`evals/knowledge/strategies-203.v1.json` freezes 203 deduplicated first-turn queries before
execution. It derives from previously exposed corpus cases plus 16 directed commercial/graph
cases. Historical holdout labels are preserved as provenance, **not** claimed as an independent
evaluation. Relevant source IDs affect scoring only; actual product scope uses the same
`mentioned_products` function as first-turn runtime retrieval.

```bash
uv run python scripts/evaluate_knowledge_strategies.py --fixture \
  --connections /absolute/private/owner-only-fixture-connections.json \
  --output /absolute/external/new-evaluation-directory
```

The explicit fixture connection file contains only `postgres_dsn` (dedicated loopback
55440/database `pv_graph_evaluation`) and `neo4j_uri`, `neo4j_username`, `neo4j_password` for
loopback 17689. It must be an owner-only regular file; provider credentials are not accepted.
The entry point requires committed application/evaluation code and records code/source hashes.
Lexical, synthetic-vector, lexical-seeded graph and hybrid results are separate. Records include
canonical chunks/hashes, path provenance and relevance metrics. No model is invoked and
`sent_to_model_chunk_ids` is empty. Fixture recall is neither semantic embedding quality nor
answer correctness, language compliance, purchase conversion, HTTP/session validation or VPS
readiness. Real-model and deployed HTTPS/CORS/cookie/SSE/restore/capacity checks remain separate.

Primary references: [Neo4j configuration](https://neo4j.com/docs/operations-manual/current/configuration/configuration-settings/),
[Community user permissions](https://neo4j.com/docs/operations-manual/current/authentication-authorization/manage-users/),
[JNA native loading](https://github.com/java-native-access/jna/blob/5.15.0/src/com/sun/jna/Native.java).
