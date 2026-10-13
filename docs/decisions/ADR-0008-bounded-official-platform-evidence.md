# ADR-0008: Optional bounded official platform evidence

Status: accepted for implementation, 2026-10-13; production activation not authorized.

The owner requested official internet sources without unrelated searches. Hosted model search
would add tool fees and broader domain scope to an adapter/ledger designed for one token-billed
request. Headless rendering would enlarge the runtime image. The official Hotmart help site's
public client instead reads unauthenticated JSON articles from a fixed public endpoint.

Add opt-in server retrieval for exactly three general buyer procedure articles, separate from
merchant catalog facts and private conversation data. One model attempt per turn and existing
budget limits remain unchanged. No model tool loop, arbitrary URL/query, account access,
transaction actions, browser/database/service dependency or shared infra is introduced.

This narrowly extends the historical “no tools” wording: read-only evidence acquisition exists
in the server; models still have no callable tools. ADR-0002 whole-catalog grounding and
ADR-0003 structured output/final validation remain binding. Only actually sent external ids
can become citations, and persisted answers/replays never re-fetch to alter their history.

The source API is used by the official public client but lacks a located stable integration
contract. Fail closed on source/schema/content changes, no stale-on-error or unapproved fallback.
Fixed-host TLS uses trusted DNS rather than IP pinning; vps-ops must review egress. This residual
and semantic citation support remain explicit activation gates. See
[the exact boundary and tests](../official-web-evidence.md).
