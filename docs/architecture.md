# Architecture

A modular monolith with hexagonal boundaries, sized for one small catalog and one process.

```
browser (assistant-web, same origin) ──/api/v1──► presentation (FastAPI routes, SSE, middleware)
                                                     │
                                                     ▼
                              application (sessions, chat run lifecycle, budget, rate limits,
                                           answer validation, catalog activation) ── ports
                                                     │                                  ▲
                                   ai (evidence, prompt, output parser, composer)       │
                                                     │                                  │
                               adapters: OpenAI Responses · fixture · SQLite · catalog file/http
                                                     ▲
                                 bootstrap (settings, composition root, lifespan, logging)
```

| Layer | Path | May import |
|---|---|---|
| domain | `app/domain` | stdlib only: catalog facts, budget math, redaction, answer rules, errors |
| application | `app/application` | domain: use cases and `Protocol` ports |
| ai | `app/ai` | domain, application: grounding and the provider port |
| adapters | `app/adapters` | the above + pydantic, httpx, openai |
| presentation | `app/presentation` | domain, application + FastAPI: wire models are the contract |
| bootstrap | `app/bootstrap` | everything: the only place that wires concrete classes |

`tests/test_architecture.py` enforces the table (AST-based) and keeps SQL inside `adapters/sqlite`.

## One turn

1. `POST /api/v1/messages` passes middleware in order: request context → CORS → origin policy →
   16 KiB body limit. It then checks the session cookie and CSRF token.
2. `ChatService.start` runs every check that can refuse the request, each as an HTTP error:
   - enabled and catalog present
   - input size and page enum
   - idempotency claim (a replay returns the stored answer)
   - rate limits
   - card-number refusal (no model call)
   - contact-data redaction
   - history window (12 messages)
   - evidence and prompt preparation, with a byte-size bound
   - concurrency slot
   - worst-case budget reservation (`BEGIN IMMEDIATE`)
   - storing the user message
3. The stream: `GroundedComposer` makes **one** provider call. The strict JSON output is parsed
   incrementally, so `answer` text streams as `message.delta`.
4. On completion `finalize()` does three things:
   - resolves every product, resource, link and source id against the catalog
   - builds card metadata from catalog data only
   - applies the answer rules (and replaces the answer on a violation)

   It then stores the answer, settles the ledger to the reported usage and emits
   `message.completed` + `run.completed`.
5. Cancellation (endpoint or disconnect), deadline and provider failures each end the stream with
   exactly one terminal event. `ClosingStreamingResponse` guarantees cleanup (slot, registry, run
   state) even when the client vanishes. Partial answers are never stored.

## Deliberate choices

- **SQLite, single process** (ADR-0001). The volume is tiny, and one file on one volume is
  simpler to operate and back up than Postgres. `BEGIN IMMEDIATE` keeps budget accounting
  atomic, even across processes.
- **Whole-catalog grounding, lexical ranking as fallback** (ADR-0002). No embeddings, GraphRAG,
  Neo4j or agents: the catalog is about 17 KB, and the retrieval eval reaches recall@3 = 0.95.
- **Structured streaming + final validation** (ADR-0003). The stream is provisional; the final
  message is authoritative and validated.
- **Catalog from the storefront at a pinned commit.** The backend owns ingestion. The storefront
  stays the source of truth, read via `git archive` (docs/catalog.md).
