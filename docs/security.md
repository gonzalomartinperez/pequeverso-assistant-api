# Security, privacy and threat model

The assistant is advisory and read-only. It holds no customer, order or payment data; the model
has no tools. The controls below are code, not prompt wording.

| Threat | Control (code) | Tested in |
|---|---|---|
| Session hijack or confusion, cross-session leakage | Opaque 64-byte random secret in a host-only HttpOnly SameSite=Lax cookie (`__Host-`, Secure in prod), stored as a SHA-256 digest; every query is scoped by session id; the CSRF token is bound to the session | `test_api.py::test_sessions_are_isolated`, `test_mutations_require_session_and_csrf` |
| CSRF | Allowlisted `Origin` on every mutation (middleware), JSON content type, per-session CSRF header compared in constant time | `test_origin_content_type_and_body_limits`, `test_streaming.py::test_origin_is_enforced_on_the_real_server` |
| Endpoint abuse and cost exhaustion | Per-client session creation (20/h), per-session (30/day) and per-client (60/h) message limits; 600-char questions; 16 KiB bodies; one active run per session (DB partial unique index); global concurrency slot (4); 60 s run deadline; one model call per turn, no tools; `max_output_tokens` 4000 (reasoning included) | `test_rate_limits`, `test_streaming.py::test_one_active_run_per_session_and_global_concurrency` |
| Budget overrun, including races | Worst-case reservation (input bytes as a token bound at the highest input rate, plus max output) inside a `BEGIN IMMEDIATE` transaction before the call; monthly cutoff with a 10 % margin and a daily cap; settlement to reported usage; missing usage keeps the reservation | `test_budget_concurrency.py` (500 concurrent reservations; 4 processes) |
| Prompt injection (visitor or catalog text) | Catalog and conversation sent as data in separate user messages; the model output is a strict JSON schema; **every** reference is re-resolved against the catalog; the final answer is checked for unlisted URLs and e-mails, unknown or unverified prices, discount codes, pressure claims, the post-purchase offer name and payment-data requests, and replaced whole on any violation; markup is stripped | `evals/guards.json` (10 cases), `test_answers.py`, `test_domain.py::test_answer_rules` |
| Malicious catalog content, SSRF on ingestion | Catalog URL is configuration only, https, allowlisted host, no redirects, `trust_env=False`, 256 KiB cap, JSON content type; strict schema with unknown fields rejected; link, image and document URLs must be https on allowlisted hosts; a failed or invalid fetch never replaces the active snapshot | `test_catalog.py` |
| Unsafe links or generated actions | The model can only name ids; URLs come from the catalog. The only action kinds are "ask a follow-up" and "open a validated URL"; no commerce actions exist | `test_answers.py::test_invented_ids_are_dropped...` |
| Product or price manipulation | Prices come only from the catalog snapshot with a freshness policy; any other amount in the text replaces the answer; product cards are server data | `test_stale_prices_are_withheld_everywhere` |
| Payment data | Card numbers (Luhn-checked) stop the turn before storage or any model call; the stored message is a placeholder | `test_card_numbers_never_reach_the_model_or_storage` |
| Personal data sent to the model | E-mails and phone numbers are redacted before storage and the model; the prompt forbids asking for children's identifying data; OpenAI calls use `store=false` and a hashed `safety_identifier` | `test_contact_data_is_redacted_before_the_model`, eval `child-data-minimization` |
| Logging leaks | Formatter allowlist: only JSON built from safe fields is logged; other messages become `unstructured_event`; request logs carry the route template, status and duration (no path params, query, body, cookie or IP); uvicorn access log off | `test_security.py::test_logs_never_contain_conversation_content_or_ips` |
| Spoofed client IP (rate-limit evasion) | `X-Forwarded-For` trusted only from `TRUSTED_PROXY_CIDRS`; right-to-left walk; malformed or long chains fall back to the peer; IPs are HMAC-hashed before storage | `test_forwarded_for_is_trusted_only_from_configured_proxies` |
| Information disclosure | Uniform error envelope; unexpected errors map to `dependency_unavailable`; OpenAPI disabled in production; no prompt, reasoning, provider payload or key in any response | `test_public_errors_never_leak_internals`, `test_contract.py` |
| Private operations data exposed | `/internal/v1/ops/summary` exists only with `OPS_READ_TOKEN`; bearer token compared as a SHA-256 digest in constant time; outside the public `/api` prefix (never routed publicly); aggregates only (no messages, session ids, client keys, e-mails); `no-store` | `test_operations.py::test_ops_summary_requires_a_configured_token`, `test_ops_summary_reports_aggregates_without_content` |
| Language switching by injected or quoted text | The reply language is decided in code from the visitor's own words (quotes, code, URLs and product names removed), then the conversation, then the UI locale; unsupported languages get a fixed bilingual note without a model call | `test_language.py`, `test_operations.py::test_unsupported_language_answers_briefly_without_a_model_call_or_spend` |
| Secrets | Keys only from the environment (`SecretStr`, hidden in validation errors); `.env*` ignored by git and Docker; production refuses a default hash key | `test_configuration_fails_closed` |

Prompt injection is not "solved": a model can still write unhelpful or off-tone text. The
boundary guarantees that such text cannot carry invented products, links, prices, discounts,
offers or payment requests to a visitor as a final answer.

## Data retention and privacy

- **Stored:** session digest and CSRF token, redacted questions, answers and their validated
  references, run states. Retained 24 h after last activity, then deleted (purge every 10 min).
  The visitor can delete earlier (`DELETE /api/v1/session`).
- **Kept longer:** the spend ledger (run id, amounts, token counts, model: no conversation data)
  and hourly or daily rate counters keyed by an HMAC of the IP (purged after 2 days).
- **Sent to OpenAI (live mode only):** the redacted question, up to 12 recent messages of the same
  session, and the public catalog. `store=false`; OpenAI's API data policies apply.
- **Not collected:** names, accounts, orders, payment data, analytics or tracking.
- **User notice required before launch (owner/legal decision):** the storefront privacy policy
  promises an update when a tool is added. The owner chose to add an assistant section to
  `/privacidad/` (visible when the assistant is enabled) covering: AI assistant, provider
  OpenAI (USA; international transfer), purpose (answering product questions), data
  (messages; do not include personal data), 24 h retention and deletion, and no automated
  decisions about purchases. The web UI should show a one-line notice with a link. This text
  belongs to the storefront and web repositories and needs owner or legal review.
