# Optional official platform evidence

The owner requested bounded internet-backed shopping help on 2026-10-13. This capability is
**server-owned read-only retrieval**, not model browsing or function calling. It is disabled
by default (`OFFICIAL_HELP_ENABLED=false`) and is never created in fixture mode, even when
that flag is set. The storefront remains disabled independently; enabling a backend capability
is not authorization to deploy or activate the assistant.

## Approved sources

| Topic / source id | Fixed human citation |
| --- | --- |
| Digital delivery / `hotmart:209033897` | [Hotmart · entrega digital](https://help.hotmart.com/es/article/209033897/-como-recibire-el-producto-que-compre-en-hotmart-) |
| Refund-request procedure / `hotmart:360061973392` | [Hotmart · solicitud de reembolso](https://help.hotmart.com/es/article/360061973392/como-solicitar-el-reembolso-de-mi-compra) |
| Product questions / `hotmart:9312940657933` | [Hotmart · ayuda sobre el producto](https://help.hotmart.com/es/article/9312940657933/tenho-duvidas-referentes-ao-produto-que-comprei) |

These sources explain general platform procedures. They cannot establish Pequeverso prices,
contents, availability, guarantees, eligibility, approval, purchase state or delivery deadlines.
Merchant facts still come only from the approved storefront catalog. Neither the model nor
this reader accesses buyer accounts, order records, checkout or the refund form. External
links inside article bodies are never followed or used as navigation metadata.

## Internet boundary

Human article HTML is a client-rendered shell: HTTP 200 alone did not yield article evidence.
The official public help site's client bundle uses unauthenticated JSON GETs on
`https://api-help-center.bkf.hotmart.com/articles/{fixed_id}`. The three approved responses
were inspected on 2026-10-13, with Spanish `es-es` bodies and `outdated:false`. This public
endpoint has no located documented integration stability/SLA; treat changes as unavailability,
not permission to discover another endpoint or scrape with a browser.

The adapter only sends GET, a fixed id, `Accept:application/json`, `Accept-Language:es` and
`Accept-Encoding:identity`. It sends no user query, message, conversation, credential,
cookie, referrer, identifier or provider key. No model-selected URL or query exists.
`trust_env=false`, redirects off, verified TLS,3 s total read envelope,64 KiB body cap. Compressed
responses are refused **before** decompression; this avoids accepting compression bombs.
Status, content type, exact article id, locale, outdated flag, body and title must validate.
HTML parsing discards scripts/styles/forms/iframes/objects/SVG and remote-resource attributes.
Only a normalized complete-paragraph prefix (maximum 2000 characters per source) goes into
untrusted evidence data. A paragraph is never cut in a way that could remove a qualification;
an article without a usable complete prefix is unavailable.
Response `html_url` cannot override the fixed human citation (upstream currently uses legacy
Zendesk URLs). No copyrighted article bodies or ideal answers are committed as test fixtures.

**DNS residual:** preflight rejects empty, private, loopback, link-local, multicast, reserved
and mixed DNS answers before HTTP. HTTP resolves again, so the transport still uses trusted
DNS for this fixed official hostname and does not pin the address used for the actual connection. Do not claim DNS-rebinding prevention. vps-ops must review egress policy and
allow only this HTTPS origin; generic URL fetching is not available. No shared infra is changed
by this repository.

## Selection, cache, freshness and spend

A local deterministic selector chooses only the three topic enums from already-redacted text.
Explicit sensitive/account/action requests are excluded. Only a short referential follow-up
may inherit the last visitor topic; unrelated new questions do not. Language/payment refusals,
idempotent replay and HTTP session/CSRF/origin rejection happen before this read capability.
The external server never sees the selector's text.

The per-process cache has exactly three public topic keys, a six-hour freshness TTL and a
30-second failure cooldown. A lock coalesces concurrent reads; cancellation releases it. There
is no background refresh loop, automatic provider retry or stale-on-error fallback. Cache miss
can add up to 3 s before streaming starts. Missing/expired/invalid evidence is omitted; the
assistant continues with approved merchant evidence and must acknowledge missing facts rather
than claim that external verification succeeded. External absence is not provider downtime,
and external refresh never re-verifies the storefront price or activates a catalog version.

At most 8000 characters of serialized extra evidence are included. Exact UTF-8 request sizing
and the existing 24k byte/token upper bound and protocol margin still apply. Optional articles
use complete-paragraph prefixes that fit remaining input; their effective text hashes are
recomputed without mutating cached articles. Whole sources are omitted if no paragraph fits.
Model-context packing retains all structured resources/products and mandatory commercial
policies while pruning optional passages and old history text only when needed. Persisted
history remains intact. The existing budget reserves before the single GPT-6 Luna medium request. No hosted
search fee or extra planner/generation is added. Token usage still includes evidence input.
Verification time means when this public article was checked, not the publisher's update date.
The hash identifies normalized text actually provided, not a price/stock verification.

## Final answer and persistence

Each accepted run retains the exact immutable evidence tuple used to prepare the request.
`finalize` can resolve an external source only from that tuple, never from the global cache or
a model-authored URL. Catalog citation IDs are likewise limited to the immutable set of documents
actually included in this generation; complete structured merchant facts remain available for
validation. Catalog sources and external sources share the existing maximum 3 slots.
Source titles and URLs come from fixed server metadata; invented/unretrieved ids are dropped.

Existing price/action/outcome/URL guards apply. Regardless of optional external evidence
availability, the bounded merchant-policy guard rejects numeric guarantee windows different from the merchant's
published buyer window and positive claims of individual refund eligibility/guaranteed approval.
Explicit catalog resource page-count checks also apply to raw and normalized answer text.
These recognizers address specific failure modes, **not complete semantic entailment**. An
agent/human must still review source support, uncertainty, usefulness and every commercial
claim in real-model evaluation; citation validity alone is insufficient.

Final citations persist with the authoritative answer. History/session restore and idempotent
replay return that exact stored answer without fetching articles or generating again. Cache
refresh/expiry never mutates historical answers or shares private conversation data between
visitors. Prior source text is not promoted to newly verified evidence on a later turn.

## Compatibility, tests and activation gates

Public v1 revision 1.4 `sources[{id,title,url}]` is sufficient; no wire field, SSE stage, browser
language selector or private ops revision changes. The storefront must explicitly approve the
three fixed source URLs; do not expand its link policy to all Hotmart subdomains or paths.
Legacy ES/EN selection and stored messages stay compatible. Spanish platform evidence can
support an English explanation; no unofficial English endpoint is inferred.

Deterministic tests use synthetic article text and mocked HTTP only. They cover schema/content/
compression/redirect/size/timeout rejection, scope, coalescing, freshness/cooldown, cancellation,
source poisoning/merchant guards, actual sent-source resolution, history/replay, isolation and
request-budget degradation. Fixture tests do not establish live model quality or VPS egress.
Content-free logs use fixed `official_help` operation and verified/unavailable outcomes; no
body, URL, question or identity is logged. These logs do not add an operations dashboard metric.

Before activation: review the undocumented-source dependency and DNS/egress residual, verify
approved source URLs render safely, validate this exact image and real VPS proxy/SSE/cookies,
freeze a post-change 200+ case manifest and review the exact accumulated evaluation envelope,
run/review the real model through HTTP/SSE, and keep original results intact. Historical
2026-10-13 authorization raised the initial 400-attempt/USD 1 ledger (282 then used attempts)
to 650 attempts while retaining USD 1. That history is preserved.

On 2026-10-18 the owner explicitly authorized 1100 attempts/USD 6 **accumulated**, with the same
USD 10 monthly project limit and no reset. The current 628 attempts/860869 microUSD/zero pending
snapshot is Root's operator evidence, not a read performed by this documentation change.
The [offline audited migration](evaluation.md#explicit-audited-extension-of-one-existing-evaluation-ledger-2026-10-18)
preserves all legacy rows and 650/USD 1 metadata; constructors/default 400/USD 1 remain unchanged.
A fresh raised ledger is not allowed. Root alone executes the real migration after review and
checks; an audit hash records provenance and integrity, not cryptographic owner authorization.
The separately frozen 225-turn current-catalog phase enables these exact three server-owned
procedure sources, never hosted web search/function tools or arbitrary URLs. Default
production/fixture source access remains off. No source change here claims that a real run or
migration completed; main merges do not activate the capability/storefront or deploy the VPS.

## Timing boundary

The accepted monotonic timestamp is captured at `ChatService.start`, after route/session/origin/
CSRF admission. First-fragment and total run metrics now include optional source preparation,
and the existing 60-second run deadline includes that work rather than adding 3 seconds. These
metrics describe an API-emitted fragment, not client receipt or proxy latency. Historical
metrics/evaluation runs are not rewritten. UTC month/day for spend are computed at the actual
reservation; accepted timestamps do not reassign a cross-midnight reservation to a prior day.

A deadline before reservation refuses without a model call or ledger row. A deadline after
reservation but before scheduling the provider records no model attempt and closes the run,
while retaining its conservative `unreported` reservation: no provider usage is invented and
no presumed refund is used to lower the budget. Scheduling a provider stream can already
dispatch, so ambiguous interrupted attempts keep their reservation.

The socket evaluator accepts optional boolean manifest `official_help_enabled`. Only authorized
bounded live mode can instantiate the network reader; fixtures remain network-free even with
the flag. Actual `official_platform_data` from each ModelRequest is recorded only in private
evidence artifacts (selected id/title/text/hash/verification/scope), never whole private prompts.
Its citation gate accepts exact retrieved source metadata only; the legacy catalog URL gate
stays unchanged. Freeze the new manifest before calls, preserving baseline manifests/artifacts.


Merchant-policy recognizers run whether this optional reader is disabled, unavailable or
returns selected evidence. General platform procedures cannot change the catalog's published
buyer guarantee; their absence cannot disable that check. Narrow positive-reminder and negation
regressions retain the same bounded, nonsemantic-entailment limits described above.
