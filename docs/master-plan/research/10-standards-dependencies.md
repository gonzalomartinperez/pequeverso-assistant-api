# Research 10: Code standards and dependency policy (TS/Next.js + Python), Nov 2026

Date: 2026-11-09. Scope: 4 TypeScript/Next.js repos (Biome, TS 7, erasable syntax), 3 Python repos (uv/ruff/mypy). Sources are numbered [n]; commercial-interest sources are tagged (C) in the list. Method note: ~45 pages fetched; the web-search quota ran out midway, so some library picks (forms, charts, Playwright, date-fns) rest on fewer fetched sources and are flagged in "Contested/uncertain".

---

## TOPIC A. Code standards

### A1. Which TypeScript style guide

| Guide | What it really is | Verdict |
|---|---|---|
| Google TS Style Guide [1] | Complete, opinionated, written for large monorepo; named exports only, no namespaces, `const`/`let` only, no `I` prefix, avoid `x!` and unjustified `as`, JSDoc on exports, semicolons, `interface` over type-literal alias for object shapes, plain `enum` (not `const enum`), CONSTANT_CASE module constants and enum values | Best base document: explicit rationale per rule, mostly enforceable by linters |
| Microsoft "Coding guidelines" [2] | Contributor rules for the TypeScript compiler repo itself; the page says it is not a prescriptive standard for others (PascalCase types, `undefined` over `null`, 4-space indent, double quotes, avoid classes in core pipeline) | Not a standard to adopt; borrow only "`undefined` not `null`" and "no `I` prefix" |
| ts-standard [3] | StandardJS engine plus `eslint-config-standard-with-typescript`; no-semicolon style; requires tsconfig and the ESLint stack; repo shows no releases listing on the page I fetched, so maintenance cadence is unconfirmed | Reject: forces ESLint, conflicts with Biome formatter defaults, unclear momentum |

**Recommendation:** adopt Google's guide as the written reference, but delegate formatting to Biome's formatter (not the guide's whitespace rules) and enforce only what Biome can check. Deviations are listed in section "Recommended standards with deviations".

### A2. Enforcing with Biome 2.x: coverage and gaps

State of Biome (primary sources): v2.4 (Feb 2026) promoted 24 rules to stable and improved Vue/Svelte/Astro; v2.5 (Jun 2026) passed 500 lint rules, added cross-file linting, and stabilized 70+ rules including some type-aware ones; v2.6 (Oct 15 2026) added Markdown/YAML/SCSS formatting and a developer-preview JavaScript plugin API next to GritQL plugins [8][9].

Rule coverage vs typescript-eslint:
- Biome's rule-sources page maps 44 typescript-eslint rules (8 only "inspired") [4]. `useNamingConvention` (inspired by `naming-convention`) and `useImportType` (inspired by `consistent-type-imports`) exist.
- Listed on that page as having no mapped Biome equivalent: `no-unsafe-*` family, `strict-boolean-expressions`, `switch-exhaustiveness-check`, `no-misused-promises` (as a typescript-eslint mapping; Biome has its own `noMisusedPromises`, see below) [4]. Biome ships `noUnnecessaryConditions` (suspicious, promoted stable in 2.5 [9]) as its answer to `no-unnecessary-condition`, so the "no equivalent" list is partly stale; verify per rule before deciding.
- Type-aware rules live in the `types` domain (`noFloatingPromises`, `noMisusedPromises`, `useAwaitThenable`, `noUnnecessaryConditions`, `useArraySortCompare`); enabling it scans the whole project and has a performance cost [5]. Biome's inference is a subset of the TS type system, tuned to avoid false positives at the price of false negatives [7]. The rule page I fetched still labelled `noFloatingPromises` as nursery (since 2.0) [6], while the 2.5 post says "over 70 rules spread among Vue, type-aware rules and more" were stabilized without naming it [9]. Treat its status as unconfirmed; pin the Biome version and read the changelog on each bump.
- Project domain rules worth turning on: `noImportCycles`, `noUndeclaredDependencies`, `noUnresolvedImports`, `noPrivateImports` [5]. Next and React domains auto-enable from package.json versions [5].

Adding a second linter for gaps:
- **typescript-eslint** is the reference implementation of typed linting (project service, 100% coverage goal in its own rule tests) [11], but it needs the TypeScript programmatic API. TS 7.0 ships with no programmatic API; 7.1 is expected to add a new one (beta published Oct 20 2026), and until then `@typescript/typescript6` re-exports the 6.0 API for tools like typescript-eslint [12][14]. So typescript-eslint adds slow, double-compiler cost and a compatibility shim. Not recommended as a default.
- **oxlint + tsgolint** runs type-aware rules in Go on top of typescript-go; docs say 59 of 61 typescript-eslint type-aware rules are covered, requires TS >= 7.0, `oxlint-tsgolint`, no legacy `baseUrl`, high memory on very large repos; its optional `--type-check` can replace `tsc --noEmit` in CI [10]. This is the only credible path to near-full typed-lint parity on TS 7.
- Decision rule: Biome first. If a repo needs `no-unsafe-*`, `strict-boolean-expressions` or `switch-exhaustiveness-check` (the real gaps), run oxlint type-aware in CI only with `--type-aware`, with all non-type-aware oxlint rules disabled to avoid duplicate findings with Biome. Keep it a CI check, not a pre-commit hook. Justification line for the ADR: closes the floating/unsafe-any gap that `tsc` strict does not.

### A3. TypeScript compiler options and language conventions

Baseline tsconfig (TS 6/7 defaults help: `strict: true`, `module: esnext`, `noUncheckedSideEffectImports: true`, `types: []`, `rootDir: ./` are defaults now [12][13]):
- `strict: true` (default but state it explicitly for tooling that reads the file).
- `noUncheckedIndexedAccess: true`: forces handling of `undefined` on index/record access; real bug class, low friction with `for..of`, `.at()`, destructuring defaults. Keep.
- `exactOptionalPropertyTypes: true`: distinguishes absent from `undefined`; not part of `strict`; rejects `x = undefined` on optional props, so it breaks assign-undefined patterns and some library types [16]. Recommend: on for new/own-domain code; off (or per-package) where heavy third-party types (React props spreading, ORM inputs) generate noise. This is a genuine team call (see Contested).
- `verbatimModuleSyntax: true`, `erasableSyntaxOnly: true`, `noEmit: true` (Next/tsgo only type-check), `isolatedModules` implied; `noImplicitOverride`, `noFallthroughCasesInSwitch`, `noPropertyAccessFromIndexSignature` (optional, noisy), `forceConsistentCasingInFileNames`.
- Remove anything TS 7 turned into a hard error: `baseUrl`, `moduleResolution: node`/`node10`/`classic`, `target: es5`, `downlevelIteration`, `esModuleInterop: false` [12][13]. Use `paths` without `baseUrl` or Node subpath imports (`#...`).
- TS 6.0 (Mar 23 2026) was the bridge; `--stableTypeOrdering` helps diagnose 6-to-7 diffs but can slow checks up to 25% and is not for long-term use [13].

Enums vs unions: Google allows plain `enum` [1], but `erasableSyntaxOnly` rejects `enum`, runtime `namespace`, parameter properties and `import =` [15]; Node's stripper fails the same constructs with `ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX` [17]. Therefore: string-literal unions plus `as const` objects (`const Status = {...} as const; type Status = (typeof Status)[keyof typeof Status]`). This is a deliberate deviation from Google.

Naming and exports (Google, mostly adopted [1]): UpperCamelCase types/classes/components; lowerCamelCase values; CONSTANT_CASE only for true module constants (deviation: camelCase for `as const` config objects); no `I` prefix; no leading underscores; kebab-case file names (Next convention; Google is silent/other). Named exports only, except where the framework demands a default export (Next `page.tsx`, `layout.tsx`, `route` handlers use named verbs, `next.config.ts`, `*.config.ts` files, `app/**/error.tsx`, `loading.tsx`, `not-found.tsx`). Biome `noDefaultExport` with overrides for those globs. Prefer `interface` for object shapes that are extended; `type` for unions/mapped/utility types (Google prefers interface always; this is a mild deviation, enforce with Biome `useConsistentTypeDefinitions` only if the team wants it).

Other: `unknown` over `any` in catch/boundaries; `import type` (Biome `useImportType`); no `x!` without comment [1]; `undefined` over `null` internally (Microsoft idea [2]) but accept `null` at JSON/DB boundaries; prefer `satisfies` over `as`; validate external input with a schema, not casts.

### A4. TS 7 (native compiler) status and ecosystem compatibility

- 7.0 beta Apr 21, RC Jun 18, GA Jul 8 2026; the TS devblog lists 7.1 beta on Oct 20 2026 [14]. Install is plain `npm i -D typescript` and the `tsc` binary is the Go build; `@typescript/typescript6` provides `tsc6` side by side [12]. (One secondary source mentions `tsgo` as a name; per the official post `tsgo` is only the nightly/preview channel naming. Treat `tsgo` in scripts as legacy.)
- Matches 6.0 type-checking behavior if the code compiles clean under 6.0 with `stableTypeOrdering` and no `ignoreDeprecations` [12]. Reported ~8-12x faster builds (Microsoft figure; vendor claim, not independently measured by me) [12][14].
- Not available in 7.0: programmatic API, so tooling that embeds the compiler (typescript-eslint, ts-morph, ts-node, ts-loader, Vue/Svelte/Astro/MDX/Angular editor support) must use the TS 6 shim or wait for 7.1 [12].
- Practical policy per repo: `typescript@^7` for `tsc`/CI, plus an alias dependency on 6 only if a tool in the chain needs the API (check Next.js's own type-check step: Next exposes `useTypeScriptCli` config to run the project-local CLI for build type checks [18]; verify behavior per Next version in each repo).
- Biome does not use the TS compiler at all, which is why it is the lowest-risk linter choice during this transition [7].

### A5. Config files: .js/.mjs/.cjs to TypeScript

Runtime facts: Node type stripping is Stability 2 (stable) since v24.12.0/v25.2.0, on by default since v22.18/v23.6, runs only erasable syntax, ignores tsconfig (`paths` unsupported), requires explicit `.ts` extensions in imports, refuses files under `node_modules`, does not support `.tsx`, and needs `import type`/`type` modifiers [17]. Node's own doc recommends `erasableSyntaxOnly`, `verbatimModuleSyntax`, `rewriteRelativeImportExtensions`, `module: nodenext` [17]. Node 26 removes `--experimental-transform-types` [17]. Use `tsx` where enums/paths/decorators are unavoidable [17].

| File | Convert? | Note |
|---|---|---|
| `next.config.ts` | Yes | Supported by Next (`import type { NextConfig } from 'next'`); `.cjs`/`.cts` are not supported; config is not run through webpack/babel so avoid syntax newer than target Node [18] |
| `postcss.config.mjs` | Usually keep `.mjs` | Tailwind 4 needs only `@tailwindcss/postcss`; PostCSS config loaders (`postcss-load-config`) support `.ts` only via a TS loader; low payoff. Verify per setup (not fetched) |
| `playwright.config.ts` | Already TS | Playwright transpiles its own config |
| `vitest.config.ts`, `vite` | Already TS | Vite bundles the config |
| `biome.json(c)` | JSON | No TS option; keep |
| `eslint.config.*` | N/A if no ESLint | If oxlint JS plugins arrive, revisit |
| scripts/*.mjs | Convert to `.mts`, run with `node script.mts` | Node >= 24.12 in `.nvmrc`; add `tsconfig.scripts.json` with erasable settings and run `tsc --noEmit` on them |
| `.github/` scripts, `commitlint`, `lint-staged` | Keep JSON/YAML configs | No benefit |

Must remain JS/JSON/other: anything loaded by a tool that does not go through Node's TS path or its own bundler (package.json, `.npmrc`, `pnpm-workspace.yaml`, `biome.json`, `.nvmrc`, Dockerfiles, Hostinger/hPanel build commands); and any file imported from `node_modules`-resolved packages (stripping refuses it) [17]. Also note hosting runtime: if a platform runs `node` older than 22.18, `.ts` scripts fail; pin Node via `engines`.

### A6. Python: Google guide vs PEP 8 + ruff

Google Python guide [19]: 80-column lines, `pylint`, Google-style docstrings (`Args:`, `Returns:`, `Raises:`, class `Attributes:`), import packages/modules not individual names with no relative imports, no mutable defaults, avoid power features, implicit truthiness but `is None`, type annotations on public APIs with `X | None`, module-level `main()` guard, 40-line function hint.

Adopt: PEP 8 as the base (what ruff/black-style formatters produce) plus Google docstring convention and a few Google rules. Deviations: line length 88 or 100 (not 80); allow `from x import y` for names (ruff isort style) instead of Google's module-only imports; relative imports allowed inside a package (ruff `TID252` can ban parent-relative); no pylint (ruff `PL` family replaces it).

Ruff mapping (900+ rules; default set is F, E, B, UP, RUF subset) [20]. Suggested `select`: `E, W, F, I, B, UP, SIM, C4, PERF, RUF, S, N, A, ARG, PT, PTH, TRY, PL, TC, ASYNC, DTZ, FURB, ISC (not ISC002 with formatter), RET, PIE, T20, D, DOC` with `D` set to `convention = "google"`. Add `ANN` only for libraries, not apps (mypy already enforces; ruff `ANN` is noisy, many rules flagged pedantic/restriction [20]). Ignore for formatter compatibility: `E501` (or keep, since the formatter can't wrap everything), `W191`, `COM812`, `ISC002`; ruff warns when conflicts exist [21]. Ruff's own repo takes a category approach (`correctness`, `suspicious`, `complexity`, `performance`, `style` with preview on) and ignores `line-too-long` to leave it to the formatter [22]. That is the model to copy: broad select, short ignore list with comments.
Formatter: `ruff format` is a near-drop-in Black; configurable quote style, `docstring-code-format = true` opt-in, line length best-effort [21]. Choose double quotes (default) and line-length 100 for apps.
Types: mypy `strict = true` stays (the owner's choice); ruff `TC` family keeps runtime imports lean. Astral's `ty` is the newer checker (the `modern-python` skill mentions ty); I did not verify its production readiness, so mypy remains.
Python 3.13/3.14 `requires-python`, `from __future__ import annotations` only if needed (ruff itself requires it for py38 target [22]; not needed on 3.13+ for most code).

---

## TOPIC B. Dependency policy

### B1. Criteria framework for choosing a dependency

Scorecard of questions (every new runtime dependency must pass; dev dependencies a lighter version):
1. Need: can platform/stdlib do it (Intl, `fetch`, `structuredClone`, Temporal, `node:test`)? Can it be 30 lines of own code?
2. Health: OpenSSF Scorecard (weighted score of Maintained, Code-Review, Branch-Protection, Dangerous-Workflow (critical), Token-Permissions, Signed-Releases, Pinned-Dependencies, Vulnerabilities, Security-Policy, SAST...; CLI `scorecard --npm=<pkg>`, API at api.scorecard.dev) [32]. Use as a signal, not a gate: a score does not prove a package is safe, and top packages score poorly on some checks.
3. Metadata and graph: deps.dev (Google) shows scorecard, advisories, licenses, dependents and transitive graph with an API [33]. Use for "who depends on it" and transitive weight.
4. Behavioral scan: Socket (C) flags install scripts, network/shell access and typosquats; its free `sfw` firewall wraps npm/pnpm/yarn/pip/uv/cargo, blocks known malware, warns on AI-detected suspicious; telemetry collected; PolyForm Shield license; free tier is an on-ramp to paid plans [34]. Optional layer, never the only control.
5. Replacement for Snyk Advisor: the old `snyk.io/advisor` URL now 301-redirects to `security.snyk.io` (a vulnerability DB) [35], consistent with the advisor being wound down; I could not fetch an official sunset notice, so treat that as inferred. Use deps.dev + Scorecard + npm/PyPI pages instead.
6. Bundle cost (frontend): measure with bundlephobia or pkg-size.dev and, better, with the repo's own build analyzer; set budget (e.g., a new client dependency > 10 kB gz needs justification). Prefer tree-shakable, ESM, `sideEffects: false`, zero transitive deps. (Bundlephobia/pkg-size were not fetched by me; criteria are standard practice.)
7. License: allow MIT, Apache-2.0, BSD-2/3, ISC, 0BSD, BlueOak-1.0.0; review MPL-2.0, LGPL; deny GPL/AGPL/SSPL/BUSL/"source-available" without owner approval. Mind custom licenses: GSAP is free including former club plugins but forbids use in tools that help build a Webflow competitor, and Webflow may update terms [40]; PolyForm Shield on `sfw` forbids competing products [34]. Automate with `license-checker-rsep`/`pip-licenses` or deps.dev API in CI.
8. Bus factor and governance: >= 2 active maintainers or a foundation/company backing, release cadence in the last 12 months, issue response time, funding (sponsors) visible; avoid single-maintainer packages that are small and have broad transitive reach (the chalk/debug incident was one maintainer's account [see B2]).
9. Security hygiene: publishes with provenance/trusted publishing, has SECURITY.md, no install scripts (or justified), no native binaries unless unavoidable.
10. Exit cost: how hard is removal (own wrapper module, Standard Schema-compatible APIs reduce lock-in).

### B2. Supply-chain threat landscape (2025-2026) and mitigations

Incidents (secondary sources, cross-checked between several):
- **Sep 8 2025, chalk/debug/qix**: a spear-phish from lookalike `npmjs.help` took over maintainer "qix"; 18-25 packages (counts vary by vendor) with ~2 billion weekly downloads shipped crypto-wallet-hijacking code; exposure about 2 to 2.5 hours before removal [Check Point, Wiz, Strobes, StepSecurity in list].
- **Shai-Hulud (Sep 2025) and Shai-Hulud 2.0 (Nov 2025)**: self-replicating worm that steals tokens in `preinstall`/`postinstall` scripts and republishes the victim's other packages; its propagation relied on install scripts, so `ignore-scripts`/strict build allow-lists would have stopped the payload [Snyk, pnpm blog] [23].
- **May 2026 "Mini Shai-Hulud" (TanStack)**: reportedly abused GitHub Actions cache poisoning so malicious packages published through legitimate OIDC trusted publishing and looked properly built [Cloudsmith]. Lesson: trusted publishing and provenance prove where something was built, not that the workflow was uncompromised.
- Yossarian's analysis of 10 attacks: 8 had exploitation windows under a week (chalk under 12 h, Nx 4 h, web3.js 5 h, tj-actions 3 days; xz ~5 weeks and Kong ~10 days were outliers) [26]. A 7-day cooldown blocks most, 14 days blocks all but xz [26]. He estimates 80-90% exposure reduction and notes the cost: delayed fixes.

Mitigation stack (priority order):
1. **Cooldown everywhere** [25]: pnpm `minimumReleaseAge` (minutes; 10.16, Sep 2025) with `minimumReleaseAgeExclude`; npm `min-release-age` (days; 11.10, Feb 2026) with `min-release-age-exclude` (11.17) [27]; Yarn `npmMinimalAgeGate`; Bun `minimumReleaseAge`; uv `exclude-newer = "7 days"` with `exclude-newer-package` and `false` to opt a package out [29]; pip `--uploaded-prior-to` (relative durations 26.1); Poetry `solver.min-release-age`. Dependabot `cooldown.default-days` (default 3; applies to version updates only, never security updates) [31]. Renovate `minimumReleaseAge`. Security fixes bypass via explicit exclude after review. One source claims pnpm 11 defaults to a nonzero minimum age; unverified, set it explicitly regardless.
2. **Block install-time code**: pnpm `strictDepBuilds: true` + allow-list (`allowBuilds`/`onlyBuiltDependencies`) [23][24]; npm `ignore-scripts=true` [27]. 
3. **pnpm `trustPolicy: no-downgrade`**: fails if a version has weaker publish trust (Trusted Publisher > Provenance > none) than an earlier one, catching the "stolen token, published from laptop" pattern; exclude list for legitimate migrations [23]. Also `blockExoticSubdeps` (settings page lists it; semantics not verified here) [24].
4. **Lockfile discipline**: commit lockfile, `pnpm install --frozen-lockfile`/`npm ci` in CI, review lockfile diffs in PRs (GitHub dependency review) [36], pin GitHub Actions to commit SHAs, `Dangerous-Workflow`/`Token-Permissions` checks via Scorecard Action [32]. Lockfile linting (`lockfile-lint`) is a known tool; I did not fetch it, so verify before adopting.
5. **Own releases** (any repo that publishes): npm trusted publishing via OIDC (npm CLI >= 11.5.1, Node >= 22.14, GitHub Actions/GitLab/CircleCI cloud runners), auto provenance on GitHub/GitLab, then set "Require 2FA and disallow tokens" [28]. Immutable releases + artifact attestations on GitHub [36]. Given the TanStack case, also isolate publish workflows from cache restore and untrusted PR code [pnpm/Cloudsmith].
6. **Detection layer**: Dependabot alerts and malware alerts [36]; optional Socket (C) [34]; `npm audit`/`pnpm audit --audit-level=high` in CI (`audit-level` controls exit code [27]).
7. Python: `uv lock` with `exclude-newer`; lockfile in CI with `uv sync --locked`; hashes via uv lock; `pip-audit` (PyPI advisory DB by default, `-s osv` for OSV, `--locked` for pylock files, exit code 1 on findings; GitHub Action `pypa/gh-action-pip-audit`) [30]; pip-audit docs do not mention uv, so export requirements from uv (`uv export --no-hashes`... or `--format requirements-txt`) and feed that, or use `uv audit` if the installed uv has it (not verified).

### B3. Minimal high-quality library picks

(Each is a recommendation, justified; none is mandatory if the repo does not need the capability.)

- **Validation: Zod 4** as default; Valibot as an option for client-bundle-critical code. Zod 4: 14.7x faster string parsing, 7.4x arrays, 6.5x objects vs Zod 3; ~175 vs 25,000+ type instantiations; core 5.36 kB gz, Zod Mini 1.88 kB gz; first-party `z.toJSONSchema()` [38]. Valibot's own comparison (author-written, so promotional bias): ~1.37 kB for a login form vs Zod ~15-17.7 kB, Zod Mini ~3.9-6.9 kB; runtime roughly on par with Zod 4 [39]. Zod wins on ecosystem (tRPC, RHF resolvers, AI SDKs, Next docs); keep schemas behind a thin module, and prefer libs that accept Standard Schema (Vitest 4 `expect.schemaMatching` accepts Zod/Valibot/ArkType [43]; TanStack Form is schema-library agnostic by validator design, not verified in detail [44]) to keep exit cost low.
- **Dates: use `Intl.DateTimeFormat`/`Date` for display; Temporal for logic once available.** Temporal is "Limited availability", not Baseline per MDN; polyfills `@js-temporal/polyfill` or FullCalendar's `temporal-polyfill` [42]. Default: no date library; if arithmetic is needed today, `date-fns` v4 (tree-shakable; not fetched, from background knowledge) or the Temporal polyfill loaded lazily. Avoid Moment, Day.js plugins sprawl.
- **Forms: Server Actions + native `FormData` + Zod for simple forms; React Hook Form (mature, small, uncontrolled) or TanStack Form (headless, type-safe, multi-framework [44]) only for complex/dynamic forms.** Not fully verified; pick one per org, not per repo.
- **Charts for dashboards: Recharts** for standard business charts (React, declarative); visx or ECharts only for heavy or custom needs; uPlot for time-series at high point counts. Recharts 3 migration page fetch failed (404), so version facts are unverified. Always put the chart behind a client component and lazy-load.
- **Animation: Motion (`motion`, ex-Framer Motion) as default for React UI** (tree-shakable, native WAAPI/ScrollTimeline with JS fallback for springs/gestures [41]; its docs promote the paid Motion+ add-on, commercial interest). **GSAP** only for complex timelines/scroll scenes: since Apr 30 2025 it is free for commercial use, former paid plugins (SplitText, MorphSVG) included, under the Webflow Standard License with the competing-builder restriction and unilateral license-update clause [40] (Webflow-owned, commercial). CSS transitions/View Transitions first. Per owner rule: respect `prefers-reduced-motion`, animate transform/opacity only.
- **Testing: Vitest 4** (browser mode stable, `toMatchScreenshot` visual regression, Standard Schema matchers [43]) + **Playwright** for E2E and component/visual checks + **Testing Library** only if component tests remain jsdom/happy-dom-based; **MSW** for network mocks (from background knowledge, unverified here). Python: pytest, pytest-cov, hypothesis (property tests) where logic is pure.
- Things to avoid adding: lodash (use native), axios (fetch), classnames/clsx beyond one tiny helper, moment, uuid (`crypto.randomUUID()`), dotenv (Node `--env-file`), ts-node (Node type stripping/tsx), `ts-morph`-based tools during the TS 7 transition [12].

### B4. Dependency ADR (see template in "Dependency policy template" below). MADR 4.0.0 is the best base: sections Context/Problem, Decision Drivers, Considered Options, Decision Outcome (+ Consequences, Confirmation), Pros and Cons, More Information; optional YAML front matter status/date/decision-makers [37].

---

## Recommended standards with deviations

TypeScript
1. Base: Google TS Style Guide [1] for semantics; Biome formatter for layout (so 2-space, 100-col, double quotes, semicolons "always" is fine, matches Google except quotes/indent defaults which Google does not mandate strongly).
2. Deviations (document in each repo's AGENTS.md):
   - No `enum`; unions/`as const` objects (erasableSyntaxOnly, Node stripping) [15][17].
   - Default exports allowed only for framework entry files (Next route files, `*.config.ts`).
   - camelCase for `as const` config objects; CONSTANT_CASE only for primitive module constants.
   - `type` aliases permitted for unions/mapped types; `interface` for extendable object shapes.
   - `undefined` internal, `null` only at I/O boundaries [2].
   - No `namespace`, no parameter properties, no `import =`, no decorators (Node cannot run them [17]).
   - `#private` allowed (Google bans it); TS `private` is not erasable-problematic but `#` is runtime-private and fine. Pick one per repo; recommended `private` for consistency with Google, `#` acceptable in new code. 
3. tsconfig: strict + noUncheckedIndexedAccess + exactOptionalPropertyTypes (on by default for new repos, per-repo opt-out with comment) + verbatimModuleSyntax + erasableSyntaxOnly + noImplicitOverride; TS 7 as `tsc`; TS 6 alias only if a tool needs the API [12][13].
4. Lint: Biome 2.x pinned exactly (`--save-exact`), domains `next`, `react`, `test` auto; enable `project` domain rules (`noImportCycles`, `noUndeclaredDependencies`); enable `types` domain only after benchmarking scan cost; optional CI-only `oxlint --type-aware` for `no-unsafe-*`/exhaustiveness gaps [5][10]. No typescript-eslint unless a plugin is indispensable.
5. Configs: `next.config.ts`, `*.config.ts`, scripts as `.mts` on Node >= 24.12 [17][18]; keep JSON/YAML/`.mjs` where the tool lacks TS loading.

Python
1. PEP 8 via `ruff format` (line 100, double quotes) + Google docstring convention (`pydocstyle` `convention = "google"`), `requires-python >= 3.13`.
2. Ruff families listed in A6; mypy strict; pytest; `uv` with `exclude-newer`.
3. Deviations from Google guide: line length 100 not 80; named imports allowed; no pylint; relative imports within a package allowed; type hints required on all functions (stricter than Google's "public APIs").

---

## Dependency policy template

Place at `docs/dependency-policy.md` per repo, with ADRs in `docs/adr/NNNN-use-<pkg>.md`.

**Policy**
- New dependency requires an ADR (MADR 4.0 short form) in the same PR; dev dependencies need a one-line justification in the PR.
- Gates (all must pass or be waived in the ADR): license allow-list; no install scripts (or allow-listed); Scorecard >= 5 or documented reason; >= 2 maintainers or organization backing; release in last 12 months; no open critical advisories; client bundle added <= 10 kB gz unless approved; zero or minimal transitive deps; no overlap with platform/stdlib or an existing dependency.
- Review cadence: quarterly prune (`knip`/`depcheck`, `deptry` for Python), license and audit re-scan.
- Updates: Dependabot/Renovate weekly grouped; `cooldown` 7 days (patch 3, major 14); security updates immediate after manual diff review; no auto-merge for runtime deps, auto-merge allowed for dev patch with green CI.
- Install hardening: pnpm `minimumReleaseAge: 10080` (7 days, minutes), `strictDepBuilds: true`, `trustPolicy: no-downgrade`, exact versions for tools (Biome, TypeScript), `--frozen-lockfile` in CI; npm repos `min-release-age=7`, `ignore-scripts=true`; uv `exclude-newer = "7 days"` and `uv sync --locked` in CI.
- CI: `pnpm audit --audit-level=high`, `pip-audit`, Dependabot alerts + dependency review on PRs, Scorecard Action, GitHub Actions pinned by SHA, least-privilege `permissions:`.
- Publishing (if any): trusted publishing OIDC, provenance, tokens disallowed.

**ADR template (MADR-based)**
```
---
status: proposed | accepted | superseded by NNNN
date: YYYY-MM-DD
decision-makers: owner
---
# Use <package> for <capability>
## Context and Problem Statement
## Decision Drivers   (need, platform alternative checked, bundle budget, license)
## Considered Options (1. platform/own code  2. <pkg>  3. <alt>)
## Decision Outcome   chosen option and why
### Evidence table
| Check | Result |
| License | |  | Maintainers / bus factor | | Last release | | Scorecard | | Install scripts | | Transitive deps | | Gzip size delta | | Open advisories | |
### Consequences      (lock-in, exit plan, wrapper module location)
### Confirmation      (how we verify: bundle analyzer budget, lint rule, test)
## More Information   (links to deps.dev, Scorecard, changelog)
```

---

## Contested / uncertain

1. **Biome type-aware status**: official rule page still says nursery for `noFloatingPromises` while release posts claim type-aware rules were stabilized; the type inference is a deliberately incomplete subset (false negatives accepted) [6][7][9]. Re-check the changelog before relying on it as the only floating-promise guard.
2. **Second linter**: oxlint type-aware is "very close" to typescript-eslint parity per its own docs but needs TS 7, has memory caveats on huge repos [10]; typescript-eslint is blocked on the TS 7 API until 7.1 [12]. Choice depends on whether gaps actually bite; start with none.
3. **`exactOptionalPropertyTypes`**: strict benefit versus friction with third-party types [16]. No consensus; per-repo opt-out is the pragmatic answer.
4. **Enums**: Google permits them [1]; erasable-only world forbids them [15][17]. We follow the latter, which is a minority position among large style guides but forced by tooling.
5. **TS 7 naming and details**: official post says `tsc`; secondary sources mention `tsgo` and conflicting summaries [12]. Speedup figures are vendor-reported [12][14].
6. **Cooldown length**: 7 days covers most historical attacks, 14 days nearly all [26]; cost is delayed bug fixes and cooldowns do not stop slow or targeted attacks (xz). Also unresolved: whether a rolling or locked cutoff is used by uv in each mode (official page: timestamp computed at resolution and recorded in the lockfile, not slid automatically [29]; one secondary guide said otherwise).
7. **Trusted publishing is not a panacea**: the May 2026 TanStack case (secondary source) shows OIDC publishing via a poisoned CI cache; treat provenance as necessary, not sufficient.
8. **Snyk Advisor**: sunset inferred from a redirect, not an official notice [35].
9. **Unverified library facts** (not fetched, background knowledge): date-fns v4, React Hook Form, Recharts 3, Playwright, MSW, bundlephobia/pkg-size internals, `lockfile-lint`, `ty` maturity, pnpm 11 default release age, `blockExoticSubdeps` semantics, `uv audit` availability. Verify before codifying.
10. **Valibot vs Zod size/perf numbers** come from the Valibot project itself [39] and Zod's own post [38]; both self-interested, neither independent.
11. **Config conversion**: PostCSS and some tool loaders lack TS support; payoff small versus risk, so `.mjs` remains acceptable there.

---

## Sources

(C) = commercial interest or vendor-authored.

Primary / official
1. Google TypeScript Style Guide: https://google.github.io/styleguide/tsguide.html
2. Microsoft TypeScript Coding guidelines (wiki): https://github.com/microsoft/TypeScript/wiki/Coding-guidelines (C: Microsoft, but internal-contributor doc)
3. ts-standard: https://github.com/standard/ts-standard
4. Biome rule sources: https://biomejs.dev/linter/rules-sources/
5. Biome domains: https://biomejs.dev/linter/domains/
6. Biome noFloatingPromises: https://biomejs.dev/linter/rules/no-floating-promises/
7. Biome + Vercel type inference (Apr 2025; Vercel-sponsored work): https://biomejs.dev/blog/vercel-partners-biome-type-inference
8. Biome blog index (v2.4, 2.5, 2.6): https://biomejs.dev/blog/
9. Biome v2.5 post: https://biomejs.dev/blog/biome-v2-5/
10. Oxlint type-aware docs: https://oxc.rs/docs/guide/usage/linter/type-aware.html
11. typescript-eslint blog: https://typescript-eslint.io/blog
12. Announcing TypeScript 7.0: https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/ (C: vendor claims)
13. Announcing TypeScript 6.0: https://devblogs.microsoft.com/typescript/announcing-typescript-6-0/
14. TypeScript devblog index: https://devblogs.microsoft.com/typescript/
15. Announcing TypeScript 5.8 (erasableSyntaxOnly): https://devblogs.microsoft.com/typescript/announcing-typescript-5-8/
16. exactOptionalPropertyTypes: https://www.typescriptlang.org/tsconfig/exactOptionalPropertyTypes.html
17. Node.js TypeScript docs: https://nodejs.org/api/typescript.html
18. Next.js next.config.js docs: https://nextjs.org/docs/app/api-reference/config/next-config-js
19. Google Python Style Guide: https://google.github.io/styleguide/pyguide.html
20. Ruff rules: https://docs.astral.sh/ruff/rules/
21. Ruff formatter: https://docs.astral.sh/ruff/formatter/
22. Ruff repo pyproject: https://github.com/astral-sh/ruff/blob/main/pyproject.toml
23. pnpm newsroom supply-chain post: https://pnpm.io/blog/2025/12/05/newsroom-npm-supply-chain-security
24. pnpm settings: https://pnpm.io/settings
25. Nesbitt, "Package managers need to cool down" (Mar 2026): https://nesbitt.io/2026/03/04/package-managers-need-to-cool-down
26. Yossarian, "We should all be using dependency cooldowns": https://blog.yossarian.net/2025/11/21/We-should-all-be-using-dependency-cooldowns
27. npm config docs: https://docs.npmjs.com/cli/v11/using-npm/config
28. npm trusted publishers: https://docs.npmjs.com/trusted-publishers
29. uv resolution / cooldowns: https://docs.astral.sh/uv/concepts/resolution/
30. pip-audit: https://github.com/pypa/pip-audit
31. Dependabot options reference: https://docs.github.com/en/code-security/dependabot/working-with-dependabot/dependabot-options-reference
32. OpenSSF Scorecard: https://github.com/ossf/scorecard
33. deps.dev / Open Source Insights: https://deps.dev/
34. Socket Firewall (C): https://socket.dev/blog/introducing-socket-firewall
35. Snyk Advisor redirect (C): https://snyk.io/advisor/ -> https://security.snyk.io/
36. GitHub supply chain security: https://docs.github.com/en/code-security/supply-chain-security/understanding-your-software-supply-chain/about-supply-chain-security
37. MADR: https://adr.github.io/madr/
38. Zod 4 release notes: https://zod.dev/v4
39. Valibot comparison (C-ish: project's own page): https://valibot.dev/guides/comparison/
40. GSAP Standard License (C: Webflow): https://gsap.com/standard-license/
41. Motion docs (C: Motion+ upsell): https://motion.dev/docs/react-quick-start
42. MDN Temporal: https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Temporal
43. Vitest 4 announcement: https://vitest.dev/blog/vitest-4
44. TanStack Form overview: https://tanstack.com/form/latest/docs/overview

Secondary (search-result pages; read as snippets only, treat as lower confidence)
45. Check Point, "The great npm heist, September 2025" (C): https://blog.checkpoint.com/crypto/the-great-npm-heist-september-2025/
46. Wiz, npm attack on debug/chalk (C): https://www.wiz.io/blog/widespread-npm-supply-chain-attack-breaking-down-impact-scope-across-debug-chalk
47. StepSecurity, 20 popular packages compromised (C): https://www.stepsecurity.io/blog/20-popular-npm-packages-compromised-chalk-debug-strip-ansi-color-convert-wrap-ansi
48. Strobes, npm phishing compromise (C): https://strobes.co/blog/npm-package-compromised-phishing-attack
49. Endor Labs, chalk/debug (C): https://endorlabs.com/learn/major-supply-chain-attack-compromises-popular-npm-packages-including-chalk-and-debug
50. Snyk, npm security best practices after Shai-Hulud (C): https://snyk.io/articles/npm-security-best-practices-shai-hulud-attack
51. Mondoo, npm supply chain defenses 2026 (C): https://mondoo.com/blog/npm-supply-chain-security-package-manager-defenses-2026
52. Cloudsmith, TanStack mini Shai-Hulud (C): https://cloudsmith.com/blog/tanstack-npm-packages-compromised-in-mini-shai-hulud-attack
53. Semgrep, rolling out dependency cooldowns (C): https://semgrep.dev/blog/2026/rolling-out-dependency-cooldowns-org-wide
54. pydevtools, uv supply-chain protection: https://pydevtools.com/handbook/how-to/how-to-protect-against-python-supply-chain-attacks-with-uv/
55. Evil Martians, secure npm releases: https://evilmartians.com/chronicles/the-secure-way-to-release-an-npm-package
56. InfoQ, TypeScript 7 released: https://infoq.com/news/2026/08/typescript-7-released/
57. Visual Studio Magazine, TS 7 RC/GA coverage: https://visualstudiomagazine.com/articles/2026/07/08/typescript-7-arrives-to-rock-vs-code-with-go-powered-speed.aspx
58. DEV Community, Node 24 type stripping field notes: https://dev.to/jsmanifest/typescript-without-tsc-in-2026-type-stripping-in-nodejs-24-bun-and-deno-compared-1k46
59. DEV Community, Biome v2 type inference limits: https://dev.to/herrington_darkholme/trying-out-biome-v2s-type-inference-and-knowing-its-limits-1j36
60. Jake Champion mirror of "Faster type-aware lint rules: Biome vs Oxlint": https://hn.jakechampion.name/reader/https://www.solberg.is/fast-type-aware-linting
