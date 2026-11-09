# Target state — pequeverso-assistant-api

Planning only. Applies ecosystem section 9 (architecture), 10.2 (Python) and 12 (assistant quality) and records only justified deviations. Measured baseline in `audit.md`.

## 1. Principle

The architecture is already hexagonal in substance and guarded by a test (`tests/test_architecture.py`, AST based, with negative fixtures in `tests/test_architecture_coverage.py`). The plan does not redesign it. It (a) replaces hand-rolled layer rules with import-linter plus a smaller AST guard, (b) removes the one real structural defect, the 36-complexity composition root and its 18 siblings above 10, (c) closes the contract and operability gaps, and (d) leaves every layer name where it is. Where a rename would only churn 40,000 lines of imports and tests, it is ceremony (owner decision O3) and is omitted.

## 2. Layers, ports and the dependency rule

| Ecosystem term | This repo | Allowed imports (guard) |
|---|---|---|
| `domain` | `app/domain` (14 files) | stdlib only |
| `application` (use cases, graph) | `app/application` (21) | `domain`, `application`; stdlib only |
| `ports` | `app/application/ports.py`, `knowledge_ports.py` (typing `Protocol`s inside `application`) | same as application |
| prompt and evidence contract | `app/ai` (6) | `domain`, `application`, `ai` |
| `adapters` | `app/adapters/{sqlite,postgres,neo4j,graph,providers,observability,catalog}` and flat modules | `domain`, `application`, `ai`, `adapters`; third-party per adapter group |
| `api` | `app/presentation` (10) | `domain`, `application`, `presentation`; `fastapi`, `starlette`, `pydantic` |
| composition root | `app/bootstrap` (10) | everything; the only place that names concrete classes |

Decision PVA-D3: keep the six layer names and the module for ports. Ecosystem names `ports/` and `api/` are mapped, not created. LangGraph, LangChain and LangSmith stay inside `adapters/graph`; SQL inside `adapters/sqlite` and `adapters/postgres`; Cypher and the Neo4j driver inside `adapters/neo4j` (AGENTS.md rules, unchanged).

### Guard design

| Rule | Tool | Notes |
|---|---|---|
| Layer order (the table above) | import-linter `layers` and `forbidden` contracts in `.importlinter` (or `pyproject.toml`) | replaces the `ALLOWED` dict in the AST test |
| Third-party allowlist per layer (`pydantic`, `psycopg`, `neo4j`, `langgraph`, ... ) | import-linter `forbidden` with `include_external_packages = true` | domain and application forbid every non-stdlib package |
| Independence between adapter groups (postgres, neo4j, sqlite, providers, graph) | import-linter `independence`, with one named exception: `adapters/postgres/import_sqlite.py` may read the SQLite driver (AGENTS.md) | exception listed explicitly, tested |
| Banned calls: `datetime.now()` and `time.time()` outside the `Clock` port and `bootstrap`; `os.environ` and `os.getenv` outside `bootstrap` | AST test (what import-linter cannot express) | 4 violations today, all fixed in M3 (`official_help.py`, `telemetry.py`) |
| SQL only in sqlite and postgres adapters; Cypher only in neo4j adapter | AST test (kept) | unchanged |
| Closed SSE event set; disconnect cancels the run and releases spend | contract and integration tests | existing, extended in `testing.md` |
| Dead code | vulture at confidence 80 with an allowlist file | new, empty allowlist target |
| Complexity ≤ 10 per function | ruff C901 `max-complexity = 10` plus ratchet file | baseline: 19 functions above 10, only downward |

Negative fixtures: a deliberately illegal import for each contract fails in a temporary package (pattern already used by `test_architecture_coverage.py`); the baseline of violations is empty from the day the contracts are enforced (M4).

## 3. Composition root and typing policy

- Composition root: `app/bootstrap`. No DI framework (ecosystem 9); explicit wiring functions only.
- Frozen `BaseSettings` with `SecretStr`, `extra="forbid"` already hold for `app/bootstrap/config.py`; the plan adds a generated **env schema** (names, required, secret flag) checked against `.env.example` and published for `vps-ops` (ecosystem 8.5).
- Typing: `mypy --strict` stays the serial gate (0 errors today over `app`, `contracts`, `scripts`); extend `files` to `evals` and `tools` Python; Pyrefly as a second, initially non-blocking CI job; `ty` in the editor only. Type hints on every function (already true under strict).
- `requires-python = ">=3.14"` (drop the `<3.15` cap) with a non-blocking Python 3.15 CI job; production stays 3.14.x (ecosystem 8.1).

## 4. The one structural change: decompose the hot spots

All splits are behaviour-preserving, executed one function per PR, protected before the first edit by the golden cassette lane, the existing 1,698 tests and mutation on the touched module. No file moves rename public symbols imported elsewhere without a codemod and a green full suite.

| Function (complexity) | Target shape | Acceptance |
|---|---|---|
| `bootstrap/container.py:create_app` (36) | `wiring.py` (build clock, settings, stores, providers, services as a frozen dataclass), `lifespan.py` (startup restore, maintenance and catalog refresh tasks, shutdown drain), `routes.py` (install routers, middleware, error handlers), `container.py` keeps a 10-line `create_app` | every new function ≤ 10; `tests/test_runtime_shutdown.py`, `test_runtime_cohort.py`, container smoke unchanged |
| `bootstrap/config.py:fail_closed` (29) | table of `(rule_name, predicate, message)` evaluated in order | one test per rule; message text unchanged |
| `application/chat.py:start` (29) and `events` (17) | named steps (admit, reserve budget, prepare evidence, generate, finalize, persist) in `chat_steps.py`; `start` is a short pipeline | cancel, idempotent replay and budget race tests unchanged |
| `application/answers.py:finalize` (21) and `check_content` (13) | one function per stage (resolve references, apply rules, replace, notices) | golden set and `test_answers.py` unchanged; mutation score on the module recorded before and after |
| `presentation/product_analytics.py:build_router` (20), `consistent` (17) | per-route handler functions, validator table | analytics HTTP tests unchanged |
| Remaining 11 functions (complexity 11 to 17) in 11 files: `composer.prepare`, `unsupported_page_claim`, `knowledge.retrieve`, `check_answer`, `lifespan`, `catalog_scope_reply`, `build_public_corpus`, analytics `ingest`, `indexing.index`, provider `stream`, graph `candidates` | local extraction (`lifespan` goes with the `create_app` split) | ratchet file reaches empty |

The complexity ratchet file stores `file::qualname -> complexity` for every function above 10; CI fails on a new entry or an increase and the file only shrinks.

## 5. Contract and operability changes (expand, then contract)

| Change | Why | Compatibility |
|---|---|---|
| `contracts/openapi.json` covers every public operation (adds product-analytics ingest); new `contracts/openapi.internal.json` covers health, `/internal/v1/ops/*`, analytics read; `contracts.export --check` still guards drift | 4 paths and 5 operations today hide routes from oasdiff and Schemathesis (audit P2-1) | additive; contract revision is 1.5 today and becomes 1.6 when the spec changes (PVA-M3.1); 1.7 is reserved for the assistant blocks, progress, capabilities, feedback and memory additions (PVA-M5-X, `roadmap.md`); consumers' snapshots refresh each time |
| `/healthz` and `/readyz` returning `version` and `schema_version`; `/health/live` and `/health/ready` stay | ecosystem 8.5 deploy contract | expand now; `vps-ops` moves; removal of the old paths is a `contract-major` change, not planned |
| `x-request-id` propagation: accept a valid inbound id (regex `^[A-Za-z0-9-]{8,64}$` already exists in `middleware.py`), echo it, log it, test it | ecosystem 18.1 request correlation | already generated; test and log field added |
| Error envelope unchanged (PVA-D6); `docs/reference/api-contract.md` maps `code`, `message`, `retryable`, `request_id` to RFC 9457 fields (`type`, `title`, `detail`, `instance`) so a future major can adopt `application/problem+json` mechanically | v1 is versioned; a breaking change needs a major and ADR; messages are machine-first, user-facing Spanish copy belongs to the storefront | no wire change |
| Logging: `LOG_STREAM` (`stdout` default for the service, `stderr` for CLIs and evals), `httpx` and `httpcore` loggers at WARNING, repeated `external unstructured_event` lines counted not printed | audit P2-2 | no schema change to the allowlisted events; adds `prompt_version` to the `run` event allowlist |
| `Clock` port injected into `official_help` and `telemetry` | audit P2-4 | internal |

## 6. Python and tooling layout (deviation recorded)

Ecosystem 10.2 prefers a `src/` layout. This repo keeps the flat `app/` package with `package = false` (PVA-D2): it is a deployable service, never an installable library; the Dockerfile, `vps-ops` deploy contract, six skills, README and 20,000 lines of tests all name `app.*`; the `src/` benefit (not importing from the working directory by accident) is already neutralized by `pythonpath = ["."]` in pytest and the image copies only `app`. Revisit only if the code becomes a package.

New top-level folders: `evals/` (Python package: `graders.py`, `cassette.py`, `runner.py`, plus data), `ratchets/` (JSON baselines), `scripts/scorecard.py`. Existing `scripts/` stays (evaluation, catalog, migration and operator CLIs); no consolidation of the nine evaluation scripts beyond routing them through the shared graders, because 14 test files and the frozen real-run records depend on their current behaviour.

## 7. Destination of every `.js`, `.mjs`, `.cjs` and TypeScript file

| Path | Lines | Destination | Reason |
|---|---:|---|---|
| `tests/fixtures/product-analytics-pointer.test.cjs` | 28 | `tests/js/product-analytics-pointer.test.mts` (convert to ESM TypeScript, run by Node type stripping, reformat) | ecosystem 10.1: no `.cjs` when the tool can load TS; `node --test` can |
| `tests/fixtures/product-analytics.html` | 93 | `tests/js/fixtures/product-analytics.html` | sits beside the only reader |
| `tools/catalog/export.ts` | 249 | stays; exception | already TypeScript; it imports modules of a pinned storefront archive that do not exist here, so it cannot be type-checked in this repo; contract kept by `export-layout.test.ts` and `sync_catalog.py` |
| `tools/catalog/export-layout.test.ts` | 112 | stays | run by `node --test` in CI |

There are no `.mjs` files and no other `.js` or `.cjs` files (`file-index.csv`). Node tooling is limited to these three files; no `package.json` is introduced, so there is no npm ecosystem in Dependabot and no Biome (PVA-D2b: three files do not justify a second toolchain; formatting is done by hand and checked by `node --check` equivalent in CI).

## 8. ADRs to write (MADR 4, `docs/decisions/ADR-00NN-title.md`, stable existing naming)

| ADR | Decision | Milestone |
|---|---|---|
| ADR-0010 | Two evaluation tiers, golden set composition, cassette at the provider port | M2 |
| ADR-0011 | Layer enforcement with import-linter plus AST guard; layer names kept | M2 |
| ADR-0012 | Flat `app/` layout, no `src/` | M1 |
| ADR-0013 | v1 error envelope stays; RFC 9457 mapping documented | M3 |
| ADR-0014 | Keep the allowlist JSON log formatter, no structlog | M3 |
| ADR-0015 | Dependency policy exceptions: `psycopg` (LGPL-3.0), `hypothesis` (MPL-2.0, dev only) | M1 |
| ADR-0016 | Weekly single dependency PR, vulnerability SLA, retirement of the eligibility classifier; reconciles the 2026-10-19 "advisory" image-CVE note | M1 |
| ADR-0017 | Prompt lock, changelog and pins | M2 |
| ADR-0018 | Health endpoint aliases (expand/contract with `vps-ops`) | M3 |
| ADR-0019 | SQLite fixture profile and legacy evaluation-envelope scripts: retire or keep (owner decision PVA-D12) | M4 |

Existing ADR-0001 to ADR-0009 keep their paths and gain a MADR "Confirmation" section (how the decision is verified) in the M3 docs PR. ADR-0001 (modular monolith on SQLite) is partly superseded by ADR-0009 (PostgreSQL and graph) and must say so in both directions.

## 9. Migration order (each step ends green on develop)

1. Safety net first (M2): cassette lane and golden set, coverage and mutation baselines, import-linter contracts in warn mode, complexity ratchet file.
2. Mechanical, repo-wide, no behaviour: ruff 100 columns and double quotes (one PR, `.git-blame-ignore-revs`), then the extended rule families fixed in one pass.
3. Fix small defects (M3): clock injection, logging, health aliases, openapi completeness, docs moves.
4. Structural (M4): decompose in the order `create_app`, `fail_closed`, `chat.start`, `finalize`, analytics router, then the remaining eleven; enforce contracts with an empty baseline; convert the `.cjs`.
5. Never in the same PR: a refactor and a behaviour change; a prompt change and a layout change; a contract change and a refactor.

## 10. Server and client boundaries

The consumers are first-party and owned elsewhere (storefront, backoffice). The API publishes snapshots (`openapi*.json`, JSON Schemas, SSE examples) and never imports a consumer. Cross-repo reads (`pequeverso`, `pequeverso-backoffice`, `vps-ops`, `portfolio-assistant-api`) stay read-only, as in AGENTS.md; this plan edits only `docs/master-plan/` and, later, this repository.
