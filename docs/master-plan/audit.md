# Audit — measured baseline of pequeverso-assistant-api

Date 2026-11-09. Subject: `origin/develop` `6912579245506bbd60f745243905ce4974dfbfe9` (97 commits, last 2026-10-19; `origin/main` `e3e69960472b68c2ae8955e720c81893a2138803`, develop contains main). Python 3.14.8, uv 0.13.1. The repository is public (MIT for software, `NOTICE.md` reserves brand and commercial material). The checkout was never modified: measurements ran in a clean `uv sync --frozen` environment from the committed lockfile, with real services absent (see "Could not be measured"). Raw files live in `audit/` of the planner's folder; the evidence files copied next to this plan are under `audit/` here.

## 1. Numbers

| Metric | Value | Evidence |
|---|---|---|
| Tracked files / lines of Python | 412 files; `app/` 15,132, `tests/` 20,565, `scripts/` 6,006 lines | `file-index.csv` |
| Tests | 1,698 passed, 45 skipped (services absent), 6 subtests, 248.8 s serial | `pytest.txt` (planner audit) |
| Coverage, local, no PostgreSQL or Neo4j | statements 87.1%, **line 84.95% (85%)**, **branch 76.5%** (1,382 of 1,806; 164 partial) | `audit/coverage-summary.txt` |
| Lowest-covered modules | `bootstrap/import_database.py` 0%, `main.py` 0%, `adapters/postgres/knowledge.py` 15.6%, `import_sqlite.py` 18.5%, `product_analytics.py` 24.6%, `private_operations.py` 29.8%, `private_ledger.py` 34.4%, `private_stores.py` 38.0%, `database.py` 58.8% | same |
| `mypy --strict` | 0 errors (95 app files; 123 files with contracts and scripts) | `mypy-strict-app.txt`, `mypy-config.txt` |
| Ruff lint / format | All checks passed; 281 files formatted (current rule set: `E F I N UP B S SIM RUF ASYNC PT`, line 110, single quotes) | `ruff-check.txt`, `ruff-format.txt` |
| Complexity (ruff C901 raw dump) | 661 functions; **19 above 10**, 9 above 15; top: `create_app` 36, `fail_closed` (config) 29, `start` (chat) 29, `finalize` 21, `build_router` (analytics) 20 | `audit/complexity-over-10.txt` |
| Image scan (Trivy, fixture image on Debian 13.7) | 1 CRITICAL (`certifi` 2026.7.22, GHSA-6q48-6c7w-9gw2, fixed in 2026.10.18); 51 HIGH, all OS packages (util-linux family 36, sqlite 3, zlib 2, others); only 5 of 52 findings have a fixed version | `audit/trivy-summary.txt` |
| OpenAPI | `contracts/openapi.json` lists 4 paths and 5 operations (availability, session POST and DELETE, messages, run cancel); health, product-analytics ingest and `/internal/v1/ops/*` use `include_in_schema=False` | `contracts/openapi.json`, `app/presentation/*.py` |
| Retrieval (lexical, 37 passages, 190 qrels cases) | recall@1 0.511, @3 0.689, @5 0.737, @10 0.758, MRR 0.603 | `audit/recall-at-k.txt` |
| Corpus pipeline (fixture) | 288 cases, 0 gate failures, 0 language mismatches, 218 behaviour flags (not model signal) | `audit/corpus-summary.txt` |
| Real-model review (2026-10-19, agent, not blind) | 245 turns: 195 acceptable, 46 P3, 4 P2, 0 P1; targeted revalidation 20 of 20 | `docs/verification/real-evaluation-2026-10-19.md` |
| Logs | 662 JSON log lines were emitted into the stdout of one corpus run; `eval-corpus.json` begins with log lines, so machine output cannot be parsed without stripping | planner audit `eval-corpus.json` |
| Dependabot | 8 remote `dependabot/*` branches (uv 5 including `uv/certifi-2026.10.18` which targets main, github-actions 1, docker 2 including `python-3.15.0-slim-trixie`); open-PR state not read | `git branch -r` |
| CI | one workflow `quality.yml`, 5 jobs plus aggregate `checks`; actions pinned by SHA; `permissions: {}`; actionlint, zizmor, gitleaks (full history); a second workflow uses `pull_request_target` with a zizmor ignore | `.github/workflows/` |

Comparison with the sibling `audit/portfolio-assistant-api/`: 819 tests, 77.6% line coverage, mypy strict 199 errors. This repo is ahead on typing and tests; it shares the same gaps in mutation, property tests, SBOM and attestations.

## 2. Findings

### P0

| # | Finding | Evidence | Plan |
|---|---|---|---|
| P0-1 | `certifi 2026.7.22` carries a CRITICAL advisory (GHSA-6q48-6c7w-9gw2), fixed in 2026.10.18. certifi is the CA bundle behind `httpx`, `requests` and the OpenAI SDK; the service is not deployed, so exposure today is zero, but the lock is what the first image will ship | `uv.lock` line 100; `audit/trivy-summary.txt` | Must be in the **first weekly dependency PR** (Monday 2026-11-16 09:00 ART, day 7 of the 7-day critical SLA). Fallback manual path if that PR is not green by 2026-11-14: a task-branch PR bumping only certifi (no second Dependabot PR). Roadmap M1.2 |

### P1

| # | Finding | Evidence | Plan |
|---|---|---|---|
| P1-1 | No golden set and no release gate for assistant quality; 100% invariants exist only as fixture floors; retrieval weak in four families (out-of-scope 0.00, support 0.36, stale-data 0.40, purchase-process 0.43) and in the English language slice (0.17, 6 cases; not a family, no target by OD-32) | `audit/recall-at-k.txt`, `tests/test_evaluations.py` | `assistant-quality.md`; M2 |
| P1-2 | Dependabot configuration breaks the owner's rule: `open-pull-requests-limit: 5`, separate groups per ecosystem, uv at 06:00, Actions and Docker without a shared group, no `multi-ecosystem-groups`; 8 stale branches; `dependency-policy.yml` uses `pull_request_target` | `.github/dependabot.yml`, branches | M1.1 to M1.3 |
| P1-3 | Rubric D2 critical criterion (complexity ≤ 10) unmet: 19 functions above 10, `create_app` 36 | `audit/complexity-over-10.txt` | `target-state.md` section 4; M4 |
| P1-4 | Branch coverage 76.5% locally, below the 85% floor; the PostgreSQL adapters sit at 16 to 59% because their tests are skipped without services (they run in the CI `database` job but their coverage is never combined or gated); no diff coverage, mutation or property tests; no contract diff or fuzzing | `audit/coverage-summary.txt`, `quality.yml` | `testing.md`; M2 |
| P1-5 | No `SECURITY.md`, `CONTRIBUTING.md`, `SUPPORT.md`, `CODE_OF_CONDUCT.md`, issue forms, PR template or `CODEOWNERS`; no CodeQL, Scorecard, SBOM, provenance or dependency-review; images never published or attested | `git ls-tree` (no such paths) | `docs-and-community.md`, `ci-cd.md`; M1 |
| P1-6 | 51 HIGH findings in the base OS layer (47 without a fixed version). Owner policy relayed 2026-10-19 treats image CVEs as advisory; the ecosystem SLA is stricter (High, fixable: 30 days; base-image High: next rebuild) | `audit/trivy-summary.txt`, `docs/security.md` | `ci-cd.md` section 6, decision PVA-D9 |

### P2

| # | Finding | Evidence | Plan |
|---|---|---|---|
| P2-1 | `openapi.json` is incomplete (4 paths, 5 operations): health, analytics ingest and internal operations are invisible to oasdiff and Schemathesis | section 1 | M3: public spec plus `openapi.internal.json` |
| P2-2 | Noisy stdout logs: third-party INFO lines reduce to `external unstructured_event` and flood stdout; eval CLIs print logs and JSON on the same stream | `eval-corpus.json`, `app/bootstrap/logging.py` | M3 |
| P2-3 | Documentation drift: `docs/evaluation.md` states 20 retrieval, 19 conversation and 14 guard cases, recall 0.95; files contain 23, 24 and 22 cases and recall 0.957; README has 13 badges and long galleries; `AGENTS.md` says "`main` is the default" while all work integrates on `develop` | `evals/*.json`, `README.md`, `AGENTS.md` | `docs-and-community.md`; M3 |
| P2-4 | `datetime.now` in adapters (`official_help.py:123`, `telemetry.py:172,293`) instead of the `Clock` port | `app/` grep | M3 |
| P2-5 | Skills are canonical in `.claude/skills` with `.agents/skills` symlinks (inverse of the ecosystem layout); six skills, no activation evals | `git ls-tree` | `skills.md`; M1 |
| P2-6 | Ruff rule set narrower than ecosystem 10.2 and style differs: with the ecosystem families on `app`, `scripts`, `contracts` ruff 0.17.3 reports **1,331 findings** (751 are missing-docstring rules D100-D107; 123 TC001, 81 TC003, 77 E402 and 59 T201 mostly in scripts; 29 TRY301; 21 S101; 18 ANN401), and `tests` another 592 outside the ecosystem's test ignores; `ruff format` at 100 columns with double quotes would rewrite 204 of 225 files (current: 110 columns, single quotes). `requires-python = ">=3.14,<3.15"` blocks the 3.15 non-blocking job | `audit/ruff-ecosystem-families.txt`, `pyproject.toml` | M2: mechanical format PR, per-file ignores, fix in one pass; docstring scope deviation in `standards.md` |
| P2-7 | `psycopg` and `psycopg-pool` are LGPL-3.0, outside the ecosystem licence allow-list | `dependencies.md` | ADR, PVA-D15 |
| P2-8 | Dockerfile: hand-pinned `liblzma5=5.8.1-1+deb13u2` patch, uv cache id `vps-ops-uv-python314` copied from another repo, `--frozen` rather than `--locked`, no OCI labels, no `SOURCE_DATE_EPOCH` | `infra/docker/app/Dockerfile` | M1 |
| P2-9 | Health endpoints are `/health/live` and `/health/ready`; the ecosystem contract is `/healthz` and `/readyz` with `version` and `schema_version` | `app/presentation/http.py:263` | M3, expand/contract with vps-ops |
| P2-10 | Error envelope is `{error:{code,message,retryable,request_id}}`, not RFC 9457; documented deviation (breaking change in v1 not allowed) | `contracts/examples/errors.json` | PVA-D6 |
| P2-11 | Test suite is 249 s serial, near the 5 min PR budget; 45 tests skip without services | `pytest.txt` | M1: xdist and random order measured |
| P2-12 | `tests/fixtures/product-analytics-pointer.test.cjs` is the only `.cjs`; dense 28-line file | `file-index.csv` | M4: convert to `.mts` |
| P2-13 | Prompt version is a hand-bumped string with no lock or test | `app/ai/prompt.py:12` | `assistant-quality.md` section 9 |

## 3. Inventory (components and flows)

| Layer (`app/`) | Files | Role | Notes |
|---|---:|---|---|
| `domain` | 14 | pure rules: answer policy, page claims, language, budget, redaction, product analytics, errors | stdlib only (guard) |
| `application` | 21 | chat run, answers finalization, catalog, knowledge, operations, sessions, analytics ports and services | stdlib only; ports in `ports.py`, `knowledge_ports.py` |
| `ai` | 6 | prompt, evidence ranking, output schema, composer, provider port | sits between application and adapters |
| `adapters` | 38 | SQLite fixture, PostgreSQL (public and private, six SQL migrations), Neo4j projection, OpenAI provider and embeddings, graph composer, telemetry, official help, catalog source | one third-party allowlist per layer in the AST test |
| `presentation` | 10 | FastAPI routers, schemas, SSE events, middleware, operations, product analytics | |
| `bootstrap` | 10 | `create_app` composition root, config (`BaseSettings`), logging, persistence jobs | |

Flows: session and CSRF, then message POST, evidence packing (catalog fits 24 KB), one provider generation, `finalize` (reference resolution, answer rules, price replacement), SSE terminal event, persistence; cancel; private operations summary and telemetry for the backoffice; optional three-article official Hotmart help; optional product analytics ingest and private read; catalog sync from a pinned storefront commit (`scripts/sync_catalog.py`, `tools/catalog/export.ts`); knowledge indexing jobs (PostgreSQL chunks, embeddings, Neo4j projection).

Assets: 9 ADRs, 6 skills, 41 dated verification files (5.6 MB), 18 corpus files, 4 frozen end-to-end manifests (hash-bound to real-run records), 14 evaluation-related test files, 9 evaluation scripts.

## 4. What could not be measured

| Item | Why | Handled by |
|---|---|---|
| Combined coverage (static job plus database job) | local run has no PostgreSQL or Neo4j; CI services not executed | M2 measures, floor starts from the combined value |
| Mutation score, property-test yield | no tooling in repo | M2 baseline run |
| Combined effect of the ecosystem Ruff families on `tests` per file ignores | measured raw only | M2 (per-file ignores decide the final number) |
| recall under hybrid retrieval with real embeddings | needs authorized embedding calls | spend-gated, floor 90 |
| Real-model behaviour on today's `develop` | last real runs on 2026-10-18/19 sources; no new calls made | live lane, owner authorization |
| Latency p95 and load behaviour | no load harness; VPS not bought | M2 harness on CI runner (floor 90 on D6 until MV) |
| CI duration p50/p95 | no run history pulled in this audit | M1 weekly duration report |
| Reachability of the certifi advisory | advisory text not analysed here | first M1 task reads GHSA text; not blocking |
| Trivy on the published image | no image is published | M7 and MV |
