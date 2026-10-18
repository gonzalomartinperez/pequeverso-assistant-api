# Local product analytics fixture channel · schema1

This independent channel counts received page views, section views and primary-pointer public
clicks. It is not operational telemetry, assistant quality, unique people, purchases, advertising
attribution, reading, attention or permission to collect production traffic. No Store collector,
Meta/CAPI, checkout, advertising consent or existing storefront behavior changes here.

Both API collection/read and BO read default OFF. `PRODUCT_ANALYTICS_ENABLED=true` is accepted only
with a nonproduction environment, fixture AI provider and existing PostgreSQL application storage.
There are no model calls in this feature. `PRODUCT_ANALYTICS_COUNTRY_ENABLED=true` is refused;
country stays unknown and no client country, IP or proxy header is interpreted. The server labels
every report `synthetic: true`; callers cannot submit that classification.

## Profile and public input

The reviewed reference is Store commit `88d6d0add414261e5ccf5bd3e2b21285e1a33179`, not a deployed-source
or current-main freshness claim. Layout `pequeverso-v1` permits only Spanish, routes `/` and
`/grafismo-fonetico/` and these exact DOM anchor pairs (the wire uses IDs without `#`):

| Route | Approved sections |
| --- | --- |
| `/` | `hero`, `leer`, `bebe`, `preguntas` |
| `/grafismo-fonetico/` | `hero`, `incluye`, `metodo`, `preguntas` |

The home reading/feeding IDs come from `content/es/hub.ts` and their chapter components. Product
IDs come from `src/features/landing/CoreLanding.tsx`. Auth, forms, assistant transcripts, affiliate
redirects, offers, thanks and checkout surfaces are excluded. Viewport CSS-pixel buckets are
mobile below768, tablet768–1023 and desktop at least1024. No route, layout or section may silently
change meaning under the same revision.

`POST /api/v1/analytics/events` returns204 for accepted and duplicate deliveries. OFF returns404
without analytics reads/writes. The separate closed input profile is
`contracts/site-experience-pequeverso-v1.schema.json`; it is not Portfolio ingestion schema2 and
not an extension of the chat payload. Public input requires exactly one configured Origin and
JSON content type, forbids Cookie/Authorization association, and has an actual streamed1KiB limit
and10s deadline including database work. Unknown/duplicate fields, raw text, URLs, timestamps,
country, arbitrary properties and visitor/session/run IDs are rejected without echoing payloads.

A UUIDv4 identifies one delivery only. Its SHA256 digest, never the raw UUID, is retained for24h;
this is dedupe, not anonymity or an identity profile. No retry or persistent event queue is
provided. A received event cannot prove navigation completion or a person. Limits are global
60new events/minute and10000/day, checked with duplicate delivery and count updates in one
advisory-locked transaction. Duplicate IDs do not increment counts. A failed quota transaction
commits none of its mutations. No IP/session key is used to enforce these limits.

`page_view` means one committed route visit, not prefetch/remount/theme update. `section_view`
requires a reviewed visible section at least50% for500ms continuously; hide/unmount/departure
cancels dwell. `public_click` is a primary pointer only and requires integer `cell_x`, `cell_y`
within0..7. Keyboard activation is not collected by this finite profile and never fabricates
coordinates. Other events forbid coordinates, including explicitnull. Optional interest,
affiliate, checkout, purchases and revenue are not admitted.

## Private report

`GET /internal/v1/ops/product-analytics` is a separate schema1 contract using existing server-only
`OPS_READ_TOKEN` bearer authentication, constant-time digest comparison and no-store responses.
It is excluded from public OpenAPI/proxy routing; the independent public profile is distributed
as an explicit schema too. Existing ops1.2, telemetry1.0, chat/OpenAPI/SSE payloads remain unchanged.
Missing API flag/service/token returns404; configured but invalid/missing bearer returns401.

Only `period=day|week|month`, `offset=0|1|2`, `route=all|/|/grafismo-fonetico/`, `section_id`,
`viewport_bucket=all|mobile|tablet|desktop`, and `locale=es` are allowed. Unknown/duplicate query
fields and impossible route/section pairs fail before storage. Every filter uniformly applies to
totals, daily rows, countries, observation interval and grid. Calendar bounds are half-open UTC;
weeks start ISO Monday, actual month/leap/year transitions apply, and the current window is partial.
Daily rows contain observed days only; absence does not prove historical collection coverage.

`generated_at` is the snapshot's logical receipt watermark: the later of the captured request
clock and the latest matching receipt inside the selected window. This admits a concurrent
committed event or an already recorded event after a clock rollback without changing calendar
bounds, counts or observation timestamps. Historical/empty reports retain the request clock.
Observations outside the selected window remain invalid; this is not a database-read completion
time or a promise that every concurrent event was included.

Report fields and synthetic example are committed in `contracts/product-analytics.schema.json`
and `contracts/examples/product-analytics.json`. The example wrapper `fixture/scope/report` is
metadata; GET returns only the inner report. Counts represent `received_events_only`; first/last
receipt timestamps belong to matching events in the selected window, not invented enabled-at dates.
Countries sum all three event counts: zero gives an emptylist,1–2 withheld, at least3 unknown;
there are no actual ISO-country buckets. This does not make small reports anonymous.

A grid is available only for an exact route and section, avoiding blended unrelated surfaces.
Each visible8×8 cell contains at least3 clicks. `visible_clicks + withheld_clicks + unselected_clicks`
reconciles exactly to filtered publicclicks. For an unselected grid, cells are empty and all clicks
are `unselected_clicks`, not withheld/keyboard events. Tables and coverage labels must accompany
BO graphics; OFF/unavailable/invalid/empty states are distinct and fixtures visibly synthetic.
BO authenticates its current actor before any read and keeps the bearer out of browser data/logs.

## PostgreSQL ownership, retention and rollback

Use the existing API private pool/project database, never BO IAM or public knowledge. The explicit
offline migrator adds `005_product_analytics.sql`; runtime never executes DDL. A feature-specific
schema marker binds migration1 to SHA256 of these exact migration bytes. Re-running a changed
migration or starting analytics against a missing/wrong marker fails closed. This is a new,
feature-scoped checksum, not a claim that older Peque migrations have a checksum registry.

Only `pequeverso_private_runtime` receives exact new table rights; knowledge/indexer/embedding
capabilities receive none. The schema marker is SELECT-only for runtime. Existing four LOGINs,
INHERIT semantics and conversation/accounting policies remain intact. Sharing the existing private
runtime login does not provide isolation from a compromised login that already has conversation
rights; this feature repository itself accesses only analytics tables and does not join identities.

Dedupe lasts24h and daily aggregates retain current UTC day plus92previous days. At most1000expired
rows/table are pruned per accepted/duplicate operation; expiry filtering is still authoritative
while a bounded backlog drains. Statement and lock timeouts bound operations. No raw events,
coordinates beyond integer cells, answers, cookie, IP, UA or referrer are persisted. Expiry does
not claim erasure from backups. A future incompatible image is not a DDL rollback: preserve
migrations, rehearse forward-compatible readers or a logical restore before a rollback decision.
Do not remove schema/data to make an old image appear ready.

## Local proof and limits

The LOCAL opt-in fixture is not Store source and is never production-enabled. It requires a saved
choice specific to this channel; no choice means no events. Withdrawal cancels timers, aborts
in-flight delivery where possible and discards unsent work. It cannot retract an accepted event or
erase backups. It never changes another consent channel, invokes a model or installs tracking.

Pure HTTP fixtures do not prove PostgreSQL persistence. `tests/test_postgres_product_analytics.py`
accepts only the existing isolated127.0.0.1:55439/pv_knowledge_test fixture DSN. It provisions one
UUID-named synthetic nonowner LOGIN with only the private capability membership (or verifies an
explicit distinct nonowner runtime DSN for that same fixture). It rejects remote/overridden/malformed
targets before connecting or truncating, closes clients before dropping its own role, and SKIPs
without the explicit isolated DSN. The existing hosted PostgreSQL test glob executes these cases
with TEST_KNOWLEDGE_DSN, without a new job, secret or service.
Atomic quotas, grants, retention and checksum require that real proof. Logical restore, local
harness→API→PG→authenticated BO and actual accessible screenshots require fresh resource leases
and independent review. Default OFF/local source implementation alone is not production parity.
