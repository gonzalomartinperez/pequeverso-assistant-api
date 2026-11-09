# Testing — pequeverso-assistant-api

Applies ecosystem section 11 (11.0 catalog, 11.1 Assistant API column, 11.2, 11.3) and section 12 for AI quality. Baseline: 1,698 passed and 45 skipped in 248.8 s serial; line coverage 84.95%, branch 76.5% (local, services absent); mypy strict 0 errors; no mutation, property, contract-diff, fuzz or load tests (`audit.md`). Research: `research/04-testing.md` section "C. FastAPI assistant APIs", `research/03-rag-evals.md`.

## 1. Layers and numeric targets (ecosystem 11.1, Assistant API column)

| Layer | Target | Baseline | Cadence |
|---|---|---|---|
| Static | ruff (ecosystem families) 0 findings, `mypy --strict` 0, vulture clean, import-linter 0 violations, complexity ratchet | ruff 0 on current narrower set; mypy 0; others not run | PR |
| Test mix by count | 20% unit / 60% integration / ≤ 5% SSE smoke and non-functional; markers `unit`, `integration`, `service` so the split is measured, not asserted | not classified (about 100 test modules) | report per PR |
| Branch coverage, whole repo | floor 85%; the floor starts at the first **combined** measurement (static job plus `database` job via `coverage combine`) and only rises; interim hard floor 76% (today's local value), valid until the M4 exit (2026-12-11); PVA-M4.12 raises branch coverage to ≥ 85 and `ratchets/coverage.json` holds 85 from then (checked at PVA-M6.5) | 76.5% local; combined unknown | PR (floor), nightly (report) |
| Diff coverage | ≥ 90% via `diff-cover` against `origin/develop` | none | PR |
| Mutation | mutmut 3 (`forkserver`) on `app/domain/`, `app/application/answers.py`, `app/application/sessions.py`, `app/ai/prompt.py`, `evidence.py`, `output.py`, `app/domain/budget.py`, `app/application/embedding_budget.py`: PR runs changed files only, break 60; weekly full scoped, target 75 | none | PR incremental, weekly full |
| Property-based | Hypothesis, profile `ci` 100 examples on PR, `nightly` 1000 | none | PR, nightly |
| Contract | `openapi.json` and `openapi.internal.json` committed; `oasdiff breaking` blocks PRs; Schemathesis 50 examples per operation on PR, 500 nightly, explicit OpenAPI links for 3 stateful flows; no Pact while both consumers are first-party | `contracts.export --check` drift only | PR, nightly |
| E2E | SSE conformance: frames, heartbeat, terminal event, disconnect cancels the run and releases spend, resume behaviour pinned (`Last-Event-ID` is not part of the v1 contract; the test pins the documented behaviour) | `tests/test_streaming.py`, `test_runtime_shutdown.py` | PR |
| Load | Locust (Python, `httpx` streaming), fixture provider as "stubbed model": time to first event p95 < 1.5 s, inter-event gap p95 < 500 ms, error and premature close < 0.5%, 12 concurrent streams (3 times the global generation slot of 4, `docs/explanation/security.md`), RSS growth < 20% over 15 min | none | nightly, release |
| Security | authz matrix on every registered mutating route (section 3), rate-limit tests, secret redaction | `tests/test_security.py`, budget and rate-limit tests exist | PR |
| Integration data | real PostgreSQL 18 + pgvector and Neo4j 5.26 in the `database` job; Neo4j fixture reset with `DETACH DELETE`; suite < 90 s excluding image build; random order; migration test | `database` job exists | PR |

Pragmatism: the service has no UI, so visual, accessibility, Lighthouse and browser E2E rows are not applicable (reasons in section 2).

## 2. Every row of the ecosystem test catalog (11.0), mapped

| # | Family | Test types (catalog) | Applies | Tool | Scope and threshold | Cadence |
|---|---|---|---|---|---|---|
| 1 | Correctness | unit; integration with real DBs; component; architecture | yes (component: n/a, no UI) | pytest 9, pytest-xdist, pytest-randomly; PostgreSQL and Neo4j containers in the `database` job; import-linter and AST guard | mix 20/60/≤5; PR critical path ≤ 5 min p50 (unit lane with xdist at M1, measured against 249 s serial) | PR |
| 2 | Test quality | mutation; branch and diff coverage; flake detection | yes | mutmut 3, coverage.py with branch, diff-cover, pytest-repeat | section 1 numbers; flake detector `--count 3` on the unit lane nightly; 0 flaky in required checks over 30 days | PR, weekly, nightly |
| 3 | Input space | property-based; API fuzzing; parser fuzzing | yes | Hypothesis, Schemathesis | 10 properties (section 4); parser targets: SSE framing, price and amount parsing, language detector, redaction | PR 100, nightly 1000 |
| 4 | Contracts | schema tests; breaking-change detection; SSE conformance; event schemas | yes | oasdiff, JSON Schema validation of `contracts/*.schema.json`, pydantic, `contracts.export --check`, consumer-compile job (storefront and backoffice types against the new spec, run from those repos) | `oasdiff breaking` = 0 without `contract-major`; examples validate against schemas; closed event set | PR (contract profile) |
| 5 | End to end | journeys; checkout hand-off; auth journeys; cross-browser | partly | pytest with `TestClient` and the real uvicorn server fixtures (`tests/test_streaming.py`) | session, CSRF, stream, cancel, replay journeys; no browser (API); checkout hand-off belongs to the storefront | PR |
| 6 | Visual | screenshot regression | not applicable | - | no rendered UI in this repo; the dated native-assistant screenshots in `docs/verification/` are historical evidence, not tests | - |
| 7 | Accessibility | axe, keyboard, reflow | not applicable | - | no UI; accessibility of the widget is tested in `pequeverso` | - |
| 8 | Performance | Lighthouse; bundle; RUM; API latency p95; TTFT | partly (API latency, TTFT) | pytest-benchmark for pure functions (`check_answer`, `rank`, `finalize`); latency and time to first delta asserted in the golden live lane | `check_answer` p95 under 5 ms for a 2 KB answer (to be baselined); live lane p95 < 8 s, TTFT per `assistant-quality.md` section 10; no Lighthouse or RUM | PR (micro), release (live) |
| 9 | Load and resilience | load, stress, soak; dependency failure | yes | Locust; fault-injection fixtures | load as section 1; fault tests for PostgreSQL down, Neo4j down (degrade to verified PostgreSQL evidence, ADR-0009), provider timeout, budget exhausted, rate limit; each with the expected degraded response | nightly (load), PR (faults) |
| 10 | Security | SAST; secrets; deps and licences; container scan; DAST; authz matrix; CSRF/Origin; session; headers; leak checks; prompt-injection and red team | yes | CodeQL (Python, default setup), gitleaks, dependency-review, osv-scanner, Grype, OWASP ZAP baseline against the container, pytest, in-repo red-team pack | matrix covers 100% of mutating routes; red team 40 to 60 attacks; Grype fails on fixable High or Critical; ZAP baseline 0 high | PR, nightly (ZAP), daily (osv) |
| 11 | AI quality | golden set; deterministic graders; retrieval metrics; judge validation; prompt-version regression | yes | `evals/` runner, graders from `app/domain`, ranx, cassettes, independent agent judge | `assistant-quality.md`: golden 100%, full-set ratchets, judge TPR ≥ 0.90 and TNR ≥ 0.85 | PR (cassette), pre-release (live) |
| 12 | Data | migrations; idempotency; seed safety; restore drill | yes (drill is `vps-ops`) | pytest on real PostgreSQL; `scripts/smoke_knowledge_postgres.sh` (restore) | six forward-only SQL migrations: apply on empty, apply on N-1 with data, re-apply is a no-op; indexing idempotent; backup restore test already in the `database` job | PR |
| 13 | Build and runtime | container structure; image smoke; hosting contract; post-deploy verification | yes | container-structure-test, `scripts/smoke_container.sh`, hadolint, dockle | user 65532, labels present, no pip or shell tooling, read-only root works with tmpfs, health 200, graceful shutdown; image size ratchet | PR (image profile), release |
| 14 | Infrastructure | host baseline; Ansible; compose/Coolify config; drift | mostly n/a | promtool and JSON validation for `deploy/monitoring/*` | host and compose belong to `vps-ops`; here only application-owned monitoring artefacts are validated | PR (when touched) |
| 15 | Content and SEO | copy invariants; Spanish locale checks; structured data; sitemap | partly | graders `variety.neutral`, `claims.*`, lychee for docs | invented prices and claims: 0 (golden); voseo and Spain-only forms: 0 in Spanish answers; SEO and structured data n/a (API) | PR |
| 16 | Time and concurrency | frozen time; timezone; races | yes | `Clock` port, `time-machine`, concurrent pytest | price freshness at the configured window (the corpus uses 7 days) with boundary tests; budget reservations race (`test_budget_concurrency.py`); one active run per session; Dependabot timezone is CI config not code | PR |
| 17 | Observability | log redaction; metrics contract; request-id propagation | yes | pytest | no PII or secrets in any log line (property test over generated messages); `/internal/v1/ops/metrics` contract test; `x-request-id` echoed, logged, propagated | PR |
| 18 | Harness | skill activation evals; docs checks; drift; CI profile coverage | yes | `scripts/validate_skills.py`, activation evals (`skills.md`), lychee, markdownlint, `tests/test_ci_profile.py` | every tracked path falls in at least one profile in `ci-profile.json`; 6 skills with 20-query trigger sets | PR (harness profile) |
| 19 | Production synthetics | uptime and journey probes | Phase V only | Uptime Kuma probe of `/readyz` and `/api/v1/availability` (read-only) | no synthetic generation probe: it would spend money on every probe | MV |

## 3. Security matrix

A test enumerates every registered route from the FastAPI app (not from a hand-written list) and fails if a mutating route is missing from the matrix. Routes today: `POST /api/v1/session`, `DELETE /api/v1/session`, `POST /api/v1/messages`, `POST /api/v1/runs/{run_id}/cancel`, the analytics ingest `POST`, plus read routes under `/internal/v1/ops/*` and `/internal/v1/ops/product-analytics` (bearer tokens).

| Check | Applies to |
|---|---|
| Unauthenticated or missing session cookie gives the documented 401 or 403 code | session-bound routes |
| Origin not allowlisted gives `origin_denied` | every mutating public route |
| Missing or wrong CSRF header gives `csrf_failed` | every mutating public route |
| Run id of another session on cancel gives the same response as an unknown id (no object oracle) | cancel |
| Mass assignment: extra fields rejected (`extra="forbid"`) | all request bodies |
| Session tamper and logout invalidation | session |
| Bearer token missing, wrong, empty and timing-safe compare | internal routes |
| `/internal/*` unreachable through the public prefix | routing |
| Rate limits per client and per session (20 sessions per hour, 30 messages per day, 60 per hour) | session and messages |
| Secret redaction: no key, token or cookie in logs, `repr` or exception text (secret-serialization audit with `SecretStr`) | all |

## 4. Property-based targets (Hypothesis)

| # | Property | Module |
|---|---|---|
| 1 | Formatting an amount in es-ES (`1.299,00`), en (`1,299.00`) and plain forms and parsing it back yields the same `Decimal` | `answer_policy._amount` |
| 2 | `check_answer` never accepts an amount and currency pair absent from `known_price_pairs`, for any generated text containing one | `answer_policy` |
| 3 | `fold` is idempotent and accent-, case-insensitive | `answer_policy.fold` |
| 4 | Language detection is invariant under case and accent stripping for a vocabulary of known sentences | `language.detect` |
| 5 | Budget reservations never exceed the cap under any interleaving of reserve, settle and release (stateful machine) | `domain/budget.py` |
| 6 | SSE: `parse(render(event)) == event`; only members of the closed event set render | `presentation/streaming.py`, `events.py` |
| 7 | Redaction is idempotent and no generated e-mail or phone survives | `domain/redaction.py` |
| 8 | Catalog diff is symmetric: `diff(a, b)` empty iff `a == b` | `application/catalog_diff.py` |
| 9 | Idempotency fingerprint is deterministic and changes with every field including the native language policy | `application/chat.py` |
| 10 | Session lifecycle state machine (create, message, cancel, expire, delete) never reaches an invalid state and never leaks across sessions | `application/sessions.py` |

## 5. Mutation plan

Tool: mutmut 3. Compatibility with CPython 3.14 and `forkserver` is unverified; M2 starts with a one-hour spike, fallback `cosmic-ray` or scoped manual mutants of `answer_policy` regexes. Regex-heavy modules (`answer_policy.py`, `page_claims.py`) have equivalent-mutant noise; survivors are triaged once and the equivalent ones recorded in a reviewed list. Gate: PR break 60 on changed files, weekly target 75, ratchet file `ratchets/mutation.json`; thresholds are raised only after the baseline run. Budget: 30 min PR, 90 min nightly or weekly (reduce scope before lowering the score).

## 6. Flake policy (ecosystem 6.3)

No blanket retries. Tests that need services run in the `database` job with health-gated fixtures, never sleeps. A flaky test gets an issue labelled `flaky`, is moved to `tests/quarantine.txt` the same day (non-blocking job), and is fixed or deleted within 7 days; cap 2% of tests or 5. `pytest-randomly` runs on every PR from M1; a first-attempt failure rate above 2% over 20 runs on `main` stops feature work. Skips are reported by reason; a skip that is not service-gated needs an issue.

## 7. Where each lane runs

| Lane | Contents | Profile |
|---|---|---|
| `static` | ruff, mypy, import-linter, vulture, complexity ratchet, node `--test` for the TS tools, contracts drift | code |
| `unit` | `-m "unit"` with xdist, coverage data | code |
| `database` | PostgreSQL, Neo4j, migrations, restore, integration HTTP/SSE | code (affected paths) |
| `contract` | oasdiff, Schemathesis short, consumer compile | contract |
| `assistant-quality` | golden replay (100%), red-team pack, full-set fixture lane vs baseline | assistant-quality |
| `container` | build once, structure tests, smoke, Grype, SBOM | code when Docker or deps change; always on release |
| `nightly` | full mutation or last green within 24 h, Schemathesis 500, Hypothesis 1000, flake detector, Locust, ZAP, osv and Grype on digests, scorecard re-score | nightly |
