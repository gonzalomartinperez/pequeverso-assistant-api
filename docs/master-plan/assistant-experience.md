# Assistant experience v2: specification for both assistants

Status: specification (proposal). Date: 2026-11-09. Scope: `portfolio-assistant-api` (bilingual EN/ES, GraphRAG over an AI engineer's public work; visitors and recruiters) and `pequeverso-assistant-api` (Spanish-only, read-only shopping advisor for a printable children's kit sold through Hotmart). Clients are the widgets of [assistant-widget.md](assistant-widget.md). Builds on ecosystem section 12 (quality standard) and decisions OD-30 to OD-32, DR-04, DR-05.

Evidence: both repos on `origin/develop` (graph, providers, SSE schema, OpenAPI, ADR-0003, ADR-0008), both quality and target-state plans, research 02 and 03, LangChain docs via MCP (custom stream events verified; Store TTL partly). Items marked **(unverified)** were not checked live; numbers marked "proposal" must be validated by the named test. Nothing here authorizes a paid call or deployment; spend stays owner-only (DR-04).

## 0. What exists today (the starting line)

**Portfolio.** LangGraph with two nodes (`retrieve`, `answer`), `recursion_limit` 4, checkpointer keyed by `run_id`, custom stream writer for deltas (`app/ai/workflow.py`). SSE events: `run.started`, `run.status` (`evidence_found`), `message.delta`, `message.completed`, `run.completed|failed|cancelled`. `Citation` has `source_type` `page|code`. `OpenAIWebSearch` covers seven closed topics (LangGraph, Neo4j, pgvector, PostgreSQL, FastAPI, Next.js, OpenTelemetry) with one fixed query each, an `allowed_domains` filter, at most 2 tool calls, 12 s timeout, 1 h cache and a separate ledger; visitor text never becomes a query (`domain/web_policy.py`). A feedback endpoint exists. History lives behind an HttpOnly session cookie with 7-day retention; external tracing is refused by a settings validator. Budgets: p95 < 6 s, < 2 cents, at most 6 steps.

**Pequeverso.** One Responses API call per turn with strict JSON `{answer, references, sources, follow_ups}` (ADR-0003); deltas are validated sentence prefixes and the final message is authoritative. `message.completed` already carries `products`, `resources`, `links`, `sources`, `follow_ups`, `notices`, `language`; the price object has `amount`, `currency`, `display`, `verified_at`. ADR-0008 allows a server-side fixed read of three Hotmart buyer-procedure articles (opt-in, no model tools, activation not authorized). No feedback endpoint; retention 24 h, content-free operations data. Budgets: p95 < 8 s, < 4 cents (measured about USD 0.00057 per generation).

Two observations drive the design. The pequeverso catalog fits the 24 KB evidence bound, so latency is the model call plus validation buffering. The portfolio web tool is already a safe pattern; v2 keeps its invariants.

## 1. Principles

1. **Facts are server-built, prose is explanatory.** Prices, guarantees, links, employers, dates and product ids reach the UI only from validated structured fields (widget principle 4).
2. **Fast and honest.** Show real progress the instant it exists; never fake thinking; abstain quickly and deterministically.
3. **Additive only.** Every wire change is optional and opt-in (ecosystem 3.3, PAA-D17).
4. **Learn about the product, not about people.** Per-visitor memory is opt-in, tiny, enumerated and erasable; the system improves from aggregate, redacted failures approved by two independent reviewer agents (owner gets a weekly summary with veto).
5. **Every capability has a switch and a budget**, and an eval that must be green before it defaults on.
6. **Pragmatism (O3).** Where the pequeverso single-call design works, v2 wraps it instead of adding an agent loop.

## 2. Performance

### 2.1 Targets (all proposals, validated by the named harness)

Measured at the API edge (request received to first byte of the named event), provider network included, client network excluded, warm instance, cache cold unless stated.

| Metric | Portfolio | Pequeverso | Validated by |
|---|---|---|---|
| Time to first event (`run.started` plus first `run.progress`) | p50 <= 150 ms, p95 <= 300 ms | same | SSE load test, `tests/load` |
| TTFT, first `message.delta` | p50 <= 1.0 s, p95 <= 2.0 s | p50 <= 1.4 s, p95 <= 2.8 s until the sentence-validation buffer is measured (ADR-0003 holds back text until a full validated sentence) | live lane, k = 3, plus nightly canary |
| Full answer p95 | <= 5 s (gate stays 6 s from ecosystem 12.3 until a baseline exists) | <= 6 s (gate stays 8 s) | live lane |
| Deterministic abstention or starter replay, first delta | p95 <= 200 ms, no model call | same | integration test with stub provider |
| Server overhead excluding provider time | p95 <= 150 ms | p95 <= 100 ms | deterministic lane with a fake clock and a stub provider that sleeps a fixed time |
| Cost per answer | typical <= 0.5 cent, hard cap 2 cents (existing) | typical <= 0.15 cent (measured 0.057 to 0.13), hard cap 4 cents (existing) | usage ledger plus live lane report |

Pequeverso TTFT is deliberately weaker: ADR-0003 exists because a false price once reached a delta, so its TTFT is the first validated sentence and the early `run.progress` event restores perceived speed. If measurement shows the buffer dominates, the lever is shorter first sentences (an eval-gated prompt change), never unvalidated text.

### 2.2 Streaming structured events

Two additive layers. **Progress phases** (opt-in header `X-Assistant-Progress: 1`, already planned as `run.progress` in the portfolio `target-state.md` section 6): closed set `understanding`, `retrieving`, `checking_web`, `reading`, `writing`, `verifying`; payload is a phase id and an optional `sources_found` count, never derived from visitor text; the widget owns localized copy. Pequeverso uses the subset `understanding`, `reading`, `writing`, `verifying`; whether to show labels stays a client string-table choice. **Typed blocks** (section 4): text streams as `message.delta` as today; other blocks arrive in `message.completed` (authoritative) and, behind `early_blocks`, as `message.block` once each block is validated on its own.

The graph uses LangGraph custom stream mode with `get_stream_writer` (verified in the LangChain docs: emit inside a node, consume with `stream_mode` including `"custom"`, combinable with `"updates"`). v2 makes the custom channel a typed envelope (`{kind: delta | progress | block}`) mapped to SSE in one `presentation/` adapter. Heartbeat: an SSE comment line every 15 s while a provider is slow (proposal; check the vps-ops proxy idle timeout).

### 2.3 Parallel retrieval

Portfolio legs run concurrently with `asyncio.gather` and independent deadlines (proposals); a leg that misses its deadline is dropped, never awaited: query embedding 400 ms (the TTFT-critical step; on timeout use lexical plus graph, telemetry `degraded: no_semantic`), semantic 600 ms, lexical 200 ms, graph expansion 500 ms (vector-only baseline still answers), memory read 150 ms (answer without personalization), web supplement 4 s in the answer path (otherwise answer from first-party evidence; never wait). Pequeverso needs no fan-out today; with ADR-0009 hybrid retrieval the same legs apply and the catalog snapshot is the floor, so any outage still yields a price-validated answer.

### 2.4 Caching (what is safe to cache)

| Cache | Key | Value and rules |
|---|---|---|
| Query embedding | normalized text hash plus model id | vector; 24 h in-process LRU; exact match only |
| Semantic retrieval cache | embedding bucket (cosine >= 0.97 to a stored query vector) plus locale plus `corpus_snapshot_id` plus retriever config hash | ranked evidence ids only (never text or answers), re-read from the live store so a retired chunk cannot be served; max 6 h; threshold set by an eval proving no recall drop |
| Starter answer replay | starter id plus locale plus corpus snapshot plus prompt version plus catalog hash | the validated final message replayed as a normal stream; built by a deploy-time job and only if it passes every validator; first delta in tens of milliseconds |
| Web topic cache | topic | existing: 1 h success, 60 s failure |
| Free-form answer cache | none | Not built: answers carry validated commercial facts, history and memory, so caching risks stale prices and cross-user leakage for almost no hit rate |

**Provider prompt caching.** Both assistants use OpenAI Responses (`gpt-6-luna`), which documents automatic prefix caching for long prompts **(unverified: threshold, discount and retention for this model)**. The rule is provider-neutral: build each request as static policy prompt, then static knowledge prefix (pequeverso: the whole compact catalog sorted deterministically; portfolio: the style guide), then variable evidence, history and question, with no timestamps, ids or per-visitor text before the variable part (the date comes from the `Clock` port after the prefix). A provider needing explicit cache markers gets them in the `Provider` adapter. Acceptance: a unit test asserts the prefix is byte-identical across two questions, and the live lane reports the cached-token ratio.

### 2.5 Model routing

Deterministic code (no model) handles input guard, language, scope and abuse rules, and payment-data detection. Intent routing (answer, clarify, out of scope, needs web, chitchat) uses rules first and a small cheap model only for the ambiguous remainder, with a closed-enum structured output. Follow-up rewrite ("and the second one?") uses a small model on the last 4 turns only when anaphora markers appear. Answer composition uses the strong model (`gpt-6-luna`), with reasoning effort chosen per assistant by eval. Judges (CI only) use a different family than the generator. The `model_router` flag is accepted only if full-set route accuracy is >= 98% and no safety stratum regresses. Reasoning effort is probably the biggest TTFT lever on reasoning models **(unverified for this provider)**: test `low` versus `medium` on the full set before changing ADR-0004.

### 2.6 Timeouts and graceful degradation

Whole run 25 s hard (`run.failed`, retryable; the widget shows its own 8 s and 25 s states). Provider first token 6 s; no automatic billed retry (existing). Evidence insufficient: immediate deterministic abstention with the support route and curated rephrasings, no model call. Web unavailable or budget exhausted: answer from the corpus plus a `web_unavailable` notice, never silently. Validator failure: ADR-0003 terminal replacement, blocks suppressed. Memory store down (150 ms): stateless answer and the memory controls show an inline note. Neo4j down (500 ms): vector-only baseline (kept in CI for this). A circuit breaker per dependency (open after 5 failures in 30 s, probe at 15 s) writes `degraded` reasons to the run record.

## 3. Answer quality and grounding

### 3.1 Composition rules (both assistants)

1. Answer first, in the user's language, then minimum support, then an optional next step; no preamble.
2. Every factual sentence is supported by at least one evidence id; unsupported sentences are dropped or the answer becomes an abstention.
3. Qualifiers in the corpus ("estimated", "reported") travel with the claim.
4. Portfolio speaks of the person in third person (`third_person_attribution`); pequeverso speaks as "el asistente de Pequeverso", neutral Latin American Spanish with "tú", no voseo (`variety.neutral`).
5. Never promise outcomes, discounts, availability, hiring or reading results.
6. Ask at most one clarifying question, only if it changes the answer (judged on the full set by `no_needless_clarification`).

### 3.2 Length and tone per audience

Portfolio: recruiters get 60 to 110 words, impact first, one proof link; engineers 90 to 180 words with trade-offs; curious visitors 50 to 90 plain words. Pequeverso: parents deciding get 40 to 90 words, answer then one relevant card, warm and without pressure or urgency; parents with a problem (access, refund) get 30 to 70 calm procedural words plus the human-handoff route. Caps are checked by a deterministic length grader (the 2000-character pequeverso limit exists). Language: portfolio answers in the detected locale (unsupported input languages are answered in EN or ES per the existing policy); pequeverso always Spanish, with a polite Spanish reply and the local notice to an English question (OD-32).

### 3.3 Claim-level citations and the "fundamentos" section

The structured output gains a `claims` list in place of a single `references` list. The model proposes; the server verifies and builds the public blocks.

```
claims: [{ text_span: "Gonzalo led the Filomena backend", evidence_ids: ["en/projects#filomena"] }, ...]
```

Server pipeline: (1) every evidence id is in the sent set (existing `dropped_references` metric); (2) each claim span is found in the answer text; (3) numbers, names, dates and employers in the claim appear in the cited evidence (normalizing es-ES and en number formats, reusing `answer_policy._amount` and `fold`); (4) failing claims are removed and the answer re-validated, and if none remains the run becomes a deterministic abstention. Semantic entailment beyond string and entity match is not claimed (ADR-0003 states the same limit); an NLI model is a later, eval-validated option.

**Fundamentos** (portfolio label "Basis", pequeverso label "Fundamentos") is a collapsed block listing, per citation marker, a **server-extracted quote** (at most 200 characters, taken verbatim from the stored evidence chunk by offset, never written by the model) plus the source. Because the quote is copied by code, it cannot be hallucinated, and a reviewer can click through to the source. Pequeverso keeps its rule that official platform help is labelled "Hotmart · procedimiento general" and never presented as a guarantee for the kit.

### 3.4 Confidence and abstention

Confidence is computed, never self-reported. `high`: evidence sufficient, every claim supported, no validator warnings (nothing shown). `medium`: one weak source or a qualified claim (the qualifier stays in the text). `low`: part of the question unanswered (the text says what is missing and a block offers the support route). `abstain`: `evidence_sufficient` false (planned retrieval field, P0-2) or a validator emptied the answer; templated, no model, route to contact. Thresholds come from ablation on the full set (portfolio P0-2: minimum score, entity-presence check). The unsupported-employer case must abstain from retrieval logic alone, not from the prompt. False-abstain rate (answerable items that abstained) is tracked with a 5% ceiling on the full set in both repos.

### 3.5 Follow-up suggestions

Two or three, proposed by the model but filtered by code: answerable from the corpus (a retrieval probe against the evidence-sufficient threshold), not a repeat, in the answer language, free of prices, claims and personal data. Failing items are dropped, never rewritten. Abstentions use curated rephrasings per intent family (no model).

### 3.6 Deterministic validators before finalization

Run inside `validate_final`; each is a golden assertion. Both: language equals policy; evidence ids exist in the sent set and claims are supported; URL and email allowlist; canary and prompt-leak check; PII and secret scrub. Portfolio adds: every named employer and institution exists in the corpus entity table; dates only with their public reference date; metrics keep their "estimated" or "reported" qualifier. Pequeverso adds: every amount equals the catalog price for the referenced SKU and none appears when prices are unverified or stale (existing `check_answer`); guarantee days equal the product's own and the affiliate guarantee is never transferred to the kit (new `guarantee.days`); no invented discount, urgency, testimonial, outcome promise, order action or payment request (existing behaviour tags); payment-data refusal notice. A failing validator blocks finalization: the existing terminal replacement emits the safe answer and no blocks. A hit is a telemetry event and a candidate golden item (section 6.5).

## 4. Rich response UI contract (additive v1.x)

### 4.1 Mechanism

| Change | Detail | Compatibility |
|---|---|---|
| `blocks` | Optional ordered array on the completed message (`message.completed`; portfolio also on the stored `MessageView`). Absent unless the request sends `X-Assistant-Blocks: 1` | v1 clients ignore it; legacy fields (`sources`, `products`, `links`, `follow_ups`, `notices`) keep being populated for one release (dual write), removal only as a `contract-major` |
| `run.progress` | Section 2.2 | opt-in header |
| `message.block` | Early single block, flag `early_blocks`, default off | opt-in |
| `capabilities` on the session response | `{blocks: true, memory: true, web: false, feedback: true}` so the widget renders only what exists | new optional member |
| Version | Portfolio: part of contract v1.1 or v1.2 (ADR-0020, M5); pequeverso: contract v1.7 (v1.5 current, v1.6 at M3) | schemas, examples and oasdiff updated together |

The block union is closed; an unknown `type` renders nothing (fail closed). Blocks carry an `id` and no HTML.

### 4.2 Block types

| `type` | Fields | Notes |
|---|---|---|
| `text` | `markdown_lite` (bold and "- " lists only, as the widget already allows), `claims[{start, end, evidence_ids}]` | markers `[n]` are derived from `claims`, not typed by the model |
| `citation` | `id`, `title`, `url`, `source_type`, `icon_id`, `origin` (`first_party` or `web`), optional `path`, `start_line`, `end_line`, `commit_sha`, `quote` (server-extracted) | `source_type` closed enum: `page`, `doc`, `repo`, `code`, `product`, `official_help`, `web` (the v1 enum `page`, `code` stays valid) |
| `product_card` (pequeverso) | `product_id`, `name`, `summary`, `age_range`, `image{url,width,height,alt}`, `price{amount,currency,display,note,tax_note,verified_at}` or `null`, `url`, `purchase_url` or `null`, `disclosure` | exactly the validated `ProductOut` of v1, wrapped; a card is built from the catalog by `product_id`, never from model text |
| `resource_card` (pequeverso) | `resource_id`, `title`, `pages`, `image` | maps `ResourceOut` |
| `project_card` (portfolio) | `repo`, `title`, `summary`, `url`, `stack_icon_ids[]` (closed enum), `role`, `period` | built from the knowledge graph entity, never from model text |
| `link_chip` | `label`, `url`, `kind` (`contact`, `cv`, `repo`, `demo`, `support`, `help`), `icon_id` | URL validated against the allowlist; at most 3 per answer |
| `fundamentos` | `items[{citation_id, quote}]`, `confidence` (section 3.4) | collapsed by default |
| `follow_ups` | `items[{id, text}]` | the request carries the full original text of the chosen item (existing allowlist rule) |
| `notice` | `code` (closed enum), `severity`, `text_ids` | existing notice codes plus `web_unavailable`, `memory_saved`, `abstained` |
| `feedback` | `message_id`, `reasons[]` (closed set from widget section 6) | portfolio posts to the existing endpoint; pequeverso shows it only after the API adds one (never faked) |
| `memory_prompt` | `proposed_facts[{key, value}]` | offer to remember, never auto-saves (section 6) |

The server fixes block order (text, cards, citations, fundamentos, follow-ups, notices, feedback); the widget never reorders.

### 4.3 Icons, link safety, UTM

- **Icons**: the server sends `icon_id` from a closed enum; the widget ships a local SVG sprite and never fetches a remote favicon (no third-party request, no visitor-IP leak). Unknown ids fall back to a generic link icon. Web and first-party sources differ by glyph shape and a text badge ("Web"), not colour alone. Portfolio stack icons are a closed enum of technologies present in the corpus graph, stored in the portfolio token layer, each with an accessible name; a missing icon renders the name as text.
- **URL policy**: server-side, https only, host in `ALLOWED_HOSTS` (site origins, the owner's public GitHub repos, per-topic official documentation hosts, the official help host for pequeverso, `mailto:` only for the configured support address), canonicalised (existing `canonical_web_url`); anything else is dropped before the block is built.
- **UTM**: the assistant adds no `utm_*`, `ref` or click redirector. Pequeverso `purchase_url` keeps only the Hotmart `sck=assistant` code through `CheckoutLink` (widget section 3.5); the owner can drop it with one config line.
- **Attributes**: `rel="noopener noreferrer"`, `referrerpolicy="no-referrer"` for web origin, `target="_blank"` for external; no auto-linking of prose. Text never becomes a link, price or card by parsing; an unlisted URL in text makes the validator replace the answer (existing).

### 4.4 Rendering (accessibility summary; detail in widget section "Rich blocks rendering")

Text is a paragraph; citation markers are links named "Fuente 2: title, tipo"; sources form an ordered list; fundamentos is a native `details`; cards are `article` elements named by title with the price in one text node; chips are links; follow-ups are buttons in a labelled group; notices use `role="note"`; one polite live region announces only the completed text, not progress phases. Blocks mount after `message.completed` below the reader's anchor, with fades removed under `prefers-reduced-motion`.

## 5. Internet access when needed

### 5.1 Tool policy

| | Portfolio | Pequeverso |
|---|---|---|
| May search when | The question needs a public technical fact or current state of a closed topic and the corpus has a profile anchor for it (existing `technical_topic`) | Only for general buyer procedures of the platform (download, access, receipt, general refund procedure) and flag `web_official_help` on |
| Never | Anything about the person beyond the corpus, people, news, hiring claims, free-form queries | Product facts, prices, guarantees, kit policy, orders or accounts, any other domain |
| Query built by | Code: one fixed query per topic (visitor text never becomes a query) | Code: three fixed articles (ADR-0008) |
| Allowlist | Per-topic official documentation host (seven today); additions are PRs with an eval item, approved by the review chain (two reviewer agents) | The official help host only |
| Denylist | All else; private, loopback and link-local addresses, non-https, cross-host redirects, credentials, non-default ports | same |
| Model tools | Hosted `web_search` restricted by `allowed_domains`, `max_tool_calls` 2, single-purpose call with no other tool | None; server fetch |

### 5.2 Provider options

| Option | Assessment |
|---|---|
| A. Current OpenAI hosted `web_search` with `allowed_domains` (portfolio) | Works, domain filter, citations, separate ledger; per-call fee **(unverified)**, one-vendor lock, injection exposure in the summarizer. Keep as the refresh path for "latest" questions |
| B. Fixed-endpoint fetch (pequeverso ADR-0008) | Deterministic, no model tool; endpoint is not a documented contract, fails closed, needs vps-ops egress review. Keep, off until activation gates pass |
| C. Weekly documentation snapshot ingested into pgvector as source type `web` with a capture date | No runtime internet for most questions; gives caching, evals, offline fallback and stable citations; needs a license and robots check per site and an owner-reviewed diff per refresh; up to a week stale. **Recommended primary for the portfolio**, labelled "web, captured {date}"; use A only if the question asks for the latest or the snapshot is older than 14 days |
| D. Third-party search APIs or self-hosted meta search | Broader coverage but new vendor, data flow, cost, privacy review and injection surface. Not recommended |

### 5.3 Sanitization against prompt injection

1. Web text is data: it enters only inside a delimited untrusted block of the answer call, never in system or developer roles (exists today).
2. The summarizing call has no other tools; its output is bounded (1 to 6000 characters today).
3. Only citations on allowlisted hosts survive; any other host discards the whole supplement (existing).
4. Strip markup, control, zero-width and bidi characters; plain text; per-source and total caps.
5. Instruction-like patterns are logged as `injection_suspect` events and become golden attacks; they are not the defence (pattern filters are bypassable, **unverified general claim**).
6. Answer validators still run; web-derived sentences cannot introduce a URL, employer or price outside the allowlists.
7. Snapshots (option C) are checked at ingest and diffed; a large diff or one with instruction patterns waits for review by two reviewer agents and is flagged in the owner's weekly summary.

### 5.4 Attribution and caps

Web-origin sources use a distinct block shape (`origin: "web"`, glyph, badge, host shown, capture date for snapshots); a sentence supported only by web evidence is worded "según documentación oficial de {host}" and never shown as first-party. Proposed caps on the existing separate ledger: 1 web call per answer, 20 per session per day, a daily ceiling of 5% of the USD 10 monthly budget, plus the global hard stop (DR-04). Offline fallback: flag off, budget exhausted or provider failure gives a first-party answer and the `web_unavailable` notice. Topic caches absorb repetition, so a visitor cannot trigger web calls by repeating questions.

### 5.5 Tool-use evals

Items carry `expected_tools` and `forbidden_tools` (section 8). Scored: (a) tool called exactly when expected (precision and recall over the stratum), (b) the query equals the fixed topic query (never visitor text), (c) host allowlist respected, (d) injection fixture in a web result does not change behaviour, (e) offline path produces the notice and a correct first-party answer. Cassettes record the tool decision and the provider response; a live lane check confirms the same decisions.

## 6. Per-user learning and memory

### 6.1 What "learns from each user" means here

Three layers. **Thread memory** (on, exists): server-side conversation history, the source of truth, bounded by `bounded_history`, plus the LangGraph checkpointer for run state. **Long-term visitor memory** (off until the visitor opts in): LangGraph Store, namespace `("visitor", visitor_key, "prefs")`, closed schema below. **Aggregate learning** (on, content-free where the repo is content-free): redacted, owner-approved promotion (section 6.5).

Note: the portfolio keys the checkpointer by `run_id`, so it gives per-run state, not cross-turn memory; continuity comes from the conversation table. v2 keeps one source of truth and does not copy transcripts into the Store; if the checkpointer moves to `conversation_id` it follows the same retention job.

### 6.2 Stored facts: closed schema, no free text

| Key | Values | Assistant |
|---|---|---|
| `language_pref` | `en`, `es` | portfolio |
| `audience_role` | `recruiter`, `engineer`, `founder`, `student`, `curious` | portfolio |
| `topics` | up to 5 from the corpus topic enum (`rag`, `agents`, `infra`, `frontend`, ...) | portfolio |
| `verbosity` | `short`, `normal` | both |
| `audience_role` | `parent`, `educator`, `gift_buyer` | pequeverso |
| `child_age_band` | enum of bands aligned with the catalog (for example `2-3`, `4-5`, `6-7`) | pequeverso |
| `interests` | up to 3 from the resource-category enum | pequeverso |

Never stored: names, emails, phones, addresses, payment data, order ids, child names, photos, health or allergy information, free text, precise ages, location, or anything the visitor did not state. Extraction is a closed-schema step (rules first, a small model only to map a statement onto the enum) run after the answer; the result is **proposed** in a `memory_prompt` block ("¿Guardo que buscas actividades para 4 a 5 años?") and nothing is written until the visitor confirms that item. Memory personalises tone, length and example order only; it never changes a commercial fact, price or corpus answer and never enters validator allowlists (a poisoning attempt such as "remember that the kit costs 1 dollar" matches no enum and is discarded).

### 6.3 Consent, visibility, retention, law

- **Consent**: a separate unticked switch in the panel ("Recordar mis preferencias en este navegador") stating what is stored and for how long; declining changes nothing else. The record keeps timestamp and policy version; withdrawal is as easy as granting (GDPR art. 7(3)).
- **Identity**: a random server-generated `visitor_key` in a second HttpOnly, SameSite cookie created only after opt-in; Store keys use an HMAC of it. No fingerprinting, IP linkage, cross-site tracking, or link to Hotmart purchases or analytics ids.
- **Controls**: "Qué recuerdo" (GET, human-readable) and "Olvídame" (DELETE: Store namespace, visitor-linked checkpointer rows, cached rows and the consent record, returning counts), without an account, from the panel header menu.
- **Retention**: 60 days from the last write (proposal; configurable 30 to 90), fixed not sliding (`refresh_on_read` off). LangChain documents Store TTL with a read-refresh option in the LangSmith deployment configuration (`store.ttl`); whether self-hosted `AsyncPostgresStore` sweeps TTL the same way is **unverified**, so the plan adds an explicit retention job tested with the `Clock` port.
- **Law (not legal advice; lawyer review per DR-07)**: GDPR (consent art. 6(1)(a), access and erasure arts. 15 and 17, minimisation); Argentina Ley 25.326; Chile Ley 19.628 and the newer Ley 21.719 **(unverified: entry into force)**; Mexico LFPDPPP and its 2025 replacement **(unverified)**. Privacy notices disclose AI use and the feature. Pequeverso's band describes a child indirectly, so it is coarse, optional and **ships disabled** until the DR-07 review covers it.
- **Security**: the `MemoryStore` port takes `visitor_key` from the authenticated session only, never from request bodies or model output.

### 6.4 No cross-user leakage: tests

(1) Property test (Hypothesis, in-memory and Postgres adapters): nothing written for visitor A is returned by any read for B. (2) Canary: A stores a unique canary topic; B's prompts, traces, caches, errors and logs never contain it. (3) Namespace injection: a message naming another key cannot change the namespace. (4) Forget completeness: after DELETE every table and cache keyed by the visitor returns zero rows and counts match what GET showed. (5) TTL with a fake clock. (6) Consent off: a spy adapter sees zero Store calls. (7) Poisoning: statements outside the enum never persist.

### 6.5 Aggregate learning loop (no personal data)

1. Every abstention, thumbs-down, validator hit or unanswered question is classified into a closed intent family and counted (no text; both repos).
2. Portfolio (content already stored for 7 days): the text is redacted (emails, phones, ids, URLs, names) into a candidate row with no visitor or session key and a 30-day life. Pequeverso stays content-free: text is captured only when the visitor presses "Enviar esta pregunta para mejorar" (consent, redacted).
3. The backoffice queue clusters candidates; two independent reviewer agents approve or reject (a third breaks ties). Approved items enter the full set automatically; golden promotion needs the same two-agent approval (incidents within 48 h), listed in the owner's weekly summary with veto and respects the quota rules of ecosystem 12.1, retiring redundant items to quarantine to keep the size band.
4. Retrieval improvements (synonym and alias rules, chunk fixes, corpus gaps the owner fills) are measured by the harness before merge, using redacted aggregates only.

Nothing is promoted without two-agent approval and an entry in the owner's weekly summary; promoted items are rewritten to remove incidental detail.

## 7. Harness

### 7.1 Graph design

Portfolio (nodes inside `ai/workflow.py`, capabilities injected through ports):

```
START -> guard_input -> route -> [retrieve_parallel || memory_read] -> evidence_gate
  evidence_gate --insufficient--> abstain_template -> finalize_blocks -> END
  evidence_gate --needs_web----> web_supplement -> compose
  evidence_gate --ok-----------> compose
compose (stream) -> validate_final -> finalize_blocks -> memory_propose -> END
```

Pequeverso: `guard_input` (payment-data and scope rules) -> `route` -> `[catalog_resolve || official_help (flag) || memory_read]` -> `compose` (one structured call) -> `validate_final` -> `finalize_blocks` (cards built from the catalog snapshot) -> `memory_propose`. There is no model tool loop; ADR-0008 and ADR-0003 remain binding.

Guards: `guard_input` is deterministic (length, language, abuse, payment data, scope) and refuses without a model call; step and recursion limits end in a retryable `run.failed`; the atomic spend reservation is a hard stop; `web_supplement` runs only for fixed queries; `validate_final` replaces failing drafts; memory is written only after explicit confirmation.

Dependencies stay behind ports (`WebSearch`, `MemoryStore`, `RetrievalCache`, `Router`, `Flags`, `Clock`); LangGraph, LangChain and LangSmith imports stay inside `adapters/graph` (pequeverso) or `ai/` (portfolio), enforced by import-linter (target-state section 3).

### 7.2 Prompt and version registry

Prompts live in git (ADR-0014) with `prompts.lock` (id, version, sha256), pinned at start; every run records `prompt_version`, `model_snapshot`, `retriever_config_hash`, `corpus_snapshot_id` (migration 011 or telemetry only). Prompt changes pass the code gate; no hosted registry (ADR-0021).

### 7.3 Tracing and online evaluation

Decision AX-D8: OpenTelemetry spans to the project's own store are the production default; LangSmith serves CI, cassette and live eval runs on synthetic or golden data. Production export to LangSmith stays off (portfolio validator, ADR-0021) unless the owner decides otherwise, with PII redaction in the span processor. Online evaluation (Phase V): deterministic evaluators on 10% of runs (language match, price grounding, citation present, claim-support, tool-decision sanity, latency, cost) and on 100% of validator hits; an invented price pages the owner; an abstain-rate shift over 5 points in 7 days opens a ticket (ecosystem 12.3).

### 7.4 Red team and injection

Per PR touching prompts, tools or validators: 30 to 60 deterministic attacks (ecosystem 12.3), now including injection in retrieved chunks and web results (fixtures), URL exfiltration bait, "search the web for Gonzalo's salary", namespace injection, memory poisoning, price-bait, invented discount, prompt extraction and ES jailbreak. Weekly garak or PyRIT sweep; each success becomes an adversarial golden item (OWASP LLM01, 02, 06, 07, 08, 09).

### 7.5 Kill switches, budgets, flags

Runtime flags (DB-backed, readable by the backoffice, audited, effective without redeploy), all default off until their gate passes: `web_access` (tool-use evals 100%, spend caps tested), `web_official_help` (ADR-0008 activation gates, vps-ops egress review), `memory` (isolation tests green, consent copy approved, pequeverso lawyer review), `blocks_v2`, `progress_events`, `early_blocks` (widget shipped, contract tests green), `semantic_cache` and `model_router` (no recall or safety regression on the full set). `assistant_enabled` exists per site. Breakers and the monthly hard stop (USD 10 per project) are independent of flags.

### 7.6 Backoffice dashboard fields (no visitor text)

Per run: ids, locale, prompt version, model snapshot, corpus snapshot, route, legs used and degraded, evidence sufficient, confidence, validators fired, tools and cost, tokens and cached tokens, TTFE, TTFT, total latency, abstain, notice codes, feedback, memory consent state, flag states. Aggregates: p50 and p95 by locale, cost per answer, cache hit rate, abstain and false-abstain rate, web spend, validator hit rate, memory opt-in and forget counts, candidate queue size.

## 8. Evals added (integrated, no new tier)

All additions live inside the tiers of OD-30 and OD-31.

| Family | Graders (deterministic first) | Golden (100%) | Full set |
|---|---|---|---|
| Tool-use correctness | `tools.expected`, `tools.query_fixed`, `tools.host_allowed` | portfolio 4, pequeverso 2 | precision and recall per family |
| Citation correctness | `refs.valid`, `claims.supported`, `fundamentos.quote_in_source` | assertions on every answer item | claim-support rate by locale |
| Web-source attribution | `citation.origin_web_distinct`; web text never shown as first-party | portfolio 2 | by topic |
| Memory correctness and privacy | `memory.consent_off_zero_calls`, `memory.isolation`, `memory.forget_complete`, `memory.no_leak_canary` | portfolio 4, pequeverso 2 (scripted multi-turn with a memory fixture) | property tests in CI always |
| Latency budgets | server overhead with a fake clock (deterministic lane); TTFE, TTFT, total in the live lane | not gated in cassettes | p50 and p95 with intervals; > 20% regression fails the live lane unless approved |
| Block contract | JSON Schema, closed enums, icon ids exist, URL allowlist | every item | n/a |

Golden size does not change (about 80 and 60): new items are reallocated from adversarial, multi-turn and the thinnest answerable duplicates, approved by two reviewer agents. The item schema gains optional `expected_tools[]`, `forbidden_tools[]`, `expected_blocks[]`, `memory_fixture`, `consent`. Memory uses an in-memory adapter implementing the same port. Cassette latency is meaningless, so the deterministic lane tests overhead only; real latency is a live-lane claim under the DR-04 caps.

## 9. Rollout

| Milestone | Work (both assistants unless noted) | Acceptance |
|---|---|---|
| M2 test scaffolding | Block and event JSON Schemas with examples (red), validator graders, item-schema extensions, memory isolation property tests against a spy port, overhead harness with a fake clock, injection fixtures | Tests exist and fail for the right reasons; golden reallocation list merged after review by two reviewer agents (assistant-quality §5.1) |
| M4 architecture | Ports (`WebSearch`, `MemoryStore`, `RetrievalCache`, `Router`, `Flags`), graph nodes of 7.1, `evidence_sufficient`, claims pipeline, parallel retrieval with deadlines (portfolio), block builder from the catalog (pequeverso keeps one structured call), all behind flags | Golden 100% on cassettes, retrieval ratchet unchanged, overhead budget green, flags default off |
| M5 UI blocks | Contract v1.x (`blocks`, `run.progress`, `capabilities`, memory GET, confirm and DELETE), consent UI, widget rendering, Store adapter; pequeverso also a feedback endpoint | Contract tests, oasdiff additive, axe 0 serious, widget acceptance, designer evaluator |
| M6 and M7 | Evals live in the cassette lane, red-team pack; release `develop` to `main` with flags off except `blocks_v2` and `progress_events` | Scorecard axes; no hotfix path (DR-08, DR-13) |
| MV live | With the provider key and owner authorization: live lane pass^3 with latency, then one flag at a time with 7-day observation, in order `progress_events`, `blocks_v2`, `semantic_cache`, `memory` (opt-in), `web_access`; pequeverso memory after legal review, `web_official_help` last | Rollback by flag |


## 10. Decisions resolved by delegation (recommended and recorded here)

- **AX-D1** TTFT targets are proposals; total-time gates stay at 6 s and 8 s until a live baseline exists.
- **AX-D2** Cards, prices, links and fundamentos quotes are built by code; prose is never parsed into facts.
- **AX-D3** Blocks are additive and header opt-in; legacy fields dual-written for one release.
- **AX-D4** Local SVG icons with closed `icon_id` enums; no remote favicons; no UTM; `sck=assistant` stays.
- **AX-D5** Portfolio web: snapshot ingestion primary, hosted search for currentness only. Pequeverso: ADR-0008 fixed fetch, off until gates pass.
- **AX-D6** Memory: opt-in, closed schema, propose-then-confirm, 60-day fixed TTL, view and forget controls; off in pequeverso until legal review.
- **AX-D7** No free-form answer cache; embedding cache, retrieval-id cache and starter replay only.
- **AX-D8** Production tracing stays in project storage; LangSmith for CI and live eval only.
- **AX-D9** Two-agent-approved promotion with owner weekly summary and veto (delegated, DR-05 style); pequeverso content-free except explicit "send this question" consent.
- **AX-D10** Golden sizes unchanged; new families reallocated within them.

## 11. Risks and unverified items

Risks: pequeverso TTFT limited by validation (measure, shorter first sentences, early progress event); semantic cache wrong neighbour (ids only, eval threshold, kill switch); memory seen as tracking (opt-in, visible controls, retention job, legal review); snapshot licensing and staleness (per-site review, owner-approved diffs, 14-day rule); web summarizer injection (no tools, allowlists, validators, fixtures); block-contract complexity (closed union, fail-closed rendering, two-release dual write); consent copy and law texts (not legal advice, DR-07).

Unverified: provider prompt-cache terms; reasoning-effort TTFT effect; hosted web-search fee; `AsyncPostgresStore` TTL sweeping; Chile and Mexico law dates; proxy idle timeout; pattern-filter effectiveness.

