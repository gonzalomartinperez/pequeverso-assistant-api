---
name: change-api-contract
description: Change the v1 HTTP/SSE contract (storefront native assistant) or the private ops contract (backoffice) without breaking either.
---

# Change the API contract

1. Edit the wire models in `app/presentation/schemas.py` or `events.py` and the route in `http.py`.
   In v1 only add optional fields, notices or codes. Removals, renames or grammar changes go to
   `/api/v2`.
2. `uv run python -m contracts.export` and review the diff of `contracts/`: OpenAPI, SSE schema,
   examples, manifest.
3. Update `docs/api-contract.md` (sessions, events, errors, freshness, actions) and add tests in
   `tests/test_api.py` or `tests/test_streaming.py`.
4. Bump `CONTRACT_REVISION` in `schemas.py` for any additive change and say what changed in
   `docs/api-contract.md`. The private ops contract (`contracts/ops.schema.json`, served by
   `app/presentation/operations.py`) follows the same rules: additive only, nulls for unknown
   values, never conversation content.
5. The PR body lists the new manifest hash and what each consumer must do: the storefront
   (`pequeverso`, native assistant) and the backoffice. Their repositories pin the contract
   from the exact merged commit (`git show <sha>:contracts/...`); do not edit them from here.

Limits: no paid calls, no deploys. A skill is a procedure, never an authorization to merge.
