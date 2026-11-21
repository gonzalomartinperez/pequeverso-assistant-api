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
[the exact boundary and tests](../explanation/official-web-evidence.md).

## Confirmation

`tests/test_official_help.py` covers the boundary: fail closed on article or schema changes
(`test_unusable_or_mismatched_articles_fail_closed`), inert HTML
(`test_html_is_inert_and_cannot_override_citation`), no general search or private scope
(`test_scope_has_no_general_search_private_accounts_or_action_topics`), fixed requests and no
private headers (`test_fixed_requests_singleflight_expiry_cooldown_and_no_private_headers`),
no redirects or stale fallback (`test_http_failures_are_optional_and_never_followed`), non-public
DNS refusal (`test_private_dns_prevents_http_dispatch`), persisted citations never re-fetched
(`test_history_and_idempotent_replay_keep_only_retrieved_citations`), default off with no network
reader (`test_fixture_opt_in_still_has_no_network_reader`), and no platform claim becoming a
merchant claim (`test_external_source_cannot_authorize_merchant_price_policy_or_transaction_claim`).
`tests/test_request_packing.py` covers citation only of sent evidence
(`test_valid_but_unsent_catalog_document_cannot_become_final_citation`). The residual
risks named above (undocumented source contract, trusted-DNS TLS, semantic citation support) have
no automated check; they remain activation gates reviewed by the owner and vps-ops.
