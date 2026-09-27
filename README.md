# pequeverso-assistant-api

Backend of the Pequeverso shopping assistant: an **advisory, read-only** AI assistant that helps
adult buyers understand the Grafismo Fonético kit, choose where to start, compare what is
included and reach the storefront's purchase flow. Private repository; all rights reserved.

- Python 3.13, FastAPI, uv; SQLite (single process); OpenAI Responses (`gpt-6-luna`) behind a
  provider port; a deterministic **fixture provider is the default**.
- Versioned HTTP/SSE contract for `pequeverso-assistant-web` (embedded `/embed` first).
- Grounded in a catalog exported from the storefront at a pinned commit; every product,
  link and price shown is server-validated.

## Quick start (clean checkout, no credentials)

```
uv sync --frozen
uv run uvicorn app.main:app --reload --port 8000      # fixture mode, bundled catalog, ./data/
curl -s -c /tmp/j -H 'Origin: http://localhost:3000' -H 'Content-Type: application/json' \
  -X POST localhost:8000/api/v1/session -d '{}'
```

Ask a question (replace `<csrf>` with `csrf_token` from the response):

```
curl -N -b /tmp/j -H 'Origin: http://localhost:3000' -H 'Content-Type: application/json' \
  -H 'X-CSRF-Token: <csrf>' -H 'Idempotency-Key: local-0001' \
  -X POST localhost:8000/api/v1/messages -d '{"content":"¿Qué incluye el kit?"}'
```

## Verify

```
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run pytest                                   # unit, HTTP/SSE contract, real-socket streaming, SQLite, budget races, evals
uv run python -m contracts.export --check       # pinned contract artifacts are current
uv run python scripts/evaluate_retrieval.py
uv run python scripts/evaluate_conversations.py # fixture safety + guards (no paid calls)
scripts/smoke_container.sh                      # image: non-root, read-only, SSE, restart persistence
```

## Documentation

| Topic | Doc |
|---|---|
| Frontend contract (sessions, SSE, references, freshness, errors) | `docs/api-contract.md` + `contracts/`, handoff `docs/handoffs/assistant-web.md` |
| Architecture and decisions | `docs/architecture.md`, `docs/decisions/` |
| Security, privacy, retention | `docs/security.md` |
| Catalog source, sync, freshness | `docs/catalog.md` |
| Evaluation and live procedure | `docs/evaluation.md` |
| Deployment handoff (vps-ops/Coolify) | `docs/deployment-contract.md` |
| Dependency updates and auto-merge policy | `docs/dependency-updates.md` |
| Reference adoption (portfolio-assistant-api) | `docs/reference-adoption.md` |
| Storefront transition, open business questions | `docs/handoffs/storefront-transition.md`, `docs/business-questions.md` |
| Agent instructions and skills | `AGENTS.md`, `.agents/skills/` |
