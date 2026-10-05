# Architecture

A modular monolith with hexagonal boundaries, sized for one small catalog and one process.

```
storefront (native assistant, cross-origin, CORS + cookie + CSRF) ──/api/v1──► presentation
backoffice server (bearer token, private network) ──/internal/v1/ops──►   (FastAPI routes, SSE, middleware)
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

## Language, metrics and spend states

- `domain/language.py` decides the reply language (es/en, or unsupported) before the model call;
  the composer passes it as `reply_language`. Unsupported languages get a static bilingual
  reply (no model call, no reservation).
- Every accepted or refused run writes one content-free row to `run_metrics` (outcome, failure
  code, model call yes/no, replaced, language, first-delta and total latency). Writing it is best
  effort: a failure is logged and never affects the answer. Retained 90 days.
- Ledger rows move `pending` → `settled` (provider usage, including on `response.incomplete`
  when usage is reported) or `unreported` (no usage: the reservation stays counted).
- `application/operations.py` builds the private ops summary from those two tables and the
  catalog state; `presentation/operations.py` serves it under `/internal/v1/ops`.

## Deliberate choices

- **SQLite, single process** (ADR-0001). The volume is tiny, and one file on one volume is
  simpler to operate and back up than Postgres. `BEGIN IMMEDIATE` keeps budget accounting
  atomic, even across processes.
- **Whole-catalog grounding, lexical ranking as fallback** (ADR-0002). No embeddings, GraphRAG,
  Neo4j or agents: the catalog is about 17 KB, and the retrieval eval reaches recall@3 = 0.95.
- **Structured streaming + final validation** (ADR-0003). The stream is provisional; the final
  message is authoritative and validated.
- **Medium reasoning effort** for `gpt-6-luna` (owner decision; ADR-0004). Reasoning tokens are
  billed as output and count toward `max_output_tokens`, so the allowance is 4000 and the run
  deadline 60 s, both to be tuned from live usage reports.
- **No LangGraph, Redis, PostgreSQL, vector store or graph database** (ADR-0002, ADR-0005): one
  bounded model call per turn is a plain function; a single process with SQLite has no
  coordination need; the catalog fits in one prompt.
- **Catalog from the storefront at a pinned commit.** The backend owns ingestion. The storefront
  stays the source of truth, read via `git archive` (docs/catalog.md).
