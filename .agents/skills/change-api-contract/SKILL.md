---
name: change-api-contract
description: Change the v1 HTTP/SSE contract consumed by pequeverso-assistant-web without breaking it.
---

# Change the API contract

1. Edit the wire models in `app/presentation/schemas.py` or `events.py` and the route in `http.py`.
   In v1 only add optional fields, notices or codes. Removals, renames or grammar changes go to
   `/api/v2`.
2. `uv run python -m contracts.export` and review the diff of `contracts/`: OpenAPI, SSE schema,
   examples, manifest.
3. Update `docs/api-contract.md` (sessions, events, errors, freshness, actions) and add tests in
   `tests/test_api.py` or `tests/test_streaming.py`.
4. The PR body lists the new manifest hash and what the frontend must do. The web repository is
   owned by another agent: do not edit it; point it to the exact merged commit.
