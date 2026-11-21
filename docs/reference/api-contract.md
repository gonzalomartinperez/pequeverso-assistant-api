# API contract v1 (frontend handoff)

Audience: the **native assistant of the storefront** `pequeverso` (the only public conversation
UI). The former `pequeverso-assistant-web` chat shells were removed; that repository is now the
private backoffice `pequeverso-backoffice` (previously `pequeverso-assistant-backoffice`). Current revision: **1.6**, additive within v1
(`contract_revision` in `SessionOut` and `contracts/manifest.json`). Revision **1.1** added: `starters`, `locale`, `language`, notice `language_unsupported`,
and the private operations API. Revision **1.2** adds `pricing` (the rate source used for
estimates) and `recent` (up to 50 latest runs with opaque ids) to the private ops summary only;
the browser response contract is unchanged from1.1. Revision **1.3** adds optional nested
`context` navigation/presentation hints to `MessageIn`; existing1.0–1.2 clients work unchanged,
and the private ops schema is unchanged from1.2.
Revision **1.4** adds optional `MessageIn.response_language: "es" | null` for the Spanish-native
storefront. Omitted/null preserves the legacy ES/EN selection and exact request fingerprint;
neither the response language enum nor existing English history is removed.
Revision **1.5** adds optional `ProductOut.kind: "core" | "affiliate"` (default `core`),
`format: string | null` and `disclosure: string | null` (both default null). Existing messages
and clients remain valid. Product price was already nullable; an affiliate price stays null
because the source does not publish it. Summary also carries the disclosure so older clients
can preserve the relationship. No request fields, routes or private ops schemas change.

Revision **1.6** documents `POST /api/v1/analytics/events` in `contracts/openapi.json` and
exports health and private operations in `contracts/openapi.internal.json`. The ingest
request example is `contracts/examples/product-analytics.event.json`. Existing wire
behavior stays the same apart from the advertised revision.

Pinned artifacts: `contracts/openapi.json`, `contracts/openapi.internal.json`,
`contracts/sse.schema.json`, `contracts/examples/*`,
hashed in `contracts/manifest.json` (`contract_version: "1"`). They are generated from the code
(`uv run python -m contracts.export`) and CI fails if they drift. Consume them from an exact
commit of this repository, never from a working tree.

## Topology and path prefix

Proposed (pending DNS and vps-ops approval): the API is served at its own HTTPS origin,
`https://assistant.pequeverso.com/api/*`, through the vps-ops reverse proxy. The storefront
(`https://pequeverso.com`, static) calls it **cross-origin** with `fetch(..., {credentials:
'include'})`. See docs/reference/deployment-contract.md ("Browser and origin assumptions") for CORS,
cookies and CSRF.

- The API's routes **include** the `/api` prefix (`/api/v1/...`) and FastAPI's `root_path` is empty.
  The proxy forwards `/api/*` **unchanged**: no prefix stripping, no rewriting, no `/api/api`.
- `/health/*`, `/healthz`, `/readyz` and `/internal/*` are internal (container, proxy and
  backoffice) and must not be routed publicly.

## Operations

The [public OpenAPI document](../../contracts/openapi.json) defines these operations. Send
`https://pequeverso.com` as the `Origin` for storefront mutations where it is allowlisted.

### `GET /api/v1/availability`

This check requires no headers. An unavailable assistant normally still returns `200 OK`
with `status: "unavailable"`.

<!-- example: GET /api/v1/availability response 200 -->
```json
{
  "status": "available",
  "reason": null
}
```

An unexpected dependency failure can return `503 Service Unavailable`.

<!-- example: GET /api/v1/availability response 503 -->
```json
{
  "error": {
    "code": "dependency_unavailable",
    "message": "A dependency is unavailable.",
    "retryable": true,
    "request_id": "req_EXAMPLE"
  }
}
```

### `POST /api/v1/session`

Send an allowlisted `Origin` and `Content-Type: application/json`. Include the session cookie
to restore a conversation. The response is `201 Created` for a new session or `200 OK` for a
restored session. The response can carry `Set-Cookie`.

<!-- example: POST /api/v1/session request -->
```json
{
  "locale": "es"
}
```

The `201 Created` response has this body.

<!-- example: POST /api/v1/session response 201 -->
[New session response](../../contracts/examples/session.created.json)

An invalid request body returns `422 Unprocessable Content`.

<!-- example: POST /api/v1/session response 422 -->
```json
{
  "error": {
    "code": "invalid_request",
    "message": "The request is invalid.",
    "retryable": false,
    "request_id": "req_EXAMPLE"
  }
}
```

### `DELETE /api/v1/session`

Send an allowlisted `Origin`, the session cookie and its `X-CSRF-Token`. The response
is `204 No Content` with an empty body and a `Set-Cookie` header that clears the cookie.
A missing or invalid session returns `401 Unauthorized`.

<!-- example: DELETE /api/v1/session response 401 -->
```json
{
  "error": {
    "code": "session_expired",
    "message": "No active session; open a new one.",
    "retryable": false,
    "request_id": "req_EXAMPLE"
  }
}
```

### `POST /api/v1/messages`

Send an allowlisted `Origin`, `Content-Type: application/json`, the session cookie,
`X-CSRF-Token` and `Idempotency-Key`.

<!-- example: POST /api/v1/messages request -->
```json
{
  "content": "Mi hija tiene 4 años y recién empieza con las letras, ¿qué me recomiendas?",
  "response_language": "es"
}
```

`200 OK` returns `text/event-stream` and an `X-Run-ID` header. The opening event below is
from the [complete recommendation stream](../../contracts/examples/stream.recommendation.sse).

<!-- example: POST /api/v1/messages response 200 -->
```sse
id: 0
event: run.started
data: {"schema_version":"1","run_id":"run_EXAMPLE0000001","sequence":0,"timestamp":"2026-09-28T15:00:00Z","type":"run.started","user_message":{"id":"msg_EXAMPLEuser00001","role":"user","content":"Mi hija tiene 4 años y recién empieza con las letras, ¿qué me recomiendas?","created_at":"2026-09-28T15:00:00Z","products":[],"resources":[],"links":[],"sources":[],"follow_ups":[],"notices":[],"language":"es"}}
```

Before streaming starts, reusing a key with a different body returns `409 Conflict`.

<!-- example: POST /api/v1/messages response 409 -->
```json
{
  "error": {
    "code": "idempotency_conflict",
    "message": "This Idempotency-Key was already used for a different or failed request.",
    "retryable": false,
    "request_id": "req_EXAMPLE"
  }
}
```

### `POST /api/v1/runs/{run_id}/cancel`

Send an allowlisted `Origin`, the session cookie and its `X-CSRF-Token`. Use the
`X-Run-ID` from the message response as `run_id`. The route returns `202 Accepted` with
an empty body. A missing or invalid CSRF token on a valid session returns `403 Forbidden`.

<!-- example: POST /api/v1/runs/{run_id}/cancel response 403 -->
```json
{
  "error": {
    "code": "csrf_failed",
    "message": "Missing or invalid CSRF token.",
    "retryable": false,
    "request_id": "req_EXAMPLE"
  }
}
```

### `POST /api/v1/analytics/events`

Send exactly one allowlisted `Origin` and `Content-Type: application/json` (optional
`charset=utf-8`). Omit `Cookie` and `Authorization`. The ingest accepts one UTF-8 event
up to 1024 bytes and returns `204 No Content` with an empty body.

<!-- example: POST /api/v1/analytics/events request -->
[Public click event request](../../contracts/examples/product-analytics.event.json)

An origin rejected by the shared middleware returns this `403 Forbidden` body.
When the ingest handler rejects supplied credentials, its `403` body is empty.

<!-- example: POST /api/v1/analytics/events response 403 -->
```json
{
  "error": {
    "code": "origin_denied",
    "message": "Origin not allowed.",
    "retryable": false,
    "request_id": "req_EXAMPLE"
  }
}
```

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
- The CSRF token comes in the `POST /session` response body. Keep it **in memory only**. On a
  reload, call `POST /session` again: the same session is restored with its token and history.
- Session mutations require an allowlisted `Origin` (`ALLOWED_ORIGINS`, normally
  `https://pequeverso.com`) and `Content-Type: application/json` where there is a body.
  Asking, canceling a run and deleting a session also require the session cookie and CSRF token.
  These checks also apply in a same-origin deployment.
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
"locale": "es" | "en" | null, "response_language": "es" | null,
"context": {"opened_path": "/grafismo-fonetico/",
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

**Spanish-native responses (1.4).** The native storefront always sends `response_language:
"es"`, opens its session with `locale: "es"` and offers no language selector. With this policy,
ordinary questions written in English may be answered in Spanish; neither an English locale
hint nor prior English replies overrides the selected Spanish language. Recognized explicit
requests for another reply language, including English, get a short Spanish-only
`language_unsupported` notice without a provider call or spend reservation. Quoted text,
negated requests and questions about the material's language do not request another reply
language. The recognizer is finite; it is not universal semantic language detection.

The optional policy is included in the idempotency digest only when it is `"es"`: adding or
removing it on an existing key yields `409 idempotency_conflict`, preventing replay of an old
English response as a new Spanish-native generation. Omitted/null keeps the exact legacy
digest, including existing context rules. Other values such as `"en"` are rejected with
`422 invalid_request` before generation. Historical English messages remain unchanged and
must retain their original `lang` attribute. Clients that omit the field keep the legacy
selection/bilingual notice above; this is not a global Spanish-only restriction on v1 clients.

The server selects Spanish in the model request and response metadata. Neither that metadata
nor final grounding validates the actual prose language of every provider sentence; provisional
SSE text is still provisional. Real-model language/quality review remains an activation gate.
Require backend contract revision at least1.4 before enabling this native policy. This additive
field authorizes no storefront activation or deployment.

**Starters (1.1).** `SessionOut.starters` holds up to four opening questions in the requested
locale, built from approved catalog topics (the storefront FAQ). Show them only before the first
message; sending one is an ordinary question.
`Idempotency-Key` is 8–128 of `[A-Za-z0-9_-]`, one new key per user attempt. Retrying the same key
with the same body replays a completed answer without a new model call (`run.started.user_message`
is `null` on a replay). Reusing it with a different body, or after a failed or cancelled run,
returns `409 idempotency_conflict`.

SSE framing: `id: <sequence>`, `event: <type>`, `data: <json>`, blank line. `: keep-alive` comments
arrive every 15 s of silence and carry no sequence. The response header `X-Run-ID` names the run.

```text
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
`answer_replaced` is set. Always render `message.completed.message.content`. Deltas contain
checked cumulative sentence/paragraph prefixes, not raw provider token fragments. Checks are
bounded deterministic recognizers, not complete semantic verification. A later rejected
sentence can still cause replacement of an earlier valid prefix; some answers have no delta.
The remaining text is sent only after complete canonical validation, with known usage retained
if the visitor disconnects. These presentation changes do not change v1 revision1.4.

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

`content` is plain text: it may contain `**bold**` and lines starting with `-`, nothing else.
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

## Errors and RFC 9457

The v1 JSON error envelope stays `{"error": {code, message, retryable, request_id}}` with
`Content-Type: application/json`. `message` is English for developers. Localize from `code`
and reopen the session on `session_expired`. The RFC 9457 member mapping and HTTP status
table are in [ADR-0013](../decisions/ADR-0013-v1-error-envelope-and-rfc-9457-mapping.md).
See the [public error envelope examples](../../contracts/examples/errors.json).

Session API validation, content-type checks and bodies exceeding the configured limit
(16 KiB by default) can produce `422 invalid_request`.

In-stream `run.failed.code` ∈ `budget_exhausted | provider_unavailable | generation_failed |
timeout | catalog_unavailable | busy`.

**Budget exhaustion and unavailability.** Check `availability` (in `SessionOut` or
`GET /availability`) before showing the composer. When it is unavailable, show a calm message
with the store's own support route (`https://pequeverso.com/soporte/`). The storefront works
without the assistant; nothing in the purchase flow depends on it.

## Private operations

The [private OpenAPI document](../../contracts/openapi.internal.json) covers container probes
and the backoffice operations API. Keep these routes off the public proxy. Health probes
require no headers. The operations routes require `Authorization: Bearer <OPS_READ_TOKEN>`.

### `GET /health/live`

`200 OK` reports process liveness. The probe defines only a success response.

<!-- example: GET /health/live response 200 -->
```json
{
  "status": "ok"
}
```

### `GET /health/ready`

`200 OK` reports readiness. `503 Service Unavailable` reports an unready service.
The catalog field appears when a catalog is active.

<!-- example: GET /health/ready response 200 -->
```json
{
  "status": "ready",
  "catalog": {
    "revision": "7dde2968783c",
    "price_status": "verified"
  }
}
```

<!-- example: GET /health/ready response 503 -->
```json
{
  "status": "not_ready"
}
```

### `GET /healthz`

`200 OK` reports process liveness and the build version. The probe defines only a success
response.

<!-- example: GET /healthz response 200 -->
```json
{
  "status": "ok",
  "version": "abc1234"
}
```

### `GET /readyz`

`200 OK` and `503 Service Unavailable` report the same readiness checks as `/health/ready`
and include the build version and storage schema level.

<!-- example: GET /readyz response 200 -->
```json
{
  "status": "ready",
  "catalog": {
    "revision": "7dde2968783c",
    "price_status": "verified"
  },
  "version": "abc1234",
  "schema_version": "sqlite-002"
}
```

<!-- example: GET /readyz response 503 -->
```json
{
  "status": "not_ready",
  "version": "abc1234",
  "schema_version": "sqlite-002"
}
```

### `GET /internal/v1/ops/summary`

`200 OK` returns a summary using the [standalone ops schema](../../contracts/ops.schema.json).

<!-- example: GET /internal/v1/ops/summary response 200 -->
[Operations summary response](../../contracts/examples/ops.summary.json)

A missing or invalid token returns `401 Unauthorized` with `WWW-Authenticate: Bearer`.

<!-- example: GET /internal/v1/ops/summary response 401 -->
```json
{
  "error": {
    "code": "unauthorized",
    "message": "Missing or invalid operations token.",
    "retryable": false,
    "request_id": "req_EXAMPLE"
  }
}
```

Money is decimal strings in USD. Spend is split into **confirmed** (settled to provider-reported
usage), **estimated** (the run ended without a usage report, so its worst-case reservation stays
counted) and **pending** (runs in progress).
Latency: `first_delta` = request accepted → first answer text; `total` = request accepted →
authoritative answer, both for runs that called the model. `daily` lists only days with records
and `metrics_since` says when recording began: earlier periods are unknown, not zero.
`service.synthetic` is true in fixture mode, where every number comes from simulated answers.
`pricing.revision` names the price list the estimates use (they are not the provider invoice;
reconcile with the OpenAI project's usage page). `recent[].id` is a digest of the run id and
cannot be used against the public API.

### `GET /internal/v1/ops/telemetry`

With observability enabled, `200 OK` returns a runtime telemetry snapshot.

<!-- example: GET /internal/v1/ops/telemetry response 200 -->
[Runtime telemetry response](../../contracts/examples/ops.telemetry.json)

A missing or invalid token returns `401 Unauthorized` with `WWW-Authenticate: Bearer`.

<!-- example: GET /internal/v1/ops/telemetry response 401 -->
```json
{
  "error": {
    "code": "unauthorized",
    "message": "Missing or invalid operations token.",
    "retryable": false,
    "request_id": "req_EXAMPLE"
  }
}
```

### `GET /internal/v1/ops/metrics`

With observability enabled, `200 OK` returns Prometheus exposition text. A sample follows.

<!-- example: GET /internal/v1/ops/metrics response 200 -->
```text
# HELP pequeverso_process_uptime_seconds Current process uptime, not historical availability.
# TYPE pequeverso_process_uptime_seconds gauge
pequeverso_process_uptime_seconds 12.5
```

A missing or invalid token returns `401 Unauthorized` with `WWW-Authenticate: Bearer`.

<!-- example: GET /internal/v1/ops/metrics response 401 -->
```json
{
  "error": {
    "code": "unauthorized",
    "message": "Missing or invalid operations token.",
    "retryable": false,
    "request_id": "req_EXAMPLE"
  }
}
```

### `GET /internal/v1/ops/product-analytics`

With product analytics enabled, `200 OK` returns a report. This example uses
`?period=day&route=/&section_id=hero`.

<!-- example: GET /internal/v1/ops/product-analytics response 200 -->
[Product analytics report fixture](../../contracts/examples/product-analytics.json#/report)

The JSON response body is the example file's `report` object. A missing or invalid token
returns `401 Unauthorized` with an empty body.

## Compatibility rules

Within v1, fields may be added and new optional notices or error codes may appear; clients must
ignore unknown fields and treat unknown codes as generic failures. Removing or renaming a field,
changing an event's meaning or the terminal grammar requires v2 under `/api/v2`.

## Optional official platform evidence (2026-10-13)

Optional [official platform evidence](../explanation/official-web-evidence.md) can populate the existing
`sources[{id,title,url}]` fields with the three server-owned `hotmart:<article_id>` references.
Only a source actually supplied for that turn can resolve. Their scope is general platform
procedures, not merchant price/policy verification or order access. No wire revision or new
SSE stage is introduced. Stored citations/history/replays remain immutable after cache expiry.

## Independent local site-analytics fixture contract

The owner-authorized default-OFF channel has its own Peque input profile and private report,
`schema_version: 1`, documented in [product-analytics.md](product-analytics.md). It does not change
chat v1, SSE, ops1.2 or telemetry1.0, and its explicit schemas are independent of the existing
public OpenAPI document. No Store producer or production collection is enabled by these artifacts.
