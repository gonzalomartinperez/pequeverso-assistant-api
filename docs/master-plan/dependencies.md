# Dependencies — pequeverso-assistant-api

78 locked packages (`uv.lock`), 16 direct runtime and 4 direct development dependencies (`pyproject.toml`). Policy: ecosystem section 7 "Dependency policy" and `research/10-standards-dependencies.md` topic B: a dependency needs a reason over platform or own code, health evidence, an allowed licence (MIT, Apache-2.0, BSD, ISC, 0BSD, BlueOak), a known exit cost; exceptions are ADRs (ADR-0015).

How to read the columns. Licence: the packages' declared licences as known when writing; the licence check job (M1, `pip-licenses` or `uv` metadata against the allow-list) is the authority and fails the weekly PR on drift. Health (2026): not re-measured in this audit; Scorecard and deps.dev values are collected once in M1 into `docs/reference/dependency-health.md` and re-read quarterly (ecosystem 16). "Security" is what the audit measured: the only advisory found in the lock is certifi (P0-1); the image scan found nothing in other Python packages.

## 1. Current runtime dependencies

| Package (pin) | Purpose | Alternatives considered | Cost | Licence | Decision |
|---|---|---|---|---|---|
| `fastapi>=0.143.3` | HTTP, SSE, schemas, OpenAPI | Starlette alone, Litestar | core; native SSE since 0.135 (`research/02`) | MIT | keep |
| `uvicorn>=0.54.0` | ASGI server, single worker by design | hypercorn, granian | small | BSD-3-Clause | keep |
| `httpx>=0.28.1` | catalog source and official-help fetches | `requests`, aiohttp | small | BSD-3-Clause | keep |
| `requests>=2.34.2,<3` | imported in `adapters/observability/telemetry.py`; also required by the OTLP HTTP exporter | httpx (the exporter still needs `requests`) | already present transitively; direct pin documents the import | Apache-2.0 | keep; two HTTP clients accepted because the exporter forces one |
| `pydantic>=2.14.1,<3`, `pydantic-settings>=2.16.0` | wire models, frozen settings with `SecretStr` | dataclasses plus manual validation | core | MIT | keep |
| `langgraph==1.2.16`, `langchain-core==1.6.12` | bounded retrieve-then-answer graph and Documents, confined to `adapters/graph` | plain async functions | heavy transitive tree; confined by import-linter | MIT | keep; revisit if the graph stays two nodes (ADR-0009 owns the choice) |
| `langsmith==0.14.9` | offline synthetic evaluation client; `tracing_context` forces tracing off at runtime; required by langchain-core | none (transitive) | transitive; runtime tracing disabled and tested | MIT | keep; never enable runtime tracing (AGENTS.md) |
| `openai>=3.33.0` | Responses API and embeddings behind the provider port | provider-neutral SDK, raw httpx | core; retries disabled by configuration | Apache-2.0 | keep |
| `psycopg[binary,pool]==3.3.6`, `psycopg-pool==3.3.3` | PostgreSQL 18 access, pool | asyncpg (BSD-style, no pgvector adapter parity), SQLAlchemy | core; `binary` bundles libpq | **LGPL-3.0** | keep with ADR-0015 exception: dynamic use as a library, no modification, no static linking; no permissive equivalent with the same maturity; owner confirms (PVA-D15) |
| `neo4j==6.4.1` | Bolt driver for the public projection | py2neo (archived) | core; telemetry and auto-commit retries explicitly disabled | Apache-2.0 | keep |
| `opentelemetry-sdk>=1.45.1`, `opentelemetry-exporter-otlp-proto-http>=1.45.1` | optional private telemetry | none needed | opt-in (`OBSERVABILITY_ENABLED`) | Apache-2.0 | keep; `gen_ai.*` attributes centralised in one module (ecosystem 17) |
| `prometheus-client>=0.26.0` | private `/internal/v1/ops/metrics` | OTel metrics only | small | Apache-2.0 | keep |

The version style is mixed (exact pins for the LangChain family, psycopg and neo4j; lower bounds for the rest). With `uv.lock` committed and `uv sync --locked`, the lock decides; lower bounds stay as declared minimums and the weekly PR moves the lock.

## 2. Current development dependencies

| Package | Purpose | Licence | Decision |
|---|---|---|---|
| `pytest>=9.1.1` | test runner | MIT | keep |
| `mypy>=2.4.0` | `--strict` gate (serial) | MIT | keep; Pyrefly added as a non-blocking second checker |
| `ruff>=0.17.1` | lint and format | MIT | keep; rule set widened, 100 columns, double quotes (M2) |
| `types-requests>=2.33.0.20261006` | stubs for `requests` | Apache-2.0 | keep |

Finding: `tests/test_ci_profile.py` and `tests/test_container_layout.py` import `yaml`, which is only present because `langchain-core` depends on `pyyaml`. Declare `pyyaml` (MIT) and `types-PyYAML` in the dev group (M1) so removing LangChain cannot break the tests.

## 3. Proposed additions (all dev, CI or eval; none enters the runtime image)

| Package or tool | Group | Purpose | Alternatives | Cost | Licence | Decision |
|---|---|---|---|---|---|---|
| `coverage[toml]`, `pytest-cov` | dev | line and branch coverage, combine data from two jobs | none better | small | Apache-2.0, MIT | adopt (M2) |
| `diff-cover` | dev | diff coverage ≥ 90% | Codecov/Qlty (hosted, commercial) | small | Apache-2.0 | adopt (M2) |
| `pytest-xdist`, `pytest-randomly` | dev | parallel and random-order runs | `pytest-flakefinder` | small | MIT | adopt (M1); markers for the unit lane |
| `import-linter` | dev | layer, forbidden-package and independence contracts | `tach` (status unconfirmed), AST test only | small | BSD-2-Clause | adopt (M2) |
| `vulture` | dev | dead-code check | none | tiny | MIT | adopt (M2) |
| `hypothesis` | dev | property tests (`testing.md` section 4) | hand-written examples | medium | **MPL-2.0** (file-level weak copyleft, dev only, never shipped) | adopt with ADR-0015 exception |
| `mutmut` (3.x) | mutation group | mutation testing on scoped modules | cosmic-ray | slow runs; Python 3.14 and `forkserver` compatibility unverified (spike) | BSD-3-Clause | adopt after spike (M2) |
| `schemathesis` | dev | OpenAPI fuzzing with stateful links | hand-written cases | medium | MIT | adopt (M2) |
| `locust` | load group | SSE load (httpx streaming) | k6 + xk6-sse | medium; one half-day spike to confirm | MIT | adopt (M2) |
| `time-machine` | dev | frozen time in clock tests | freezegun | tiny | MIT | adopt (M2) |
| `pytest-benchmark` | dev | micro-benchmarks of pure functions | none | tiny | BSD-2-Clause | adopt (M3) |
| `ranx` | eval group | recall, nDCG, MRR, paired tests | metrics already in `scripts/evaluate_corpus.py` plus SciPy bootstrap | heavy (numba); numba on CPython 3.14 unverified | MIT | adopt after a 30-minute spike; fallback in-house (M2) |
| `pytest-recording` / `vcrpy` | dev | only for the OpenAI adapter's own HTTP tests if wanted | custom port-level cassette (adopted for the gate) | small | MIT | optional |
| `pytest-repeat` | - | flake loops | shell loop with `-p randomly` | - | MPL-2.0 | **not adopted** (a loop does the job without a new dependency) |

CI tools (no Python dependency): `oasdiff` (Apache-2.0), `gitleaks` (MIT), `zizmor` (MIT), `actionlint` (MIT), Grype and Syft (Apache-2.0), hadolint (GPL-3.0, run as a binary in CI, never linked), dockle and container-structure-test (Apache-2.0), `promtool` (Apache-2.0), OWASP ZAP baseline (Apache-2.0), `release-please` (Apache-2.0), `lychee` (Apache-2.0/MIT), `markdownlint-cli2` (MIT).

Not adopted, with reasons: **structlog** (the in-repo allowlist formatter enforces event schemas and field allowlists, which structlog does not give; replacing it adds a dependency and removes a guarantee; PVA-D7); **promptfoo** (Node toolchain, OpenAI-owned, graders already exist in Python; PVA-D16); **Braintrust, Langfuse, Phoenix** (a second eval platform is unnecessary; datasets live in the repo, `research/03` section 13); **svcs or any DI framework** (explicit wiring in `bootstrap`); **Biome and a `package.json`** (three TypeScript files, `target-state.md` section 7).

## 4. Update flow

All of the above update through the single weekly Dependabot PR (`ci-cd.md` section 5). `uv` uses `exclude-newer = "7 days"` and `uv sync --locked` in CI and images; lockfile diffs are reviewed by the weekly review skill; any new runtime dependency passes an ADR with the template in `research/10-standards-dependencies.md`. The Python base image stays on 3.14.x by an `ignore` rule until the fleet policy adopts 3.15.
