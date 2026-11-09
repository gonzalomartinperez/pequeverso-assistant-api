# Best-in-class Python service architecture and tooling, November 2026

Research date: 2026-11-09. Scope: two FastAPI + LangGraph GraphRAG assistant APIs (pgvector + Neo4j, SSE, read-only advisor, LLM spend budget) and vps-ops (single-VPS ops tooling). Current stack: uv, ruff, mypy, pytest, custom AST layering guard, Protocol ports, no DI framework.

Method note: sources were fetched in Nov 2026. Primary sources (docs, PyPI, repo files) are preferred; blogs are flagged. Items marked **[COMM]** have a commercial interest. Where only a secondary source supports a claim it is labelled "secondary". Version numbers come from PyPI/GitHub pages read on the research date.

---

## 1. Snapshot of the ecosystem (verified versions)

| Component | Version / status (Nov 2026) | Source |
|---|---|---|
| Python 3.14 | bugfix, 3.14.10 (2026-10-25); free-threaded build officially supported (PEP 779) | python.org downloads, What's New 3.14 |
| Python 3.15 | released 2026-10-09, 3.15.2 | python.org downloads |
| FastAPI | 0.162.2 (2026-11-07), classifiers 3.10-3.14, no free-threaded classifier | PyPI |
| LangGraph | 1.2.20 (2026-11-05), Python >=3.10 | PyPI |
| ruff | 0.17.4 (2026-11-05) | PyPI |
| import-linter | 2.16 (2026-11-06), Python >=3.11, classifiers up to 3.15 and free-threading | PyPI |
| ty (Astral) | 0.0.99 (2026-11-06), still 0.0.x, beta; baselines in preview since 0.0.93 | GitHub releases |
| Pyrefly (Meta) | 1.0.0 on 2026-05-12; 1.4.0 on 2026-10-14 (secondary) | GitHub / pydevtools |
| mypy | 2.0 (May 2026), experimental parallel checking via `--num-workers` | mypy changelog (secondary summaries) |
| dependency-injector | 4.49.0 (2026-03-22) | CERN mirror (secondary) |
| FastAPI SSE | native `fastapi.sse.EventSourceResponse`, since 0.135.0 | FastAPI docs |

Structural event to price in: **OpenAI announced the acquisition of Astral (uv, ruff, ty) on 2026-03-19**, with both parties committing to keep the tools open source; terms undisclosed, subject to regulatory approval. Permissive licences keep a fork possible. This is a supply-chain/governance risk to note, not a reason to leave uv or ruff.

---

## 2. Architecture: clean/hexagonal for FastAPI + LangGraph

### 2.1 Where LangGraph sits

No authoritative standard exists. The LangGraph docs describe a graph as an application whose nodes "can contain arbitrary code", and provide a `Runtime[ContextSchema]` / `context_schema` mechanism for passing dependencies (model, DB handle) into nodes "without putting them in graph state". That mechanism is the framework's own DI seam and maps cleanly onto hexagonal ports. Community write-ups place LangGraph orchestration inside the application layer (nodes/graphs/agents folders) and wire adapters through FastAPI DI (secondary, DEV Community posts; quality varies).

Recommended mapping (my synthesis, consistent with the docs above):

```
src/<pkg>/
  domain/          pure types: Product, Evidence, Citation, Budget, Money, errors   (no I/O, no pydantic-ai/langgraph imports)
  ports/           Protocols: LLMPort, EmbeddingPort, VectorStorePort, GraphStorePort,
                   SpendLedgerPort, ClockPort, CheckpointerPort (thin)
  application/     use cases (AdviseShopper, AnswerQuestion); the compiled graph lives HERE
    graph/         state.py (TypedDict/BaseModel), nodes/*.py, build.py (builds StateGraph from ports)
  adapters/
    llm/           anthropic/openai/fake
    vector/        pgvector via psycopg3
    graph/         neo4j async
    spend/         postgres ledger
  api/             FastAPI routers, SSE mapping, dependencies, error handlers
  platform/        settings, logging, telemetry, lifespan wiring (composition root)
```

Rules that matter more than the folder names:

1. **Nodes depend on ports, never adapters.** Pass ports via `context_schema` (a frozen dataclass `Deps`), not module globals and not graph state. State must stay serialisable (checkpointers), ports are not.
2. **The graph is an implementation detail of a use case.** The router calls `AdviseShopper.stream(request)` which returns an `AsyncIterator[DomainEvent]`; the SSE layer maps domain events to `ServerSentEvent`. This lets you test nodes with fakes, and swap LangGraph without touching the API.
3. **Spend budget is a port plus a pre-call guard**, not a callback buried in an adapter: `SpendLedgerPort.reserve(estimate) -> Reservation` before the LLM call, `commit(actual)` after. For a read-only advisor this is your main safety invariant; test it with property-based tests.
4. **Composition root in `platform/`**: one function `build_container(settings) -> Deps`, called from FastAPI lifespan. Tests build `Deps` with fakes.
5. **Checkpointer**: keep LangGraph's Postgres checkpointer behind `CheckpointerPort` only if you need to swap; otherwise accept it as a framework dependency inside `adapters/` and pass it at graph compile time.

Tradeoff: strict hexagonal costs indirection. Cosmic Python's stance (Percival and Gregory) is explicitly pragmatic: try patterns on a small project, goal is that technology choices become "minor implementation details", and the service layer makes entrypoints thin. For a read-only advisor with 3 external stores, ports for LLM, vector, graph and spend are justified; ports for "Clock" or "Settings" are not.

### 2.2 Enforcing the layers: import-linter vs custom AST guard

- **import-linter** (2.16, BSD-2, Python >=3.11): contracts for `layers`, `forbidden`, `independence`, `protected`, `acyclic_siblings`, plus custom contract types; configured in `.importlinter` / pyproject. It builds a graph of internal imports, so it catches **indirect** violations (A -> B -> C) that a per-file AST check misses. Active (release 4 days before research date).
- **Tach** (Rust, MIT): module boundaries with declared public interfaces, cycle detection, `tach show`, incremental adoption. Repo under `tach-org`, badges point to `gauge-sh/tach`; a fork called dtach claims tach is unmaintained (that claim comes from the fork, unverified). I could not confirm recent maintenance; treat as risky.
- **Custom AST guard** (what you have): flexible (can check "no `langgraph` import in `domain/`", "no `os.environ` outside platform", "no `datetime.now()`"), but it re-implements graph analysis and needs its own maintenance.

Recommendation: **keep the AST guard only for rules import-linter cannot express** (banned calls, banned third-party imports by layer, naming); move all layering, independence and "forbidden third-party in domain" rules to import-linter (it supports forbidden contracts with external packages when `include_external_packages = True`, verify in your version). Run both in CI and in pre-commit; make it part of `just check`. This removes the maintenance burden for the bulk of the rules and catches transitive imports.

---

## 3. Dependency injection: none vs framework

| Option | Fit | Notes |
|---|---|---|
| **No framework, composition root + `Deps` dataclass** (your current) | Best default for 2 services of this size | Explicit, typed, trivially mockable; works with LangGraph `context_schema`. |
| **FastAPI `Depends`** | Good at the HTTP edge only | Per-request scoping, overridable in tests via `app.dependency_overrides`. Keep it in `api/`; do not let `Depends` leak into application or domain code. The FastAPI settings docs recommend `Annotated[Settings, Depends(get_settings)]` with a cached `get_settings`. |
| **svcs** (Hynek) | Strong middle path if lifecycle management grows | Service locator with lifecycle (async cleanup, health pings), "no global state, no decorators, no signature changes"; integrations for FastAPI/Starlette/Flask/AIOHTTP. Registers factories; you `aget` services. Useful for pools (psycopg, Neo4j) with health checks. Locator, not pure DI, so keep lookups at the edges. |
| **dependency-injector** | Not recommended for new code | Production/stable, large download volume (117M total, secondary), last release seen 2026-03-22; wiring via `@inject`/`Provide[...]` pushes framework decorators into business code and has a history of friction with static typing. |

Recommendation: stay with explicit composition. Add **svcs only if** you find yourself hand-writing lifespan teardown ordering for more than ~4 resources (psycopg pool, Neo4j driver, LLM client, HTTP client, checkpointer). Otherwise lifespan + `AsyncExitStack` is simpler and has no dependency.

---

## 4. Typing: mypy strict vs pyright vs ty vs pyrefly

State as of Nov 2026:

- **mypy 2.0** (May 2026): experimental parallel checking (`--num-workers`), minor semantic differences between parallel and serial mode per the changelog, so keep serial for the gating CI job. `strict_bytes` default-on; drops `--python-version 3.9`. FastAPI itself uses `mypy strict = true` with the pydantic plugin **and** carries a `[tool.ty]` section, i.e. it is dual-running.
- **Pyright**: highest typing-spec conformance in the numbers I saw (95.7% in one source; 97.8% in another; 134/141 in a third; the sources disagree on absolute values but agree on ordering: pyright > pyrefly > ty/mypy, with Zuban reported highest). Slowest of the set on huge repos (144 s on pandas vs ~2 s for Rust checkers in one benchmark). Pydantic itself runs pyright on its package.
- **Pyrefly 1.x** (Meta, stable since 2026-05-12): 92.2% conformance (pydevtools, secondary), `pyrefly init` migrates mypy config, baseline files (described as experimental), `pyrefly infer`/`suppress`. Not supported by Pylance yet; Type Server Protocol announced. Stricter inference of container types than ty.
- **ty** (Astral, 0.0.99): beta, no 1.0 yet (searches found no 1.0 announcement); philosophy "adding annotations never introduces new errors", configurable return inference, baselines in preview. Conformance ~53-67% depending on the source. Astral being acquired by OpenAI is an extra strategic uncertainty (flagged by pydevtools).
- **Plugins**: neither ty nor pyrefly has a user plugin API; the **pydantic mypy plugin** has no equivalent. For pydantic-heavy code, pydantic v2's dataclass-transform support already makes plain pyright/pyrefly/ty adequate for models; the plugin mainly adds `init_forbid_extra`, `init_typed` and `warn_required_dynamic_aliases`.

Recommendation, ranked by risk:

1. **Keep mypy strict as the gating checker** (it already passes; the pydantic plugin; FastAPI does the same). Pin to 2.x, serial mode in CI.
2. **Add pyright (or basedpyright) in strict mode as a second gate** on `src/` only if you want a rigorous independent check; otherwise add **Pyrefly as a non-blocking advisory** job (it finds different bugs: pydevtools "ty and pyrefly find different bugs").
3. **Use ty in the editor** via uv/ruff-adjacent LSP for speed, not in CI until it hits 1.0 and passes your code with baselines off. Revisit in Q1-Q2 2027.
4. Do **not** switch the sole gate to a 0.x tool for a "95+" plan. If you want one checker for simplicity, pyright strict is the conservative alternative to mypy for greenfield code; Pyrefly 1.x is the credible fast option.

Set `--strict` plus: `warn_unreachable`, `enable_error_code = ["ignore-without-code","redundant-expr","truthy-bool","possibly-undefined"]`, `disallow_any_explicit` only on `domain/` and `ports/` (per-module overrides).

---

## 5. Ruff rule selection and docstrings

What top projects actually select (read from their pyproject files, Nov 2026):

- **FastAPI**: `E, W, F, I, B, C4, UP`; ignores `E501, B008, C901`.
- **Pydantic**: `F, E, I, D, UP, YTT, B, T10, T20, C4, PERF, PIE, PYI006, PYI062, PYI063, PYI066`; `pydocstyle.convention = "google"`; ignores `D105, D107, D205, D415, E501, B011, B028, B904, PIE804`.

Both are small, explicit sets. Ruff's own docs advise explicit `select` rather than `ALL` because `ALL` silently enables new rules on upgrade (secondary summary of the docs). There is a `FAST` rule group for FastAPI (FAST001 redundant response model, FAST002 non-Annotated dependencies, FAST003 unused path parameter).

Suggested baseline for these repos (a superset of the above, tuned for services):

```toml
[tool.ruff]
line-length = 100
target-version = "py313"   # match requires-python floor

[tool.ruff.lint]
select = [
  "E","W","F","I","B","C4","UP","SIM","RUF","PERF","PIE","PT","PTH","TC","ASYNC","S","T20","TRY","ARG",
  "FAST","LOG","G","DTZ","ERA","FURB","N","RET","D","ANN"
]
ignore = ["E501","B008","TRY003","D203","D213"]   # B008 only if using Depends defaults; prefer Annotated and drop it

[tool.ruff.lint.pydocstyle]
convention = "google"

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101","ANN","D","ARG"]
```

Why these: `ASYNC` catches blocking calls in async code (key for FastAPI + psycopg + Neo4j), `S` (bandit) for a read-only advisor with LLM tool use, `DTZ` for naive datetimes in spend budgets, `LOG`/`G` for logging misuse, `TC` for type-checking-only imports (also helps layering), `FAST` for FastAPI. Enable per family and fix incrementally, never `ALL`. Run `ruff format` (replaces black) and `ruff check --fix` in pre-commit; use `--preview` selectively only for rules you have verified.

### Google style guide vs PEP 8 + ruff

The Google Python Style Guide is stricter than PEP 8 on imports (import modules not names, no relative imports), 80-column lines, `Args:/Returns:/Raises:` docstrings, no mutable global state, no bare `except`, and recommends running pylint with Google's pylintrc and Black/Pyink. Ruff does not implement "import modules not names" (no rule enforces it). Practical stance used by pydantic: **PEP 8 + ruff with `convention = "google"` for docstrings only**, line length 88-100, not 80. Adopt the Google *docstring* format and its mutable-defaults/exception rules; do not adopt the 80-column or modules-only import rule. Require docstrings on public API of `ports/` and `domain/` (D1xx), relax elsewhere.

---

## 6. uv workflows, project layout, builds

- **Layout**: `src/` layout, one `pyproject.toml`, `uv.lock` committed, `.python-version` pinned, dependency groups (`[dependency-groups] dev`, `test`, `lint`, `types`) instead of extras for dev tooling. `uv sync --locked` in CI (fails if lock drifts), `uv sync --frozen` only in Docker intermediate layer.
- **Build backend**: `uv_build` is "a great choice for most Python projects" (pure Python only), expects `src/<name>/__init__.py`, and recommends an upper-bound pin (`uv_build>=X,<Y`). For an application that is never published, you may skip building wheels and run `uv sync --no-editable` in Docker; `uv build` is useful for vps-ops if you ship a wheel to the VPS.
- **Workspaces**: single lockfile, per-member `pyproject.toml`, `uv run --package`, intersection of `requires-python`. Docs say avoid workspaces when members have conflicting requirements or need separate venvs. Python does not isolate members, so a member can import another member's deps; use import-linter to enforce this (see 2.2).
- **CI**: `astral-sh/setup-uv`, cache keyed on `uv.lock`, `uv run --locked ruff check`, `mypy`, `pytest -n auto`. `uv lock --check` as a fast gate. `uv audit`/`pip-audit` (or `uv export | pip-audit`) plus Dependabot/Renovate for supply chain.
- **Task runner**: a `justfile` (readable, cross-platform, no `.PHONY` quirks) with `just check` (lint, format-check, types, import contracts, tests), `just fix`, `just up`, `just eval`. Makefile remains fine; the point is one documented entrypoint that CI calls identically.

---

## 7. Async data access

### psycopg 3 pool (pgvector)

From the psycopg docs: create `AsyncConnectionPool(..., open=False)` and `await pool.open()` in FastAPI lifespan, `await pool.close()` on shutdown (opening in the constructor is deprecated). Use:

- `min_size`/`max_size` sized per process (total connections = workers x max_size must stay under Postgres `max_connections`; on a single VPS keep this small, e.g. 2-10).
- `check=AsyncConnectionPool.check_connection` (added in 3.2) to validate before handing out.
- `max_lifetime`, `max_idle`, `reconnect_timeout`, and `reconnect_failed` for alerting.
- `configure=` callback runs on each new connection; this is where pgvector types are registered. pgvector-python documents `register_vector_async(conn)` for async psycopg connections and the `configure` pattern for sync pools; I found **no official example combining `AsyncConnectionPool` with `register_vector_async`**, so write one integration test that proves it works with your versions.
- Set `statement_timeout` and `application_name` in `kwargs`/`configure` for observability; use read-only DB role for the advisor (defense in depth with the "read-only" product rule).

### Neo4j async driver

Current driver line is 6.x (package name `neo4j`). Pattern (Neo4j developer docs [COMM, vendor] plus third-party): one `AsyncGraphDatabase.driver` per process created in lifespan, `await driver.verify_connectivity()` at startup, close on shutdown; never hold a global session; prefer `driver.execute_query(..., database_=...)` or managed transactions `execute_read`; pass the database name explicitly; use `neo4j+s://` for TLS/cluster, `bolt://` for a single local instance. Set `max_connection_pool_size`, `connection_acquisition_timeout`, `max_transaction_retry_time`. Enforce read-only at the Cypher level too: use `execute_read` and a read-only DB user.

### Concurrency and budgets

Wrap every external call with explicit timeouts (`asyncio.timeout`) and cancellation safety; pair SSE with disconnect detection so a closed client cancels the graph run and releases the spend reservation. FastAPI docs do not cover disconnect handling on the SSE tutorial page; test it.

---

## 8. SSE streaming

FastAPI 0.135+ ships `EventSourceResponse` / `ServerSentEvent` natively: yield from the path operation, JSON-encodes via the declared return type, supports `event/id/retry/comment`, `raw_data` for `[DONE]`, `Last-Event-ID` resume, and works with POST. It automatically sends a keep-alive ping after ~15 s idle and sets `Cache-Control: no-cache` and `X-Accel-Buffering: no`. If you use `sse-starlette` today, migrating removes a dependency, but check behavior parity (disconnect handling, ping interval, headers) with a contract test. Define a closed set of event types (`token`, `citation`, `tool`, `budget`, `error`, `done`) in `domain/` and mirror them in an OpenAPI/JSON-Schema doc for clients.

---

## 9. Pydantic v2 settings

Consistent guidance across sources (mostly blogs, plus FastAPI docs):

- `pydantic_settings.BaseSettings` with `model_config = SettingsConfigDict(env_file=".env.local", env_prefix="APP_", env_nested_delimiter="__", extra="forbid", frozen=True)`.
- `SecretStr` for every credential (keeps it out of repr/log/`model_dump`); use `secret-serialization` style review for dataclasses and spans.
- Nested sub-settings as plain `BaseModel`, `BaseSettings` only at the root.
- Required fields without defaults for fail-fast startup; `get_settings()` with `lru_cache`, or construct once in lifespan and inject (preferred: no hidden global).
- `Annotated[Settings, Depends(get_settings)]` at the HTTP edge only.
- Validate cross-field invariants (budget caps > 0, pool sizes sane) with `model_validator`.
- Use `SettingsConfigDict(secrets_dir=...)` or env for Docker/VPS secrets; never bake `.env` into images.

---

## 10. Observability: structured logging and OpenTelemetry

- **Logging**: `structlog` with `merge_contextvars`, ISO timestamper, a small custom processor that adds `trace_id`/`span_id` from the active OTel span (this is the pattern all sources converge on; no official built-in), JSON renderer in prod, console in dev; bind `request_id`, `session_id` (hashed), `graph_run_id` in middleware. Scrub secrets in a processor.
- **Traces**: `opentelemetry-instrumentation-fastapi` (`instrument_app`, `exclude_urls`, `exclude_spans=["send","receive"]` to cut SSE noise, header redaction via `..._SANITIZE_FIELDS`), plus psycopg and httpx instrumentation; Neo4j has no first-party OTel instrumentation I could verify, so wrap adapter calls in manual spans.
- **LangGraph/LLM**: GenAI semantic conventions (`gen_ai.*`) are still **Development** status. As of v1.42.0 (2026-06-12) they moved to a separate `semantic-conventions-genai` repo with no tagged release (Dash0 [COMM], Sept 2026; one promotional source claims stable, treat as wrong). Dash0's advice is sound: pin at the library, keep attribute strings in one module, capture content only in staging, record metadata (model, tokens, latency, error type) in prod. LangSmith [COMM] accepts OTLP and supports `tracing_mode` `langsmith | otel | hybrid`, and an OTel Collector gateway pattern for redaction (LangChain docs). Choose one primary: for privacy and portability, **OTel + Collector** with an optional LangSmith fanout; for dev ergonomics LangSmith native tracing is easier.
- **Metrics that matter** for the advisor: tokens in/out and USD per request, budget reservations vs commits, rejection count, retrieval latency (pgvector, Neo4j), graph node durations, SSE stream duration and abandonment.
- On a single VPS, an OTel Collector container plus Grafana/Tempo/Loki or a hosted free tier is enough; keep sampling at 100% for errors and budget events, 10-20% otherwise.

---

## 11. Packaging: Docker with uv

From the uv docs: pin the uv image tag (digest for reproducibility); `uv sync --locked --no-install-project --no-dev` in an intermediate layer with only `pyproject.toml`/`uv.lock` mounted; then copy source and `uv sync --locked --no-dev --no-editable`; cache mount `/root/.cache/uv`; `UV_LINK_MODE=copy`; `UV_COMPILE_BYTECODE=1`; multi-stage, copy only `/app/.venv` to the final image; `.venv` in `.dockerignore`.

Runtime base choice:

| Base | Pros | Cons |
|---|---|---|
| `python:3.14-slim` (Debian) | Familiar, shell for debugging, wheels just work | Larger CVE surface than distroless |
| Google distroless python | Minimal | Python version often lags (one source: debian12 variant ships 3.11); you must match builder Python; hard to debug |
| **Chainguard Python** [COMM] | No pip/shell/apk, nonroot default (uid 65532), daily-rebuilt, official `-dev` builder + minimal runtime pattern, uv image available | Vendor tie-in; free tier limited to certain tags/latest, pinned versions are paid (verify current terms); small ecosystem knowledge; no shell for debugging |

Recommendation: **multi-stage, Debian slim or Chainguard runtime, nonroot user, read-only root filesystem, `PYTHONUNBUFFERED=1`, `PYTHONDONTWRITEBYTECODE` off if you precompile bytecode, healthcheck via a tiny Python script or HTTP probe, `HEALTHCHECK`/compose healthcheck**, `tini` or `init: true`, Gunicorn+UvicornWorker or `uvicorn --workers N` sized to CPU (on a small VPS prefer 1-2 workers and async I/O). For a single VPS, slim + Trivy/Grype scan in CI is the pragmatic default; adopt Chainguard if you want near-zero CVE findings and accept the vendor dependency. Pin images by digest and sign/attest with cosign if you want a "perpetual excellence" supply chain story.

---

## 12. Python 3.14/3.15 and free-threading

- 3.14: free-threaded build **officially supported** (PEP 779; "Phase II"), single-thread penalty ~5-10% per What's New; not the default; whether it becomes default is an open future decision. Other 3.14 features of service relevance: deferred annotations (PEP 649/749; `from __future__ import annotations` becomes unnecessary and `annotationlib` is the introspection API; check Pydantic/FastAPI behavior in tests), t-strings, `asyncio ps/pstree` introspection and `capture_call_graph`, `forkserver` default for multiprocessing on Linux, Zstandard, and remote debugging (disable with `PYTHON_DISABLE_REMOTE_DEBUG` in prod if policy requires). **Incremental GC from 3.14.0-3.14.4 was reverted in 3.14.5**: pin >=3.14.5.
- Python 3.15 GA'd 2026-10-09 (3.15.2 now). Reasonable plan: production on **3.14** (latest 3.14.x), CI matrix adds 3.15 as non-blocking, move to 3.15 after the ecosystem wheels settle (typically mid-2027).
- **Free-threading relevance for I/O-bound FastAPI+LangGraph: low.** Throughput is bound by LLM/DB latency; async concurrency already handles it. FastAPI has no free-threaded classifier (PyPI), and a March 2026 report (single secondary source) said the 3.14t PR was still pending review. The py-free-threading tracker lists many deps (pydantic-core, psycopg, uvloop, cryptography, grpcio) as having ongoing work; one non-compatible C extension re-enables the GIL. Action: add a **non-blocking CI job on 3.14t** only for vps-ops or pure-Python pieces to keep an eye on it; do not ship free-threaded.
- JIT: experimental, not for production.

---

## 13. Sharing code across the two sibling assistant APIs

Options:

1. **Internal package** (`assistant-core`, versioned, in its own repo or published to a private index/GitHub Packages or git tag dependency in `uv`): shared ports, SpendLedger, SSE event models, settings base, telemetry setup, evaluation harness. Pros: one source of truth, semver, independent releases. Cons: cross-repo release friction; breaking changes need coordinated bumps.
2. **uv workspace monorepo** (one lockfile, `uv sync --package`): atomic cross-service changes, one CI. Cons: you must merge repos, and workspace needs a shared `requires-python`; different deploy cadences and separate GitHub rulesets/secrets get harder; docs warn that workspaces are not for conflicting requirements.
3. **Copier template** (`copier update` keeps downstream repos in sync with template changes, unlike one-shot cookiecutter): shares *scaffolding and config* (pyproject tooling, CI, Dockerfile, justfile, import-linter contracts, ruff config), not runtime code.

Recommendation: **combine 1 and 3**. Extract the genuinely shared runtime code (spend budget, SSE event schema, telemetry/logging bootstrap, settings helpers, port Protocols that are truly identical) into a small internal `assistant-kit` package consumed by git tag (or private index), with its own tests and contract tests that both APIs run against. Use **Copier** for the repo skeleton and CI/tooling parity, so the "95+ on every axis" bar propagates by `copier update`. Do not go monorepo unless the repos will always release together. Guardrail: the shared package must not import either app; enforce with import-linter, and keep it small (duplication of 30 lines is cheaper than a wrong abstraction).

---

## Recommendations for our repos

**Both assistant APIs**

1. Adopt the layout in 2.1; graph in `application/graph`, ports in `ports/`, Deps via LangGraph `context_schema`; domain events to SSE mapping in `api/`.
2. Move layering rules to **import-linter 2.x** (layers + forbidden external packages in domain + independence between adapters); keep the AST guard for call-level rules; both in `just check` and pre-commit.
3. Keep **no DI framework**; composition root in lifespan; consider svcs only if lifecycle code grows.
4. Typing: **mypy strict (2.x, serial) stays the gate**; add Pyrefly (or pyright strict) as a second, initially non-blocking job; ty in editor only. Re-evaluate ty at 1.0.
5. Ruff: explicit rule families from section 5 (incl. `ASYNC`, `S`, `DTZ`, `FAST`, `TC`), Google docstring convention, never `ALL`.
6. Data: psycopg3 `AsyncConnectionPool(open=False)` in lifespan with `check`, `max_lifetime`, `configure` registering pgvector (write an integration test); Neo4j async driver per process, `execute_read`, explicit database; both with read-only credentials and statement/transaction timeouts.
7. SSE: use native `fastapi.sse` (>=0.135), typed closed event set, disconnect cancels graph and releases spend reservation, contract test for headers/ping.
8. Settings: frozen `BaseSettings`, `SecretStr`, `extra="forbid"`, built once in lifespan.
9. Observability: structlog JSON + OTel trace correlation, OTel Collector, `gen_ai.*` attributes centralised in one module, content capture off in prod, spend metrics (tokens, USD, rejections).
10. Docker: multi-stage uv build per official docs, nonroot, read-only FS, digest-pinned images, scan in CI; Debian slim default, Chainguard optional.
11. Python: ship on 3.14 (>=3.14.5), 3.15 non-blocking in CI; no free-threading in production.
12. Sharing: `assistant-kit` internal package (git tag) + Copier template; no monorepo.

**vps-ops**

- Same ruff/mypy/uv/just baseline, `src/` layout, `uv_build` and `uv build` for a wheel (or `uv sync --no-editable` in image); import-linter with a simple `cli -> services -> adapters (ssh/docker/systemd) -> domain` layering; ports for `Shell`, `Clock`, `Filesystem` so commands are testable with fakes and a `--dry-run` default for destructive actions.
- It is the safest candidate for a **3.14t / free-threading experiment** (pure Python, few C deps), and for trying ty/Pyrefly as the primary checker, since blast radius is small.
- Structured JSON logs plus a run-id; emit OTel spans only if you already run a collector.

---

## Contested / uncertain

- **Which type checker is "best"**: conformance numbers differ by source (pyright 95.7-97.8%, Pyrefly 87.8-92.2%, ty 53-67%, mypy 58-60%); benchmarks come from vendors (Meta, Astral) or a single blog. Pyrefly's own speed numbers are Meta-run. Real-bug detection on *your* code differs from spec conformance.
- **ty 1.0 timing**: still 0.0.x at 0.0.99; "1.0 in 2026" is a stated target in secondary sources; I found no official announcement. With the OpenAI acquisition the roadmap is less predictable.
- **mypy 2.0 parallel mode**: secondary sources conflict on which release finalised `--num-workers`; the official changelog says serial/parallel differ semantically.
- **OTel GenAI conventions stability**: Dash0 and the Greptime post say Development; one promotional article claims stable. Treat as unstable; expect renames.
- **LangGraph placement**: no official hexagonal guidance; my layering is a synthesis from LangGraph's `Runtime`/`context_schema` design plus community posts.
- **Tach maintenance**: unclear; not recommended without checking recent commits.
- **dependency-injector** health: release cadence slowed (latest seen March 2026); I did not evaluate its typing story in 2026.
- **pgvector + psycopg AsyncConnectionPool**: no official combined example found; verify.
- **FastAPI free-threading**: single secondary source (March 2026) on a pending PR; no later confirmation; PyPI shows no free-threaded classifier.
- **Chainguard terms**: free/paid tag availability changes; verify before depending on it.
- **Astral/OpenAI**: open-source commitments are statements, not governance; keep tools pinned in `uv.lock`/CI and be ready to fork or swap (ruff -> ruff fork, uv remains permissively licensed).
- **Docker image size figures** in blog posts (80-180 MB) are unverified benchmarks.

---

## Sources

Primary / official

1. Python 3.14 What's New, https://docs.python.org/3/whatsnew/3.14.html (read 2026-11-09)
2. Python downloads (3.14.10, 3.15.2), https://www.python.org/downloads/ (2026-11-09)
3. PEP 779, https://peps.python.org/pep-0779/ (via discuss.python.org thread, 2025)
4. uv Docker guide, https://docs.astral.sh/uv/guides/integration/docker/
5. uv workspaces, https://docs.astral.sh/uv/concepts/projects/workspaces/
6. uv build backend, https://docs.astral.sh/uv/concepts/build-backend/
7. FastAPI SSE tutorial, https://fastapi.tiangolo.com/tutorial/server-sent-events/
8. FastAPI pyproject.toml, https://raw.githubusercontent.com/fastapi/fastapi/master/pyproject.toml
9. Pydantic pyproject.toml, https://raw.githubusercontent.com/pydantic/pydantic/main/pyproject.toml
10. PyPI: FastAPI https://pypi.org/project/fastapi/ ; LangGraph https://pypi.org/project/langgraph/ ; ruff https://pypi.org/project/ruff/ ; import-linter https://pypi.org/project/import-linter/ (all 2026-11)
11. ty releases, https://github.com/astral-sh/ty/releases (0.0.99, 2026-11-06)
12. Pyrefly releases, https://github.com/facebook/pyrefly/releases/tag/1.0.0 (2026-05-12)
13. import-linter docs, https://import-linter.readthedocs.io/en/stable/
14. psycopg 3 connection pools, https://psycopg.org/psycopg3/docs/advanced/pool.html
15. OpenTelemetry FastAPI instrumentation, https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html
16. Google Python Style Guide, https://google.github.io/styleguide/pyguide.html
17. Python free-threading tracker, https://py-free-threading.github.io/tracking/
18. LangGraph runtime context docs, https://docs.langchain.com/oss/python/langgraph/graph-api-nodes#add-runtime-configuration **[COMM: LangChain sells LangSmith]**
19. LangSmith OTel tracing / gateway / replicas, https://docs.langchain.com/langsmith/trace-replicas ; https://docs.langchain.com/langsmith/otel-gateway-trace-redaction **[COMM]**
20. pgvector-python README, https://github.com/pgvector/pgvector-python
21. Cosmic Python preface, https://www.cosmicpython.com/book/preface.html
22. svcs, https://svcs.hynek.me/ and https://github.com/hynek/svcs
23. Neo4j driver best practices, https://neo4j.com/blog/developer/neo4j-driver-best-practices/ ; Python manual performance page https://neo4j.com/docs/python-manual/current/performance **[COMM: Neo4j vendor]**
24. Tach repo, https://github.com/gauge-sh/tach (moved to tach-org; status unconfirmed)

Secondary / blogs (verify before relying)
25. pydevtools, "If you're on mypy in 2026, Pyrefly is the obvious upgrade" (May 2026), https://pydevtools.com/blog/pyrefly-1-0-is-the-obvious-mypy-upgrade/
26. pydevtools, ty vs Pyrefly, https://pydevtools.com/handbook/explanation/ty-vs-pyrefly/ (undated)
27. pydevtools, how type checkers compare, https://pydevtools.com/handbook/explanation/how-do-mypy-pyright-and-ty-compare/
28. pydevtools, mypy 2.0 parallel type checking, https://pydevtools.com/blog/mypy-2-0-parallel-type-checking/ (May 2026)
29. pydevtools, OpenAI to acquire Astral (2026-03-19), https://pydevtools.com/blog/openai-acquires-astral/ ; The New Stack, https://thenewstack.io/openai-astral-acquisition/ ; SiliconANGLE (2026-03-19)
30. pydevtools, how to check a FastAPI project (FAST rules), https://pydevtools.com/handbook/how-to/how-to-check-a-fastapi-project/
31. pydevtools, uv workspaces monorepo how-to, https://pydevtools.com/handbook/how-to/how-to-set-up-a-python-monorepo-with-uv-workspaces/
32. Pyrefly speed/memory comparison, https://pyrefly.org/blog/speed-and-memory-comparison/ **[COMM-ish: Meta project, self-benchmark]**
33. Dash0, OpenTelemetry GenAI semantic conventions explained (updated 2026-09-14), https://www.dash0.com/knowledge/opentelemetry-genai-semantic-conventions-explained **[COMM: observability vendor]**
34. Greptime, OTel GenAI conventions (2026-05-09), https://www.greptime.com/blogs/2026-05-09-opentelemetry-genai-semantic-conventions **[COMM]**
35. Coralogix LangGraph OTel integration, https://coralogix.com/docs/integrations/ai-observability/langgraph/ **[COMM]**
36. OneUptime, Chainguard Python + uv relocatable venv (2026-07-29), https://oneuptime.com/blog/post/2026-07-29-chainguard-python-uv-relocatable-venv/view **[COMM: observability vendor blog]**
37. Chainguard Python getting started / uv image, https://www.chainguard.dev/docs/chainguard/containers/getting-started/languages-and-runtimes/python/ ; https://images.chainguard.dev/directory/image/uv/overview **[COMM: Chainguard]**
38. OneUptime, distroless Python with venv (2026-02-17), https://oneuptime.com/blog/post/2026-02-17-how-to-build-a-distroless-python-container-image-with-a-virtual-environment-for-cloud-run/view **[COMM]**
39. Microsoft ISE, Dockerizing uv (2025-06-12), https://devblogs.microsoft.com/ise/dockerizing-uv/
40. DEV Community, hexagonal architecture in Python, https://dev.to/elpic/hexagonal-architecture-in-python-wiring-adapters-dependency-injection-and-the-application-layer-61l ; multi-agent LangGraph + hexagonal, https://dev.to/csotelo/building-a-multi-agent-atdd-pipeline-with-langgraph-and-hexagonal-architecture-5a9k
41. dependency-injector listing, https://simple-repository.app.cern.ch/project/dependency-injector (4.49.0)
42. DataCamp pyright tutorial (Jan 2026) **[COMM: training vendor]**, https://www.datacamp.com/tutorial/pyright ; basedpyright reference https://pydevtools.com/handbook/reference/basedpyright/
43. Free-threaded Python 3.14 articles: https://pydevtools.com/handbook/explanation/what-is-pep-779/ ; Cloudsmith blog **[COMM]** https://cloudsmith.com/blog/python-3-14-what-you-need-to-know
44. Copier vs cookiecutter material, https://ep2025.europython.eu/session/your-cookiecutter-is-wrong ; https://www.kunalganglani.com/blog/python-uv-workspace-monorepo
45. Structlog + OTel correlation examples, https://oneuptime.com/blog/post/2026-01-30-log-trace-correlation/view **[COMM]** ; https://ad-sdl.github.io/MADSci/otel-processors
46. FastAPI settings docs, https://fastapi.tiangolo.com/advanced/settings/ ; community config guides (dev.to 2026)

Discarded as unreliable: kubaik.github.io free-threading posts (conflicting dates), dev.to "FastAPI 0.115 PEP 737" article, dev.co import-linter description, businesstechnavigator "stable GenAI spec" claim.
