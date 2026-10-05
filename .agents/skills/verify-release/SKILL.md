---
name: verify-release
description: Verify a release candidate of the assistant API end to end without paid calls or deployment. Not an authorization to promote to main or deploy.
---

# Verify a release candidate

1. Clean checkout of the exact commit: `uv sync --frozen`.
2. `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`.
3. `uv run python -m contracts.export --check`, `uv run python scripts/evaluate_retrieval.py`,
   `uv run python scripts/evaluate_conversations.py --output docs/verification/fixture-eval.json`.
4. `scripts/smoke_container.sh` (non-root, read-only, SSE, restart persistence); record memory
   and stop time in `docs/deployment-contract.md` if they changed.
5. If a frontend commit is available, run it against this API locally, with its own
   instructions and ports, and record both commit shas. Do not interfere with its services.
6. Report what was not verified (live model, proxy buffering, real DNS and cookies). Promotion to
   `main` and any deployment need the owner's explicit approval; vps-ops deploys.

## Limits

- Verification only: promotion to `main` and any deployment need the owner's explicit approval;
  vps-ops deploys. No paid calls.
