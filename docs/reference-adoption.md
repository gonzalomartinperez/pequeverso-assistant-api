# Reference adoption record (portfolio-assistant-api)

`portfolio-assistant-api` has **no source license** (all rights reserved). Ideas were adapted;
no code was copied. It was inspected read-only: `git show` and the GitHub API on immutable
commits, never its working tree.

| Inspected | Improvement | Decision | Reason / compatibility |
|---|---|---|---|
| `47219c3` (develop) | Hexagonal layers + AST architecture test | Adapted | Same idea, own layer map (`ai` separate; stdlib-only domain/application) |
| `47219c3` | Opaque cookie secret stored as a digest + CSRF token in the body; Origin allowlist on mutations | Adopted (own code) | Fits anonymous shoppers; same-origin embed keeps it |
| `47219c3` | Responses API streaming, `max_retries=0` at the SDK, fixture provider as default | Adapted | Structured JSON output (references) instead of free text; runtime SDK and adapter retries are now0; historical bounded-retry option remains for isolated adapter tests |
| `47219c3` | Worst-case budget reservation and settlement; missing usage keeps the reservation | Adapted | SQLite `BEGIN IMMEDIATE` instead of a Postgres advisory lock; added a **daily** cap and per-session limits (the reference has no per-session cap); settle fails loudly if no reservation exists (the reference has no row guard) |
| `47219c3` | SSE envelope with sequence, heartbeat comments, guaranteed close on disconnect | Adapted | Own event set (`message.completed` authoritative); explicit per-step deadline (a task-bound timeout across generator yields never fires, a bug found in testing) |
| `47219c3` | Redacting JSON log formatter, no access logs, uniform error envelope | Adopted (own code) | — |
| `47219c3` | Pinned contract artifacts + manifest + drift check in CI | Adopted | `contracts/export.py` also builds examples through real validation code |
| `47219c3` | Postgres + pgvector + Neo4j GraphRAG + LangGraph | **Rejected** | A catalog of about 17 KB; retrieval eval 0.95 recall@3 lexically (ADR-0002) |
| `47219c3` | Skills as real files in `.claude/skills`, symlinked from `.agents` | Rejected (layout) | Followed the storefront convention instead: canonical `.agents/skills`, thin `.claude` adapters |
| `4602abe` | Spoofed and malformed `X-Forwarded-For` rejection | Adopted | Right-to-left walk over trusted CIDRs, chain ≤ 5 |
| `44f70ed` | Concurrency test for reservations | Adopted | Plus a 4-process test on one SQLite file |
| `b7d33fb` (merged as #22) | Bound serialized provider input before the call | Adopted (already) | Input byte size is the token upper bound for the reservation; over `MAX_INPUT_TOKENS` → rejected before any call |
| `5742961` (#23) | Preserve conversational topic across follow-ups | Adapted | Assistant turns in history carry `referenced_ids` so "the second one" resolves |
| `c085b93` / `4186664` (#23) | Embedded-first handoff: `/api` prefix preserved, empty `root_path`, host-only Lax cookies, no Domain cookies or `SameSite=None`, iframe kept mounted on minimize, exact frame-ancestors | Adopted | Matches this contract (docs/api-contract.md) |

Next check: before the release-candidate PR and whenever a new reference PR touches security,
sessions or budgets.
