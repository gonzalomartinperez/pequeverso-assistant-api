# Execution plan and status

| Step | Status |
|---|---|
| Discovery: storefront (catalog, policies, flow, deploy triggers), reference API, vps-ops boundary | Done 2026-09-27 |
| Owner decisions: privacy section (draft + review), 24 h retention, placement, offer never mentioned | Answered 2026-09-27 |
| Repository created private with bootstrap `main`; made **public** and `main` set as default at the owner's request (2026-09-27); rulesets on `main` and `develop` | Done |
| Backend: domain, use cases, AI composer, SQLite, providers, HTTP/SSE, bootstrap | Merged, PR #1 (`0750524`) |
| Catalog export from pinned storefront commit, freshness policy | Merged, PR #1 |
| Tests (unit, contract, real-socket streaming, persistence, budget races, security, architecture) and evaluations | Merged, PR #1 |
| Contract v1 artifacts + frontend handoff; deployment contract; security; skills; CI | Merged, PR #1; web handoff pinned in `docs/handoffs/backoffice.md` |
| Ownership update: frontend moved to `pequeverso-assistant-web`; storefront integration deferred | Applied (no storefront changes existed) |
| Conservative Dependabot automation | Merged, PR #2 (`c0f842e`); verified live on Dependabot PR #3 (manual review, auto-merge off) |
| Live-model evaluation, production deployment, DNS | Not authorized, pending owner |
| Contract 1.1: es/en languages, starters, ledger states (confirmed/estimated/pending), run metrics, private ops API, medium effort, published-only catalog sync with semantic report | Implemented on `feat/assistant-evolution` (2026-10-05) |
| Evaluation corpus by intent family with dev/holdout split | PR #20 |
| Native storefront assistant (cross-origin, disabled by default); backoffice consuming the ops API | In the storefront and web repositories |
| Live-model evaluation at medium effort (reasoning tokens, incomplete rate, cost per turn) | Not authorized, pending owner |
