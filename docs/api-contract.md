# API contract v1 (frontend handoff)

Audience: the **native assistant of the storefront** `pequeverso` (the only public conversation
UI). The former `pequeverso-assistant-web` chat shells were removed; that repository is now the
private backoffice `pequeverso-assistant-backoffice`. Current revision: **1.3**, additive within v1
(`contract_revision` in `SessionOut` and `contracts/manifest.json`). Revision **1.1** added: `starters`, `locale`, `language`, notice `language_unsupported`,
and the private operations API. Revision **1.2** adds `pricing` (the rate source used for
estimates) and `recent` (up to 50 latest runs with opaque ids) to the private ops summary only;
the browser response contract is unchanged from1.1. Revision **1.3** adds optional nested
`context` navigation/presentation hints to `MessageIn`; existing1.0–1.2 clients work unchanged,
and the private ops schema is unchanged from1.2.
Pinned artifacts: `contracts/openapi.json`, `contracts/sse.schema.json`, `contracts/examples/*`,
hashed in `contracts/manifest.json` (`contract_version: "1"`). They are generated from the code
(`uv run python -m contracts.export`) and CI fails if they drift. Consume them from an exact
commit of this repository, never from a working tree.

## Topology and path prefix

Proposed (pending DNS and vps-ops approval): the API is served at its own HTTPS origin,
`https://assistant.pequeverso.com/api/*`, through the vps-ops reverse proxy. The storefront
(`https://pequeverso.com`, static) calls it **cross-origin** with `fetch(..., {credentials:
'include'})`. See docs/deployment-contract.md ("Browser and origin assumptions") for CORS,
cookies and CSRF.

- The API's routes **include** the `/api` prefix (`/api/v1/...`) and FastAPI's `root_path` is empty.
  The proxy forwards `/api/*` **unchanged**: no prefix stripping, no rewriting, no `/api/api`.
- `/health/*` and `/internal/*` are internal (container, proxy and backoffice) and must not be
  routed publicly.

## Sessions and ownership

| Step | Request | Result |
|---|---|---|
| Open | `POST /api/v1/session`, `Content-Type: application/json`, body `{}` or `{"locale": "es" \| "en"}` | `201` created or `200` restored: `SessionOut` (`csrf_token`, `expires_at`, `created`, `messages` history, `availability`, `limits`, `starters`, `contract_revision`) |
| Ask | `POST /api/v1/messages` + `X-CSRF-Token` + `Idempotency-Key` | `text/event-stream` (below) |
| Cancel | `POST /api/v1/runs/{run_id}/cancel` + `X-CSRF-Token` | `202`; `404 run_not_found` if not active in this session |
| Delete | `DELETE /api/v1/session` + `X-CSRF-Token` | `204`; the session, its messages and runs are deleted and the cookie cleared |
| Availability | `GET /api/v1/availability` (no session) | `{status: available \| unavailable, reason?}` |

- The session credential is an opaque random secret in a **host-only, HttpOnly, SameSite=Lax**
  cookie (`__Host-pv_assistant`, `Secure`, `Path=/` in production; `pv_assistant_dev` locally).
  It is stored server-side only as a SHA-256 digest. It never appears in a URL, a response
  body or a log.
- The CSRF token comes in the `POST /session` body. Keep it **in memory only**. On a reload, call
  `POST /session` again: the same session is restored with its token and history.
- Every mutation requires an allowlisted `Origin` (`ALLOWED_ORIGINS`, normally just
  `https://assistant.pequeverso.com`), `Content-Type: application/json` where there is a body,
  and the CSRF token. Same-origin deployment does not remove these checks.
- Retention is 24 h sliding (each open and each question extends it). Expired sessions are purged
  every 10 minutes; a request with an expired cookie gets `401 session_expired`, and the client
  should open a new session.
- **Continuity.** The storefront keeps the assistant mounted in its root layout, so minimizing,
  reopening and navigating between store pages reuse the in-memory token. A full page load calls
  `POST /session` again and the cookie restores the same history. Transfer across devices or
  browsers is **not implemented**. Storefront and API are same-site (`pequeverso.com` /
  `assistant.pequeverso.com`), so the host-only Lax cookie is sent on credentialed requests.
  Using the API from an unrelated site is unsupported: do not switch to Domain cookies or
  `SameSite=None`.

## Asking and streaming

Request body: `{"content": "<1..600 chars>", "page": "home" | "product" | "support" | null,
"locale": "es" | "en" | null, "context": {"opened_path": "/grafismo-fonetico/",
"current_path": "/soporte/", "presentation": "compact" | "expanded" | "page"} | null}`. `page` is optional context from the storefront route (a fixed
enum; never free text). `locale` is the interface language: a preference, not an order.
The default application limit is 600 characters (`MAX_MESSAGE_CHARS`, configurable within
50–2000). The wire schema permits up to 2000; exceeding the configured application limit
returns `422 invalid_request` before any model call.

**Navigation hints (1.3).** `context` and every member are optional/null. `opened_path` is the
public route captured when the panel opened; `current_path` is the allowlisted pathname at send
time; `presentation` is a UI hint (`compact`, `expanded` or `page`). It is an untrusted hint, not a theme, route
command or catalog fact. The composer places these values only in the `visitor_turn` JSON data,
never the system prompt or catalog evidence. Paths are not stored as message/run fields or logged;
only the existing idempotency digest incorporates nonempty context. Omitted, null and empty
context retain the exact legacy request hash. Different hints on the same idempotency key cause
`409 idempotency_conflict`; trailing-slash aliases canonicalize to the same digest.

Known routes, reviewed from storefront commit `25aa9ce22a0652375f0554576b88f24f83b65b88`:
`/`, `/grafismo-fonetico/`, `/soporte/`, `/arrepentimiento/`, `/aviso-legal/`,
`/compras-y-reembolsos/`, `/cookies/`, `/privacidad/`, `/terminos/`. Non-root paths also accept
an alias without the final slash. UI locales use these same routes; no `/en/` route is invented.
The offer and thank-you paths are excluded. Query strings, fragments, absolute URLs, percent
encoding, traversal, unknown keys (including `theme`), HTML and identifying data are rejected
with the existing `422 invalid_request` before any model call. Context does not authorize showing
the assistant on an otherwise ineligible page or introducing commercial facts.

**Languages (1.1).** The server decides the answer language in code: the visitor's own words
(quoted text, code, URLs and product names removed) decide between Spanish and English; when
they do not, the conversation's last answer language wins, then `locale`, then Spanish. A
message in another language gets a fixed bilingual note (notice `language_unsupported`) without
a model call. `MessageOut.language` says which language `content` is in: set it as the `lang`
attribute of the rendered message. Product and resource names stay in Spanish; the material is
in Spanish.

**Starters (1.1).** `SessionOut.starters` holds up to four opening questions in the requested
locale, built from approved catalog topics (the storefront FAQ). Show them only before the first
message; sending one is an ordinary question.
`Idempotency-Key` is 8–128 of `[A-Za-z0-9_-]`, one new key per user attempt. Retrying the same key
with the same body replays a completed answer without a new model call (`run.started.user_message`
is `null` on a replay). Reusing it with a different body, or after a failed or cancelled run,
returns `409 idempotency_conflict`.

SSE framing: `id: <sequence>`, `event: <type>`, `data: <json>`, blank line. `: keep-alive` comments
arrive every 15 s of silence and carry no sequence. The response header `X-Run-ID` names the run.

```
run.started        {user_message: Message | null}
message.delta*     {text}                         provisional; append to a draft
message.completed  {message: Message}             authoritative; REPLACE the draft with message.content
run.completed                                     terminal
run.failed         {code, retryable}              terminal (instead of completed)
run.cancelled                                     terminal (instead of completed)
```

Every stream ends with exactly one terminal event. Every event carries `schema_version: "1"`,
`run_id`, a 0-based strictly increasing `sequence` and a `timestamp`. The final content can
differ from the streamed draft: when the server-side answer rules replace an answer, the notice
`answer_replaced` is set. Always render `message.completed.message.content`.

**Interruption.** If the connection drops before a terminal event, the client cannot know
whether the answer was stored: a drop after the server finished leaves a completed run, a drop
earlier cancels the upstream model call. The client shows "interrupted" and offers an explicit
retry (never automatic). Recommended retry (what the storefront does): resend the **same**
Idempotency-Key and body first. A completed run replays its stored answer with no model call or
cost; a cancelled or failed run returns `409 idempotency_conflict`, and the client then retries
once with a **new** key; a run still active returns `409 run_in_progress`. After a failure or a
user stop, retry with a new key. **Stop button:** abort the fetch
*and* `POST /runs/{run_id}/cancel`; either alone is enough server-side, and both cover proxies
that hide disconnects. One run at a time per session: a second question while one is active
gets `409 run_in_progress`.

## Message payload (`MessageOut`)

`content` is plain text: it may contain `**bold**` and lines starting with `- `, nothing else.
Render it as text. The server strips markup-like tags, but the client must not interpret HTML or
Markdown links either. The text is useful on its own; every other field is optional enrichment:

| Field | Contents | Guarantee |
|---|---|---|
| `products[]` | `id` (storefront slug), `name`, `summary`, `age_range`, `url`, `purchase_url`, `image{url,width,height,alt}`, `price` | Every id was resolved against the active catalog server-side; invented ids are dropped. URLs are absolute `https://pequeverso.com/...` from the catalog, never from model text |
| `resources[]` | `id` (`<product>/<resource>`), `product_id`, `title`, `pages`, `description`, `image` | Same validation; at most 3 |
| `links[]` | `id`, `label`, `url` (support, purchases/refunds, withdrawal, Hotmart buyer area/refund form, product page) | From the catalog allowlist only; at most 3 |
| `sources[]` | `id`, `title`, `url` of the FAQ/policy entries the answer relied on | Resolved against catalog documents; at most 3 |
| `follow_ups[]` | Up to 3 short suggested questions | Plain text, validated by the same answer rules |
| `notices[]` | `answer_replaced`, `payment_data_refused`, `contact_data_redacted`, `language_unsupported` (1.1) | Explain server interventions |
| `language` | `es` \| `en` (1.1; absent in 1.0 means `es`) | Language of `content` |

**Actions are constrained to two kinds.** An *ask* action sends a `follow_ups` string as a new
question. An *open* action is a plain link to a validated `url` (`purchase_url`, product `url`,
`links[].url`, `sources[].url`) that the visitor activates; the client never navigates on its
own. Links to the storefront itself may open in the same tab; external hosts (Hotmart help)
open in a new tab with `rel="noopener noreferrer"`. The assistant never
adds to a cart, pays, cancels, refunds or changes accounts. `purchase_url` points to the storefront
buy section (`/grafismo-fonetico/#comprar`); checkout stays in the store's Hotmart flow.

## Freshness of commercial data

| Fact | Source | Policy |
|---|---|---|
| Price | Storefront registry at a pinned `main` commit (`catalog/catalog.v1.json`, `source.revision`) | Quoted only while the snapshot's verification time is within `CATALOG_PRICE_MAX_AGE_HOURS` (default 168 h). For the bundled snapshot this is its export time; for a future live `CATALOG_URL`, the last successful fetch. Otherwise `price` is `null`, the model is told not to state amounts, and any amount it writes causes replacement. `price.verified_at` is always present with a price |
| Availability / stock | Not applicable: a digital product with no stock | The assistant never claims scarcity or stock |
| Promotions / discounts | None in the catalog | Never offered; discount or coupon claims cause replacement |
| Currency | Reference USD; Hotmart converts and shows the final total | Show `price.note` next to any price |

## Errors

Non-stream errors are JSON `{"error": {code, message, retryable, request_id}}`. `message` is
English, for developers; localize from `code`. Every code is listed in
`contracts/examples/errors.json`.

| Status | Codes |
|---|---|
| 401 | `session_expired` → reopen the session |
| 403 | `origin_denied`, `csrf_failed` |
| 404 | `run_not_found`, `not_found` |
| 409 | `run_in_progress`, `idempotency_conflict` |
| 422 | `invalid_request` (validation, content type, body > 16 KiB) |
| 429 | `rate_limited` (+ `Retry-After`) |
| 502/503/504 | `generation_failed`, `budget_exhausted` (+ `Retry-After`), `assistant_disabled`, `catalog_unavailable`, `provider_unavailable`, `busy` (+ `Retry-After: 5`), `dependency_unavailable`, `timeout` |

In-stream `run.failed.code` ∈ `budget_exhausted | provider_unavailable | generation_failed |
timeout | catalog_unavailable | busy`.

**Budget exhaustion and unavailability.** Check `availability` (in `SessionOut` or
`GET /availability`) before showing the composer. When it is unavailable, show a calm message
with the store's own support route (`https://pequeverso.com/soporte/`). The storefront works
without the assistant; nothing in the purchase flow depends on it.

## Private operations API (backoffice only)

`GET /internal/v1/ops/summary` with `Authorization: Bearer <OPS_READ_TOKEN>`; schema
`contracts/ops.schema.json`, example `contracts/examples/ops.summary.json`. Not part of the
browser contract and never routed publicly. Money is decimal strings in USD. Spend is split
into **confirmed** (settled to provider-reported usage), **estimated** (the run ended without a
usage report, so its worst-case reservation stays counted) and **pending** (runs in progress).
Latency: `first_delta` = request accepted → first answer text; `total` = request accepted →
authoritative answer, both for runs that called the model. `daily` lists only days with records
and `metrics_since` says when recording began: earlier periods are unknown, not zero.
`service.synthetic` is true in fixture mode, where every number comes from simulated answers.
`pricing.revision` names the price list the estimates use (they are not the provider invoice;
reconcile with the OpenAI project's usage page). `recent[].id` is a digest of the run id and
cannot be used against the public API.

## Compatibility rules

Within v1, fields may be added and new optional notices or error codes may appear; clients must
ignore unknown fields and treat unknown codes as generic failures. Removing or renaming a field,
changing an event's meaning or the terminal grammar requires v2 under `/api/v2`.
