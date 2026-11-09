# 04 - Best-in-class testing strategy, 2026

Date: 2026-11-09. Scope: 2 public Next.js sites, 2 Next.js backoffices (OAuth/RBAC, better-auth), 2 FastAPI assistant APIs, 1 Python ops repo. Current baseline: node --test, Playwright (Chromium/Firefox/WebKit), axe, Lighthouse CI, pytest, partial Hypothesis, no TS mutation testing.

Method note: web research was done in one session. The WebSearch budget ran out before the last three planned queries (Neo4j/pgvector Testcontainers specifics, Pact critique, Google coverage-correlation study), so those topics rest on thinner evidence and are flagged. Items marked **[unverified]** came from secondary sources only. Sources with a commercial interest are tagged **[COMM]** in the source list. Numeric thresholds in the recommendation section are my judgment built on the evidence; they are not published standards unless stated.

---

## 1. Test shapes and per-layer targets

**What the sources say.** Kent C. Dodds' trophy (static base, few unit, mostly integration, few E2E) is explicitly scoped by its author to monoliths; he has not considered it for microservices [S1]. Spotify's honeycomb targets microservices: few implementation-detail tests, a thick middle of "integrated" service tests [S2]. web.dev's guide gives no ratios and says to pick by architecture, reserve E2E for critical journeys, and not chase coverage percentages [S2]. Rauch's line, quoted in both: "Write tests. Not too many. Mostly integration."

**Fit for this portfolio.** None of the 7 repos is a microservice mesh; each is a small app with one or two external boundaries (DB, OAuth provider, LLM). That makes the trophy the better default for the Next.js repos and a "honeycomb-lite" (thick API-level integration against real Postgres) the better default for the FastAPI repos. The Python ops repo is closer to a classic pyramid because it is mostly pure transforms plus I/O glue.

**Caveat for Next.js specifically.** The Next.js docs (v14/v15) state Vitest does not support async Server Components and recommend E2E for them [S3]. The current App Router page (v16.x) appeared without that caveat in search snippets, so it may have been trimmed; do not assume it was fixed [unverified]. Practical consequence: extract logic out of async RSCs into plain functions (unit/integration) and cover the RSC render path with Playwright.

**Per-layer targets (share of test count, by repo type)** - judgment, not a standard:

| Layer | Public Next.js | Backoffice Next.js | FastAPI API | Python ops |
|---|---|---|---|---|
| Static (tsc/ruff/ty/eslint, strict) | gate, 0 errors | gate | gate | gate |
| Unit (pure logic, parsers, validators) | 25% | 20% | 20% | 55% |
| Integration (real DB / route handlers / components in real browser) | 30% | 45% | 60% | 35% |
| E2E (Playwright, critical journeys) | 35% | 30% | 0-5% (SSE smoke) | 0% |
| Visual / a11y / perf (non-functional) | 10% | 5% | n/a | n/a |

Rule of thumb for E2E: cap at roughly 15-25 journey tests per Next.js repo, each under 30 s, and fail the plan if the E2E layer exceeds 10 min wall-clock after sharding.

---

## 2. Coverage policy vs mutation score

**Coverage proves execution, not detection.** Google's mutation work states coverage "is easily fooled, as it only determines whether code has been executed" [S4]. The widely cited 2014 ICSE paper (Inozemtseva and Holmes, "Coverage is not strongly correlated with test suite effectiveness") is the academic basis for this; I could not re-fetch it this session, so cite it from memory [unverified here]. Google also notes computing an absolute mutation score for its whole repo is infeasibly expensive, so it mutates only changed code at review time [S4]; the same paper family admits evidence that writing tests for mutants improves test quality is still limited [S4]. This matters: mutation score is a better signal than line coverage, but it is not proven to be a causal quality lever.

**Recommended policy (layered):**
1. **Line + branch coverage as a floor, not a goal.** Branch coverage on, enforced on the whole repo only at a modest floor (below), because floors catch deletions of tests, not weak tests.
2. **Diff (patch) coverage as the PR gate.** diff-cover's `--fail-under` is the standard open-source way; 80% on changed lines is a common documented policy and the CodeClimate default [S5]. This is cheap and fair to legacy code.
3. **Mutation score on changed code, plus scheduled whole-repo runs on risk modules only** (auth, RBAC, money/quota, parsers, prompt/guardrail logic). Not on UI glue.

**Mutants are noisy.** Trail of Bits states there is no formal threshold for equivalent mutants and relies on triage: clustered survivors suggest real bugs, isolated operator flips in utilities are probably low priority [S6]. So gate on a score with headroom, never on 100%.

---

## 3. Mutation testing tools

### 3.1 StrykerJS (TS/JS)

Verified facts from the official docs:
- Defaults: `thresholds` = high 80 / low 60 / break null (never fails unless you set `break`); `coverageAnalysis` = `perTest`; `timeoutFactor` 1.5, `timeoutMS` 5000; `ignoreStatic` default false and requires perTest [S7].
- **Incremental mode** (`--incremental`, file `reports/stryker-incremental.json`) re-tests only changed code/tests but still emits a full report; `--force` rebuilds. Reuse is most precise for runners that report test locations: Jest, Vitest and Cucumber [S8, S9].
- **Vitest runner**: single thread, bails on first failing test (unless `disableBail`), always perTest, no Browser Mode support; does not bundle vitest [S9].
- **node:test**: no dedicated runner. The `@stryker-mutator/tap-runner` accepts any runner emitting TAP, which the Stryker 7 announcement says includes the Node built-in runner, with coverage analysis and test filtering claimed [S10]. The generic `command` runner works with any runner but launches a fresh process per run and disables coverage analysis [S11]. I found no independent report of real-world tap-runner performance on node:test [unverified].
- **TypeScript checker**: drops mutants that do not compile. Since 6.4, grouping by dependency graph speeds it up to ~50% (43% measured on Stryker core at 99.1% accuracy); before that, Stryker on itself ran ~10x slower with the checker; grouping can be disabled with `prioritizePerformanceOverAccuracy: false` at the cost of speed [S12]. Note Stryker 7 flipped `disableTypeChecks` to default true [S10].
- Version drift: one blog and jsDelivr suggest a v10 exists (Aug 2026) while other listings show 9.x; I could not confirm which is current or whether the checker supports TS 6/7 [unverified].

**TS 7 interaction (inference).** TypeScript 7.0 (2026-07-08) ships the Go-native compiler as `tsc` with **no programmatic API until 7.1**; `@typescript/typescript6` keeps the old API for tools that need it [S13]. Stryker's checker uses the TS Compiler API (per [S12]'s dependency-graph description), so expect to alias TS 6 for the checker until 7.1. The TS 7 post does not mention Stryker [S13]; treat compatibility as something to prove in a spike, not assume. Vitest transforms through Vite and does not need the TS API for running tests (my inference, not verified against Vitest docs).

**Realistic thresholds/cadence for TS:**
- Scope with `mutate` to pure-logic and security modules; exclude `*.tsx`, route glue, config.
- PR job: `--incremental` with the incremental file cached between runs (CI cache or artifact), `break` = 60 on changed code initially.
- Nightly/weekly: full run on scoped modules, `high 80 / low 65 / break 60`. Public sources converge on 80% as a realistic top target and 60-70% as a starting break [S14, secondary blogs]. Do not go above 85 on a first adoption; the long tail is equivalent mutants.
- Budget: set a wall-clock cap (30 min PR, 90 min nightly) via scoping rather than lowering the score.

### 3.2 Python: mutmut 3 vs cosmic-ray vs mewt/muton

- **mutmut 3** (verified from README): fork-per-mutant from a parent that has already imported pytest; optional `forkserver` mode; tracks progress in `mutants/` so runs resume; runs only relevant tests per mutant; can skip mutants a type checker (mypy or pyrefly; not pyright/ty) rejects; `mutate_only_covered_lines`; POSIX only (WSL on Windows); pytest only; unstable timeout settings may change in minor versions; fork-unsafe libs (gevent, grpc, torch) can hang or give irreproducible results [S15]. FastAPI + async + DB drivers are exactly where fork-safety bites; use `forkserver`.
- **cosmic-ray**: import-hook based, plugin architecture, distributed execution; a 2026 arXiv paper picked it for operator control, and calls it and mutmut the two most actively maintained tools [S16, secondary]. A 2024-era academic comparison found mutmut results incomplete in its setup and cosmic-ray at 25.7% "competency" [S16, secondary; weak evidence]. Comparisons from pytest-gremlins and irradiate are written by competing-tool authors **[COMM]** [S16].
- **mewt/muton** (Trail of Bits, April 2026): language-agnostic Tree-sitter engine; mewt covers Solidity, Rust, Go and others; muton targets TON languages; SQLite state, SARIF export, pause/resume [S6, S17]. **Python and TypeScript are not in the stated language list**; do not plan on it for these repos. The Trail of Bits Claude skill is for configuring/analyzing campaigns and is useful as a triage method, not as the engine here [S17]. Trail of Bits is a consultancy with a commercial interest in the security-tooling narrative.

**Recommendation:** mutmut 3 as the default for FastAPI/ops (simple, resumable, pyproject config); keep cosmic-ray as the fallback if fork issues or the need for custom operators arise. Run mutmut only on `app/domain`, `app/auth`, guardrail/prompt-assembly and retrieval-ranking code. Cadence: weekly full on scoped modules, on-demand per PR for changed modules (mutmut has no native git-diff mode as far as sources show [S14, unverified]; script `only_mutate` from `git diff --name-only`). Target score 75% on scoped modules (break 60), lower than JS because async and DB code has more unkillable mutants.

---

## 4. Property-based testing

**Hypothesis** (latest 6.170.15, 2026-11-06; dropped Python 3.10, supports 3.15; internals migrating to Rust, so source builds need a Rust toolchain) [S18]. Practical setup, from the settings docs [S19]:
- Register `dev`, `ci` profiles and select with `HYPOTHESIS_PROFILE`.
- `derandomize=True` implies the example database is off, so a deterministic CI profile cannot also replay saved failures; choose deliberately [S19].
- Stateful default `stateful_step_count` is 50 [S19].
- Keep CI on a non-derandomized profile with the database persisted as a CI cache artifact if you want failures replayed, and use a derandomized profile only for required-merge gates where flake risk matters more than search power (my judgment).

**What to property-test in these repos:** parsers/serializers round-trip; RBAC permission lattice (monotonic: adding a role never removes access); pagination/cursor invariants; idempotency of ingestion jobs; prompt-assembly never exceeds token budget; SSE framing encode/decode.

**fast-check** (TS): has a Vitest connector (`@fast-check/vitest`, 0.4 line needs Vitest ^4.1) and a documented plain-API recipe for node:test with no connector [S20, S21]. Use `fc.assert(fc.property(...))` inside `test()`. Set `numRuns` 100 on PR and 1000+ nightly, and always log/seed failures (`seed`, `path`). The fast-check model-based API (commands) is relevant for backoffice session/state flows but I did not verify its docs this session [unverified].

**Schemathesis** is the bridge between Hypothesis and your OpenAPI (section 6).

---

## 5. Integration tests against real databases

**Pattern consensus** from guides: one container per test session, fixture-scoped isolation on top (transaction rollback for Postgres, or a clean schema per test; `DETACH DELETE` for Neo4j) [S22]. pgvector needs the `pgvector/pgvector` image rather than stock `postgres` (seen in a project conftest using `pgvector/pgvector:pg16`) [S22, secondary]. Migrations (Alembic) should run once per session against the container, which doubles as a migration test [S22].

**Gaps I could not close:** the official Testcontainers-Python docs I fetched do not list a Neo4j module or a container "reuse" feature (reuse examples found were Java `withReuse`) [S23]. Check `testcontainers-neo4j`/community modules and whether reuse exists in the Python lib before promising it. Alternative that avoids the question: GitHub Actions `services:` containers for Postgres/pgvector/Neo4j in CI, and a `docker compose` file for local; then Testcontainers is optional [judgment]. Ryuk (the cleanup reaper) can be disabled or privileged through env vars in locked-down CI [S23].

**Targets:** DB-backed integration suite under 90 s on CI; each test independent of order (run with `pytest -p randomly` or `--shuffle` equivalent); one dedicated migration test (upgrade to head, downgrade one, upgrade again); a pgvector test asserting recall@k on a seeded fixture for retrieval changes.

---

## 6. Contract testing between API and two consumers

Two approaches, per the sources: provider-driven (Schemathesis generating from the OpenAPI document and checking responses; oasdiff classifying spec changes as breaking) versus consumer-driven (Pact) [S24, S25]. Schemathesis stateful testing relies on OpenAPI links; with no links discoverable it skips the stateful phase by default, so a green CI run may not have exercised stateful flows; FastAPI does not emit links by default [S26]. oasdiff supports OpenAPI 3.1/3.2 and has a GitHub Action; the hosted PR-review workflow is a separate commercial offer [S27]. Critiques of Pact cost (one Speakeasy post: "an extra 20% of value for at least 2x the cost") come from a vendor selling OpenAPI tooling **[COMM]** [S24]; PactFlow bi-directional contracts are sold by a vendor too **[COMM]**.

**Recommendation for 1 API + 2 first-party consumers (same owner):** schema-driven, not Pact.
1. FastAPI emits `openapi.json`; committed snapshot in the API repo.
2. CI on every PR: `oasdiff breaking` against base branch (fail on breaking), `oasdiff changelog` in the PR comment.
3. Schemathesis against an ephemeral app instance with the real DB: `--checks all`, 50 examples per operation on PR, 500 nightly; add explicit `links` (via `add_link` or OpenAPI links) for the 3-5 stateful flows (create session -> post message -> stream -> delete) [S26].
4. Consumers generate typed clients from the committed spec and run their integration tests against an MSW/mock server generated from the same spec, so schema drift fails compile (tsc) rather than prod.
5. Add Pact only if a consumer becomes external or deploys independently with a different release cadence. Until then it is extra cost.

---

## 7. Playwright best practices (1.65 era)

Current Playwright is 1.65 (WebKit 27.2, Chromium 158, Firefox 159) [S28]. Features that matter:
- `failOnFlakyTests` (1.52) fails the run if any test passed only on retry; `retryStrategy: 'isolated'` (1.62) re-runs retries at the end in one worker; `--shuffle` (1.64); `--update-snapshots=missing` (1.64); WebP default screenshots (1.64) [S28].
- Official best practices: `getByRole` locators, web-first assertions, isolated tests, mock third parties with `page.route`, **trace on first retry on CI, not `on`** (very heavy), Linux on CI, install only needed browsers, lint `no-floating-promises` and run `tsc --noEmit` [S29].
- Retries are off by default; a test failing then passing is classed "flaky" [S30].
- Sharding: `--shard=x/y`, `fullyParallel: true` recommended so sharding is per test; use the `blob` reporter on CI and a merge job with `if: !cancelled()` [S31].

**Flaky policy (recommended):** `retries: 1` on CI only; `failOnFlakyTests: true` on `main` and release branches (warn on PRs for the first month); a flaky test gets quarantined (tagged `@quarantine`, run in a non-blocking job) within 48 h and fixed or deleted in 14 days; track flaky rate from the blob/JSON report; target under 1% of runs with a retry.

**Sharding:** enable once total CI time of the Playwright job exceeds about 8 min; shards = ceil(minutes/4), max 4-6 per repo; one project per browser in a matrix rather than every browser on every PR (see below).

**Browser matrix:** PR = Chromium + one iPhone WebKit profile on the critical-journey tag; nightly and release = Chromium, Firefox, WebKit desktop, iPhone and Pixel profiles. Device descriptors (`devices['iPhone 15']`) bundle viewport, UA, DPR, touch, and default to WebKit, but this is Playwright's own patched WebKit on the host OS, not Mobile Safari; keyboard, safe-area, memory pressure and real network behavior are not reproduced (vendor sources favoring real-device clouds, **[COMM]**, so the framing is biased but the engine point is consistent with Playwright's design) [S32]. For a public site targeting Safari iOS, add a monthly real-device smoke (manual or a cloud) rather than trusting emulation alone.

**Component testing:** Playwright CT remains experimental; React/Vue CT packages stopped receiving updates (1.63) and Svelte CT was removed (1.59) [S28, S33]. Prefer **Vitest 4 Browser Mode** (stable since 4.0, Playwright provider) for component behavior and keep Playwright for journeys [S34, S33]. Caveat: Stryker's Vitest runner does not support Browser Mode [S9], so mutation testing remains on node/jsdom-environment unit tests.

---

## 8. Visual regression tools

- **Playwright snapshots (`toHaveScreenshot`)**: free, in-repo, but baselines are OS/browser specific. Stability recipe from multiple guides: generate and compare inside the official Playwright Docker image; wait on `document.fonts.ready`; leave `animations: 'disabled'`; fix viewport and `deviceScaleFactor`; mask dynamic regions; small tolerance such as `maxDiffPixelRatio` 0.01 (sources disagree on exact values) [S35, mostly blogs, some **[COMM]**].
- **Argos**: SaaS review UI on top of Playwright/Vitest screenshots; one comparison lists free to 5,000 screenshots/month then USD 100 flat, but it is Argos's own blog and a second source says self-hosting is not supported **[COMM]** [S36, S37].
- **Chromatic**: Storybook-native; one list gives from USD 179/month **[COMM]** [S36].
- **Lost Pixel**: sources report the team joined Figma and the repo was archived 2026-04-22; treat as dead [S36, secondary, **[COMM]** authors].
- **Vitest 4 `toMatchScreenshot`** with "stable screenshot detection" for component-level visuals [S34].

**Recommendation:** Playwright native snapshots in Docker for 6-10 key pages x 2 viewports per public site (threshold above); no SaaS until review friction justifies the cost (more than ~2 visual PRs per week with multiple reviewers). If a SaaS is added, Argos is the closer fit than Chromatic because there is no Storybook in the stack (verify). Backoffices: visual tests only on the design-system components, not data tables.

---

## 9. Accessibility automation limits

Deque's 2021 study (13,000+ page states, ~300,000 issues) reports axe-core rules found **57.38% of total issues by volume**, versus the older 20-30% estimate based on the share of WCAG criteria that are machine-testable. Deque makes axe **[COMM]**; it covered HTML first-time audits only and Deque itself says manual expert testing is still required [S38]. Conclusion: automated axe is a regression net that likely catches roughly half of issues by volume and far fewer by criterion; it cannot judge alt-text quality, reading order sense, focus-management correctness or cognitive load.

**Recommended a11y stack:** axe in Playwright on every critical page/state (open menus, dialogs, error states, not just load), zero violations of impact serious/critical as a hard gate, minor as report; keyboard-only Playwright journeys (Tab order, focus trap in modals, focus return) as explicit tests; `prefers-reduced-motion` emulation test on any animated route (also your user-level rule); a manual screen-reader pass (NVDA/VoiceOver) per release for public sites, quarterly for backoffices. Do not claim "WCAG compliant" from axe alone.

---

## 10. Lighthouse CI budgets and field CWV

- LHCI assertion levels: `off`/`warn`/`error`; `numberOfRuns` defaults to 3 (examples use 5); `aggregationMethod` default `optimistic`, others `median`, `pessimistic`, `median-run`; `budgetsFile` cannot be combined with other assert options [S39].
- No INP in the lab; common practice uses TBT as a proxy (secondary sources) [S40]. Field thresholds at p75: LCP good under 2.5 s, INP under 200 ms, CLS under 0.1 [S40, secondary; matches Google's published values from memory].
- The lab/field gap is real: web.dev documents why lab and field differ [S41], and one secondary example shows a page with good LCP/CLS but INP 248 ms in the field [S40].

**Recommended budgets:**
- Public sites, mobile emulation, `numberOfRuns: 5`, `aggregationMethod: median-run`: performance score min 0.90 (error), accessibility 1.0 (error), best-practices 0.95 and SEO 0.95 (error); LCP max 2500 ms, CLS max 0.1, TBT max 200 ms (error); JS transferred max ~170 KB gzip on the landing route (budget; tune to your baseline).
- Backoffices: performance min 0.80 (warn), TBT max 300 ms (warn), accessibility 1.0 (error); do not chase LCP on authenticated dashboards.
- Field: add `web-vitals` RUM reporting to your own endpoint or use CrUX API for public sites; alert at p75 LCP 2.5 s, INP 200 ms, CLS 0.1. Lab gates prevent regressions; only field data confirms the outcome. With low traffic, CrUX may have no data for a site; then RUM is the only field signal.

---

## 11. Load testing SSE (k6 vs Locust vs Artillery)

No head-to-head benchmark with reliable methodology exists in what I found. Facts:
- **k6**: SSE via the community extension `xk6-sse` (Apache-2.0, small project: 54 stars, empty Releases page; README says no custom xk6 build needed since a k6 announcement, tested with k6 v1.2.2) and Grafana Cloud extension support; includes an LLM time-to-first-token example [S42, S43]. k6 core docs did not mention SSE in the extensions page I fetched [S43].
- **Locust**: Python, same language as the FastAPI repos; a `locust-sse` plugin exists for LLM streaming benchmarks; LoadForge guides are vendor material **[COMM]** [S44].
- **Artillery**: no SSE-specific guidance found; Node runtime is heavier than Go [S44, secondary].
- Method guidance: assert the stream stays open and emits valid frames, not just HTTP 200 [S44]; watch the HTTP/1.1 per-origin connection ceiling (6 per browser) which affects real clients, not load generators.
- An unverified blog claims FastAPI/uvicorn handled 4,200 connections before drops vs 11,800 for Litestar; no methodology, ignore [S44, unverified].

**Recommendation:** Locust (Python, custom SSE client with httpx streaming) if the team wants to share fixtures and auth helpers with pytest; k6 + xk6-sse if you want thresholds-as-code and Grafana integration and accept a small community extension. Pick one; spike each for half a day on the real `/stream` endpoint. Metrics and thresholds (assistant APIs): time-to-first-event p95 under 1.5 s (excluding LLM latency, use a stubbed model), inter-event gap p95 under 500 ms, error and premature-close rate under 0.5%, sustained N concurrent streams where N = 3x expected peak with RSS growth under 20% over 15 min (leak test), reconnect-with-`Last-Event-ID` correctness. Run on schedule (nightly or pre-release), never on PR.

---

## 12. Security testing for OAuth/CSRF/RBAC (better-auth)

**Recent advisories:** GHSA-wxw3-q3m9-c3jr / CVE-2026-67335: OAuth callback accepted a mismatched `state` when cookie-backed state storage was used without PKCE, enabling login CSRF; fixed in better-auth 1.6.2 (CVSS reported as 5.3-6.5 depending on database) [S45]. GHSA-9h47-pqcx-hjr4 / CVE-2026-67336: insecure oidcProvider/MCP defaults (alg=none advertised, plain PKCE accepted); fixed in 1.6.11; severity reported 8.7-9.4 [S45]. Lesson: pin better-auth to a patched floor and keep a regression test per advisory.

**What better-auth's own security doc implies you should assert** [S46]: untrusted `Origin` rejected on state-changing requests; `Origin: null` accepted only with `Sec-Fetch-Site: same-origin` and trusted URL origin; cookie-less cross-site navigation sign-in blocked; redirect/callback URLs reject absolute untrusted URLs, `//`, backslashes, control chars, encoded separators; cookies `Secure`, `HttpOnly`, `SameSite=Lax` on HTTPS; forged `X-Forwarded-For`/`Host` ignored unless `trustedProxies`; rate limits trip with stricter thresholds on sensitive routes; OAuth callbacks with missing or mismatched state/PKCE rejected and state cleaned up; token/JWKS fetches do not follow redirects; revoked sessions stop authenticating; identical sign-up responses for existing vs new emails with similar timing. Note `trustedOrigins` must not include localhost in production, and `disableOriginCheck` disables CSRF too [S46].

**RBAC/IDOR.** OWASP A01:2025 tells teams to include functional access-control checks in unit and integration tests and verify permission on every object access [S47]. Scanners miss most of these because only a human knows who should own a record [S47, secondary]. Implement a **role x resource x action matrix test** generated from the same permission table the app uses, run through the real HTTP layer with one fixture per role plus a second tenant/user (the three-user swap-ID pattern) [S47, secondary; single-blog sketch]. Include: unauthenticated -> 401, wrong role -> 403, wrong owner -> 404/403 consistently, horizontal and vertical escalation, direct object ID swap, mass-assignment on role fields, JWT/session tamper, logout invalidation, CSRF on every mutating route in the matrix.

**Targets:** 100% of mutating routes appear in the matrix (enforced by a test that enumerates registered routes and fails if one is unlisted); mutation score on the auth/permission module at least 85%; a Playwright test per OAuth provider covering the error paths (denied consent, replayed code, tampered state); a CI dependency check (`npm audit`/OSV) failing on high advisories for better-auth.

---

## 13. Test runner choice: node:test vs Vitest 4 with TS 7

Facts:
- **Vitest 4.0** (2025-10-22): Browser Mode stable, visual regression (`toMatchScreenshot`), Playwright Trace support, breaking changes (migration guide) [S34]. The publisher VoidZero backs Vitest/Vite **[COMM]**.
- **node:test**: Node 24 runs `.ts` via type stripping without a loader; it strips only, does not type check, ignores tsconfig paths, no `.tsx` [S48]. Sources conflict on coverage status (experimental vs stable in Node 24) and `mock.module()` is still immature and flagged experimental by one guide [S48, secondary]. Speed claims (40% faster) lack methodology; ignore [S48].
- **TS 7.0** (2026-07-08): native `tsc`, 8-12x faster builds, stricter defaults (`strict` true, `types: []`, removed `baseUrl`/`node10`), no programmatic API until 7.1 [S13]. Tools needing the API (typescript-eslint, template checkers) need a TS 6 alias [S13]. This favors running type checking as a separate `tsc --noEmit` job under TS 7 and keeping test running independent of the TS API.

**Recommendation:**
- If the repo has meaningful logic and you want mutation testing, component tests, mocking and fast-check: **migrate to Vitest 4** for the Next.js repos. The reasons are Stryker's best-supported runner (precise incremental reuse, perTest) [S8, S9], Browser Mode components, ESM mocking.
- Keep `node:test` for small dependency-free library/CLI packages if it already works; then mutation testing runs through tap-runner (unproven here; spike first) [S10].
- Do not mix runners inside one package. Run `tsc --noEmit` (TS 7) as its own CI job with a hard gate, since neither runner type-checks (node:test strips, Vitest uses esbuild/oxc transforms).
- Migration cost is real: budget 1-2 days per repo for rewriting mocks and config; verify `@fast-check/vitest` version compatibility (needs Vitest ^4.1) [S20].

---

## Recommendations per repo type (numeric)

### A. Public Next.js sites (x2)
- Static: `tsc --noEmit` (TS 7) 0 errors, eslint 0 warnings gate.
- Unit/integration (Vitest 4): branch coverage floor 75% repo-wide; diff coverage 85% on PR.
- Mutation (Stryker, scoped to lib/utils/seo/forms/validation): PR incremental, break 60; weekly full, target 75-80 (high 80, low 65). Skip UI components.
- fast-check: 3-5 properties (slug/url normalization, form validation, sitemap generation); 100 runs PR, 1000 nightly.
- Playwright: 10-20 journey tests, `retries: 1`, `failOnFlakyTests` on main, trace `on-first-retry`, shard when job exceeds 8 min; PR = Chromium + iPhone WebKit; nightly = all browsers + Pixel profile.
- Visual: 6-10 pages x 2 viewports, Docker image, `maxDiffPixelRatio` 0.01 (tune), `animations: disabled`, reduced-motion variant for animated pages.
- a11y: axe on every route and key states, 0 serious/critical; keyboard journeys; manual screen-reader pass per release.
- LHCI (5 runs, median-run): perf >= 0.90, a11y 1.0, SEO >= 0.95, LCP <= 2500 ms, CLS <= 0.1, TBT <= 200 ms. Field: RUM p75 LCP <= 2.5 s, INP <= 200 ms, CLS <= 0.1.
- Security: headers/CSP smoke test, dependency audit gate.

### B. Next.js backoffices (x2, OAuth/RBAC)
- Vitest 4: branch floor 80%, diff 90% on auth/permission code, 80% elsewhere.
- Mutation: Stryker scoped to `auth/`, `permissions/`, `policies/`, input validation: break 70, target >= 85 on the permission module, 75 on the rest.
- fast-check: permission lattice and filter/pagination properties; model-based test of session lifecycle if verified feasible.
- Playwright: 15-25 tests; per-role projects with stored auth state; the role x resource x action matrix (every mutating route listed, enforced); OAuth error paths; CSRF/Origin tests; `failOnFlakyTests` on main; PR = Chromium; nightly = Chromium + Firefox + WebKit.
- better-auth: pin >= 1.6.11 (covers both advisories above) and one regression test per advisory; assert every item in section 12.
- a11y: axe + keyboard on forms, tables, dialogs; 0 serious/critical.
- LHCI: perf >= 0.80 warn, a11y 1.0 error, TBT <= 300 ms warn.
- Visual: design-system components only (Vitest Browser Mode `toMatchScreenshot` or Playwright), not data views.

### C. FastAPI assistant APIs (x2)
- pytest + pytest-cov: branch coverage floor 85%, diff coverage 90% via diff-cover; `ruff` + `ty`/mypy strict gates.
- Integration: real Postgres+pgvector (Testcontainers or CI services), session-scoped container, rollback per test, Neo4j fixture with `DETACH DELETE`; suite under 90 s; random ordering.
- Hypothesis: `ci` profile 100 examples PR, 1000 nightly; stateful machine for the conversation/session lifecycle (50 steps default).
- Mutation: mutmut 3 (forkserver), scoped to domain/auth/prompt-assembly/retrieval ranking; weekly; break 60, target 75.
- Contract: committed `openapi.json`; `oasdiff breaking` blocks PR; Schemathesis 50 examples PR / 500 nightly with explicit links for stateful flows; no Pact while both consumers are first-party.
- SSE: pytest SSE conformance tests (frame format, heartbeat, `Last-Event-ID`, client disconnect cancels the LLM call); nightly load test with Locust or k6+xk6-sse: TTFE p95 < 1.5 s (stubbed model), error rate < 0.5%, 3x peak concurrent streams, RSS growth < 20% over 15 min.
- LLM evals separate from this plan (golden sets, judge validation); keep deterministic tests free of live model calls.
- Security: authz matrix on all routes, rate-limit tests, secret-redaction test (no tokens in logs/repr).

### D. Python ops repo
- pytest, pyramid shape (55% unit): branch coverage floor 85%, diff 90%.
- Hypothesis on parsers, idempotency of jobs, retry/backoff math.
- Mutation: mutmut on decision logic (scheduling, retention, cost calculations): target 80, break 65, monthly (low change rate).
- Integration: temp dirs, `tmp_path`, recorded fixtures for external APIs; dry-run mode tested for every destructive command (ties to your guard-hook policy); contract test for any CLI JSON output via snapshot.
- No Playwright/Lighthouse/visual.

### Cross-cutting CI cadence
| Job | PR | Nightly | Weekly | Release |
|---|---|---|---|---|
| Static + unit + integration + diff coverage | yes | yes | - | yes |
| Playwright (Chromium + iPhone WebKit) | yes | - | - | - |
| Playwright full browser/device matrix + visual | - | yes | - | yes |
| Stryker/mutmut | incremental changed-only | - | full scoped | full scoped |
| Schemathesis/oasdiff | oasdiff + short Schemathesis | long Schemathesis | - | yes |
| LHCI | public sites | - | - | yes |
| SSE load | - | yes | - | yes |
| Manual a11y + real-device Safari | - | - | - | yes (public) |

---

## Contested / uncertain

1. **Mutation score as a gate.** Evidence that mutation-driven testing improves real quality is limited; Google's authors say so [S4]. Treat it as a review aid on changed code plus a sanity gate on risk modules, not a vanity KPI. Thresholds here are consensus-blog values, not research-derived.
2. **Stryker + node:test via tap-runner.** Claimed in the Stryker 7 announcement [S10]; no real-world benchmark or issue reports found. Spike before committing.
3. **Stryker current version and TS 6/7 checker compatibility.** Conflicting version signals (9.x vs 10); TS 7 has no programmatic API until 7.1 [S13]. Likely needs the TS 6 alias; unverified.
4. **node:test coverage/mocking maturity.** Sources disagree (stable vs experimental) [S48]; check the Node 24/26 docs yourself.
5. **Vitest vs node:test speed.** Published benchmarks lack methodology; do your own timing on a real repo.
6. **mutmut vs cosmic-ray.** Only vendor-adjacent or weak academic comparisons exist [S16]; run both on one repo for a day.
7. **Testcontainers-Python specifics** (Neo4j module, container reuse): not confirmed in official docs I could fetch [S23]; CI `services:` is the safe fallback.
8. **Pact vs schema-driven.** The best critiques come from vendors in the OpenAPI space **[COMM]**; the recommendation here depends on both consumers being first-party and co-released. If that changes, revisit.
9. **k6 xk6-sse vs Locust for SSE.** No credible benchmark; xk6-sse is a small community project [S42].
10. **axe 57%.** Single vendor study, first-time audits, HTML only [S38]. Other studies reportedly show lower detection; I did not retrieve them.
11. **Playwright WebKit as Safari proxy.** Direction of the claim is consistent but the "80-90%" coverage figure is unsupported; do not cite it.
12. **Next.js RSC testing.** Docs caveat "Vitest does not support async Server Components" appears in v14/v15 pages but not in the snippet of the current page [S3]; verify.
13. **Visual SaaS landscape.** Pricing and Lost Pixel's status come from vendor blogs [S36]; re-check vendor pages before purchase.
14. **Severity of better-auth CVEs** differs across databases (5.3-6.5 and 8.7-9.4) [S45]; use the GitHub advisories as ground truth.
15. **Dated oddities.** Some secondary pages carry dates later than today or contradict each other (e.g. a blog dated 2026-12-05); weight primary docs.

---

## Sources

[COMM] marks commercial interest in the topic or tool.

- S1. Dodds, The Testing Trophy and Testing Classifications - https://kentcdodds.com/blog/the-testing-trophy-and-testing-classifications
- S2. web.dev, Pyramid or Crab? Find a testing strategy that fits - https://web.dev/articles/ta-strategies ; Spotify honeycomb described via secondary summaries: https://howitworks-dev.pages.dev/testing-strategies/
- S3. Next.js testing docs: https://nextjs.org/docs/15/app/guides/testing/vitest ; https://nextjs.org/docs/14/app/building-your-application/testing/vitest ; https://nextjs.org/docs/app/guides/testing
- S4. Petrovic et al., Practical Mutation Testing at Scale: A view from Google (IEEE TSE 2021) - https://homes.cs.washington.edu/~rjust/publ/PetrovicIFJ2021c-abstract.html ; https://arxiv.org/pdf/2102.11378v1 ; https://people.cs.umass.edu/~rjust/publ/industrial_mutation_icst_2018.pdf
- S5. diff-cover (`--fail-under`) https://pypi.python.org/pypi/diff_cover/0.9.1 ; CodeClimate diff coverage statuses https://codeclimate.com/changelog/59baa212ced24c026c0017b8 ; Qlty https://docs.qlty.sh/coverage/commit-statuses [COMM: Codacy/CodeClimate/Qlty are vendors] ; https://blog.codacy.com/diff-coverage
- S6. Trail of Bits, Mutation testing for the agentic era - https://blog.trailofbits.com/2026/04/01/mutation-testing-for-the-agentic-era/ [COMM: consultancy]
- S7. Stryker configuration - https://stryker-mutator.io/docs/stryker-js/configuration/
- S8. Stryker incremental mode - https://stryker-mutator.io/docs/stryker-js/incremental/ ; https://stryker-mutator.io/blog/announcing-incremental-mode/
- S9. Stryker Vitest runner - https://stryker-mutator.io/docs/stryker-js/vitest-runner/
- S10. Announcing StrykerJS 7 (tap-runner, vitest-runner) - https://stryker-mutator.io/blog/announcing-stryker-js-7/
- S11. Announcing Stryker 0.34 (command runner) - https://stryker-mutator.io/blog/announcing-stryker-0-34/ ; plugin list https://stryker-mutator.io/docs/stryker-js/plugins/
- S12. Announcing faster TypeScript checking for StrykerJS - https://stryker-mutator.io/blog/announcing-faster-typescript-checking/
- S13. Announcing TypeScript 7.0 - https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/ ; InfoQ https://infoq.com/news/2026/08/typescript-7-released/
- S14. Mutation threshold/cadence blogs (secondary): https://oneuptime.com/blog/post/2026-01-25-mutation-testing-with-stryker/view ; https://frontendchecklist.io/rules/testing/mutation-testing ; https://testwithpinpoint.com/blog/mutation-testing-guide ; https://kindatechnical.com/test-driven-development/mutation-testing-tools-stryker-mutmut-pitest.html
- S15. mutmut README - https://github.com/boxed/mutmut
- S16. Python mutation comparisons: https://arxiv.org/html/2601.19088v1 ; https://par.nsf.gov/servlets/purl/10573281 ; https://pytest-gremlins.readthedocs.io/en/latest/guide/comparison/ [COMM] ; https://nwyin.github.io/irradiate/guide/comparison/ [COMM] ; https://ep2024.europython.eu/session/mutation-testing-in-python-with-cosmic-ray
- S17. Trail of Bits mutation-testing skill - https://trailofbits.com/skills/mutation-testing/ [COMM]
- S18. Hypothesis changelog - https://hypothesis.readthedocs.io/en/latest/changelog.html
- S19. Hypothesis settings - https://hypothesis.readthedocs.io/en/latest/tutorial/settings.html ; source https://hypothesis.readthedocs.io/en/latest/_modules/hypothesis/_settings.html
- S20. @fast-check/vitest - https://www.npmjs.com/package/@fast-check/vitest ; https://fast-check.dev/docs/tutorials/setting-up-your-test-environment/property-based-testing-with-vitest/
- S21. fast-check with node:test - https://fast-check.dev/docs/tutorials/setting-up-your-test-environment/property-based-testing-with-nodejs-test-runner/ ; https://fast-check.dev/blog/2025/03/28/beyond-flaky-tests-bringing-controlled-randomness-to-vitest/
- S22. Testcontainers/pytest patterns (secondary): https://oneuptime.com/blog/post/2025-01-06-python-testcontainers-integration/view ; https://helpmetest.com/blog/testcontainers-python/ ; https://qaskills.sh/blog/testcontainers-python-pytest-integration-guide [COMM: test-tool vendors] ; https://neo-technology-field.github.io/python-etl-lib/testing.html
- S23. Testcontainers for Python docs - https://testcontainers-python.readthedocs.io/en/latest/
- S24. Speakeasy, Pact vs OpenAPI - https://www.speakeasy.com/blog/pact-vs-openapi [COMM] ; https://dev.to/deepaksatyam/pact-is-great-its-also-why-most-teams-dont-do-contract-testing-5c14 ; https://oneuptime.com/blog/post/2026-01-30-bi-directional-contract-testing/view
- S25. Contract testing plans: https://dev.to/speccoding/your-openapi-spec-is-decoration-until-ci-enforces-it-1and ; https://stevekinney.com/courses/enterprise-ui/api-contract-testing
- S26. Schemathesis stateful testing - https://schemathesis.readthedocs.io/en/latest/guides/stateful-testing/ ; https://schemathesis.readthedocs.io/en/latest/explanations/stateful/
- S27. oasdiff - https://github.com/oasdiff/oasdiff [COMM: hosted tier]
- S28. Playwright release notes - https://playwright.dev/docs/release-notes
- S29. Playwright best practices - https://playwright.dev/docs/best-practices
- S30. Playwright retries - https://playwright.dev/docs/test-retries
- S31. Playwright sharding - https://playwright.dev/docs/test-sharding
- S32. Playwright mobile/WebKit vs real Safari: https://www.browserstack.com/guide/playwright-ios-automation [COMM] ; https://www.testdino.com/blog/playwright-mobile-testing [COMM] ; https://hyperping.com/learn/playwright/playwright-mobile-emulation [COMM]
- S33. Playwright CT vs Vitest browser mode: https://currents.dev/posts/playwright-component-testing [COMM] ; https://www.epicweb.dev/vitest-browser-mode-vs-playwright
- S34. Announcing Vitest 4 - https://voidzero.dev/posts/announcing-vitest-4 [COMM: VoidZero] ; https://v4.vitest.dev/guide/browser/visual-regression-testing ; https://www.infoq.com/news/2025/12/vitest-4-browser-mode
- S35. Playwright visual regression stability: https://argos-ci.com/blog/playwright-visual-regression-testing-ci [COMM] ; https://testquality.com/?p=7894 [COMM] ; https://testdino.com/blog/playwright-visual-testing [COMM] ; https://www.desplega.ai/blog/deep-dive-snapshot-testing-reliability
- S36. Visual tool comparison: https://argos-ci.com/blog/best-visual-regression-testing-tools [COMM] ; https://21st.dev/blog/lost-pixel-alternatives [COMM] ; https://toolradar.com/compare/lost-pixel-vs-chromatic [COMM]
- S37. Cloudzy, Argos vs Lost Pixel vs BackstopJS - https://cloudzy.com/blog/argos-vs-lost-pixel-vs-backstopjs-compared/ [COMM, affiliate-style]
- S38. Deque, automated testing study 57% - https://www.deque.com/blog/automated-testing-study-identifies-57-percent-of-digital-accessibility-issues [COMM: axe vendor] ; https://www.deque.com/automated-accessibility-testing-coverage/
- S39. Lighthouse CI configuration - https://github.com/GoogleChrome/lighthouse-ci/blob/main/docs/configuration.md
- S40. CWV/INP proxies and thresholds (secondary): https://corewebvitals.io/core-web-vitals ; https://unlighthouse.dev/learn-lighthouse/lighthouse-ci/budgets [COMM: tool vendor] ; https://dev.to/benriemer/core-web-vitals-in-2026-the-practical-fixes-for-inp-lcp-and-cls-that-actually-work-4ef0
- S41. web.dev, Why lab and field data can be different - https://web.dev/articles/lab-and-field-data-differences
- S42. xk6-sse - https://github.com/phymbert/xk6-sse
- S43. Grafana k6 extensions - https://grafana.com/docs/k6/latest/extensions/
- S44. SSE load testing guides: https://loadforge.com/guides/api-protocols/load-testing-server-sent-events-sse [COMM] ; https://helpmetest.com/blog/real-time-testing-tools/ [COMM] ; https://tessl.io/registry/testland/sse-load-tests ; https://dev.to/_6638a39c349d7e9c85ee20/load-testing-guide-2026-k6-vs-artillery-vs-locust-vs-wrk2-for-performance-testing-11h3 ; https://awesome.ecosyste.ms/projects/github.com%2Faleph-alpha%2Flocust-sse
- S45. better-auth advisories: https://advisories.gitlab.com/npm/better-auth/GHSA-wxw3-q3m9-c3jr/ ; https://advisories.gitlab.com/npm/better-auth/GHSA-9h47-pqcx-hjr4/ ; https://security.snyk.io/vuln/SNYK-JS-BETTERAUTH-16722768 [COMM: Snyk] ; https://corgea.com/advisories/vulnerabilities/CVE-2026-67335 [COMM]
- S46. better-auth security reference - https://better-auth.com/docs/reference/security
- S47. OWASP A01:2025 Broken Access Control - https://owasp.org/Top10/2025/A01_2025-Broken_Access_Control/index.html ; RBAC test sketches (secondary): https://softwaretestpilot.com/blog/security-testing/rbac-security-testing-checklist-qa ; https://web-security-automation.pages.dev/blog/access-control-vulnerabilities.html ; https://xbow.com/blog/insecure-direct-object-reference-idor [COMM: security vendor]
- S48. node:test vs Vitest / type stripping: https://wallabyjs.com/whatsnew/node-test-native-type-stripping.html [COMM: Wallaby] ; https://flaviocopes.com/node-test-runner ; https://blog.openreplay.com/drop-jest-node-test-runner/ [COMM] ; https://dev.to/gabrielanhaia/mocking-esm-in-2026-vitest-bun-and-nodes-mockmodule-hep ; https://www.pkgpulse.com/guides/node-test-vs-vitest-vs-jest-native-test-runner-2026
