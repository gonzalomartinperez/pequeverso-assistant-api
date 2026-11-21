# ADR-0013: v1 error envelope stays; RFC 9457 mapping documented

Status: accepted (2026-11-21). Master-plan task PVA-M3.4.

## Context and problem statement

Every non-stream error of the v1 API is the JSON envelope
`{"error": {code, message, retryable, request_id}}` (`error_payload` in
`app/presentation/middleware.py`, codes in `FailureCode` in `app/domain/errors.py`, examples in
`contracts/examples/errors.json`, section "Errors" of `docs/api-contract.md`). The storefront
assistant depends on it. RFC 9457 defines `application/problem+json` as the standard shape for HTTP
API errors. We want the envelope to stay stable in v1 and a future v2 to adopt the standard without
a redesign.

## Considered options

- Adopt `application/problem+json` in v1: rejected. It changes the body and content type of every
  error, which breaks the storefront consumer and the v1 compatibility rule.
- Keep the envelope and document an exact mapping to RFC 9457: chosen.
- Keep the envelope with no documented mapping: rejected; the mapping would be reinvented in v2.

## Decision outcome

The v1 envelope, the codes and the HTTP statuses do not change. A v2 may serve the same data as
problem details with this mapping:

| RFC 9457 member | Source in v1 |
|---|---|
| `type` | `urn:pequeverso:error:<code>` |
| `title` | fixed English title per `code` (one per code, never request-specific) |
| `status` | the HTTP status of the response (table below) |
| `detail` | `message` (English, for developers, already free of visitor content) |
| `instance` | `urn:request:<request_id>` |
| `retryable` (extension member) | `retryable` |
| `code` (extension member) | `code`, so v2 clients keep the same switch key |

`type` uses a URN, not a documentation URL. The codes are an opaque, stable vocabulary: a URN does
not depend on where the documentation lives, is not a link that can rot, and needs no hosting
decision. RFC 9457 allows non-resolvable `type` URIs. A documentation URL can be added later as an
additional `help` extension member without changing `type`. `Retry-After` stays a header.

| Code | HTTP status | retryable | `Retry-After` |
|---|---|---|---|
| `invalid_request` | 422 | false | |
| `origin_denied` | 403 | false | |
| `csrf_failed` | 403 | false | |
| `session_expired` | 401 | false | |
| `rate_limited` | 429 | false | 600 |
| `busy` | 503 | true | 5 |
| `run_in_progress` | 409 | false | |
| `idempotency_conflict` | 409 | false | |
| `run_not_found` | 404 | false | |
| `budget_exhausted` | 503 | false | 3600 |
| `assistant_disabled` | 503 | false | |
| `catalog_unavailable` | 503 | true | |
| `provider_unavailable` | 503 | true | |
| `generation_failed` | 502 | true | |
| `timeout` | 504 | true | |
| `dependency_unavailable` | 503 | true | |

Two codes are produced outside `FailureCode` with `retryable: false`: `not_found` (404, unknown
route, `http_error` in `app/presentation/http.py`) and `unauthorized` (401 with
`WWW-Authenticate: Bearer`, private operations API, `app/presentation/operations.py`). Any other
status raised by the framework is reported as `invalid_request` with that status. In-stream failures
use the `run.failed` event, which is not an HTTP error response and is out of scope for this
mapping.

### Consequences

- Good: no consumer change now; the v2 conversion is a pure function of existing fields.
- Good: `type` and `title` are derived from `code`, so adding a code adds one table row.
- Bad: the mapping is documentation until v2 exists; nothing generates problem details today.
- Bad: `message` stays English; localization remains the client's job, keyed on `code`.

## Confirmation

`tests/test_api.py::test_public_errors_never_leak_internals` pins the four envelope keys, and the
same file asserts status and `code` pairs for the main codes (for example `origin_denied` 403,
`csrf_failed` 403, `session_expired` 401, `idempotency_conflict` 409, `rate_limited` 429,
`budget_exhausted` 503). `tests/test_faults.py` asserts `timeout` and `retryable`.
`tests/test_schemathesis_contract.py` checks that error bodies are `{"error": {"code": ...}}`
against the schema. `contracts/examples/errors.json` holds one example per code; it is regenerated
and compared by `uv run python -m contracts.export --check` (CI `static` job, step "Contract
artifacts are current") and `tests/test_contract.py`, and the oasdiff gate rejects breaking
changes against the base. `tests/test_error_mapping_doc.py` parses the status table above and fails
when it differs from `STATUS`, `RETRYABLE` and `RETRY_AFTER`. Nothing generates problem details
yet, so the member mapping itself is documentation until v2.
