# Roadmap — pequeverso-assistant-api

Milestones M0 to M7 and MV follow ecosystem section 3A. Every milestone is a safe point: `develop` green on the full `release` CI profile, `progress.md` updated, tag `checkpoint/M<n>` pushed on `develop`, ecosystem tracker row recorded. Work lands on `develop` through task branches and `ci-gate`; `main` is untouched until M7. Effort is S (up to 4 agent-hours), M (5 to 12), L (more than 12); hours are agent work, not owner time. Calendar targets assume 3 to 4 agents working in parallel and are planning estimates, not commitments. Phase mapping: A = polish (M1 to M3), B = architecture and typing (M4), C = end state (M5 to M7), V = VPS-gated (MV).

| Milestone | Phase | Agent-hours (sum of item rows below, including assistant v2 tasks) | Calendar target |
|---|---|---:|---|
| M0 Plans merged | - | 1 | 2026-11-10 |
| M1 Foundation | A | 40 | 2026-11-17 (first weekly PR on 2026-11-16) |
| M2 Quality net | A | 109 (99 plus 8 for PVA-M2-X plus 2 for owner-authorized cassette recording) | 2026-11-27 |
| M3 Phase A polish | A | 43 | 2026-12-04 |
| M4 Architecture and typing | B | 71 (60 plus 3 for PVA-M4.12 plus 8 for PVA-M4-X) | 2026-12-11 |
| M5 API and conversational UX | C | 26 (18 plus 8 for PVA-M5-X) | 2026-12-14 (runs in parallel with the M4 tail and M6 preparation; M5 starts once PVA-M4-X lands) |
| M6 Excellence verified | C | 42 | 2026-12-18 |
| M7 Release to main | C | 9 | 2026-12-21 (after all nine repos reach M6) |
| M8 Profile showcase | C | 2 | after every repo reaches M7 |
| MV VPS activation | V | 20 (17 plus 3 for PVA-MV-X; this repo) | after owner purchase and authorization |

Total 363 agent-hours (sum of the rows; arithmetic, critical path and RESUME command in the last section). Owner time is not counted: about 1.5 h for the golden-set Spanish review (PVA-M2.4) and about 1 h for the one-time judge-label spot-check (PVA-M6.2).

## M0 Plans merged (S)

| ID | Item and acceptance | Effort | Status |
|---|---|---|---|
| PVA-M0.1 | Docs-only PR of `docs/master-plan/` into `develop` (profile `docs`). Acceptance: files on develop, markdown renders, links resolve, `progress.md` shows M0. Risk: none. Cross-repo: all nine repos merge their plans; ecosystem tracker row. | S 1 | todo |
| PVA-M0.2 | Decision list PVA-D1 to PVA-D19 recorded in the README (all resolved by delegation; nothing for the owner to decide). | S 0 (part of M0.1) | todo |

## M1 Foundation (L, 40 h)

Start with **M1.2** (time-critical P0, 7-day SLA ends 2026-11-16); M1.1 and the rest run in parallel.

| ID | Item | Effort | Acceptance criteria | Status |
|---|---|---|---|---|
| PVA-M1.1 | (parallel, not a prerequisite for M1.2) Consume the Dependabot sandbox proof (shared, ecosystem E2): four unverified points recorded in an ADR | S 3 | result in ADR-0016; if grouped-PR update fails, the guard's supersede flow is used | todo |
| PVA-M1.2 | **P0 certifi**: replace `.github/dependabot.yml` with the multi-ecosystem weekly group; close the 8 stale `dependabot/*` branches with a pointer comment; owner turns Dependabot security updates off and alerts on | S 2 | default path: manual single-dependency PR `fix/deps-certifi` (certifi 2026.10.18 only) opened by 2026-11-11 and merged by 2026-11-13, so the 7-day SLA (ends 2026-11-16) has 3 days of margin; the new `dependabot.yml` is merged before 2026-11-16 and exactly one open Dependabot PR exists on 2026-11-16 09:00 ART; Grype reports 0 critical Python findings | todo |
| PVA-M1.3 | Retire `dependency-policy.yml`, `scripts/dependabot_policy.py`, `.github/dependabot-policy.json`, `tests/test_dependabot_policy.py`; add `deps-weekly-guard` and `tests/test_dependabot_config.py` | S 2 | 750 lines removed; no `pull_request_target` left; guard run green | todo |
| PVA-M1.4 | `ci.yml` with `classify`, `ci-profile.json`, shared reusable workflows, `ci-gate` beside `checks`; owner applies the ruleset script; remove `checks` | L 8 | `tests/test_ci_profile.py`: every tracked path in a group; docs-only PR runs in ≤ 2 min; required context is `ci-gate` on `develop` and `main` | todo |
| PVA-M1.5 | Speed and hygiene: pytest-xdist and pytest-randomly, `unit` markers, declare `pyyaml` and `types-PyYAML`, baseline CI durations | S 3 | unit lane p50 ≤ 90 s locally; PR critical path p50 ≤ 5 min measured over 10 runs | in-progress |
| PVA-M1.6 | Security workflows: CodeQL (python, actions), Scorecard weekly, dependency-review, daily osv-scanner issue, settings check (secret scanning, push protection, private vulnerability reporting) | M 4 | all green on develop; Scorecard score recorded; daily job opens a labelled issue in a dry run | in-progress |
| PVA-M1.7 | Container: canonical Dockerfile, hadolint, dockle, container-structure-test, Grype, Syft SBOM as CI artifact, `.grype.yaml` ignores with issue and 90-day expiry, drop the `liblzma5` pin when the base has the fix | M 6 | image reproducible (same digest twice with `SOURCE_DATE_EPOCH`), SBOM artifact present, 0 fixable High or Critical, labels present; `HEALTHCHECK` keeps calling `/health/live` (the `/healthz` alias does not exist before PVA-M3.3) | in-progress |
| PVA-M1.8 | Community files (the new `SECURITY.md` names only a pequeverso.com contact mailbox, OD-53; a grep test bans the retired `digitalproductsteam.com` domain from M1 on), issue forms, PR template, CODEOWNERS, `CONTRIBUTING.md` (absorbs `docs/engineering-standards.md`), `AGENTS.md` workflow wording and `just check` | M 4 | the 8 files exist; AGENTS commands equal the `justfile` (test); `docs/engineering-standards.md` deleted | todo |
| PVA-M1.9 | Skills layout inverted (`.agents/skills` canonical), metadata added, `validate_skills.py` and `test_skills.py` updated, activation-eval skeleton for 6 skills | M 4 | `.claude/skills/*` are relative symlinks; validator green; each skill has `evals/triggers.json` stub | in-progress |
| PVA-M1.10 | release-please manifest and config validated in a sandbox (E5) | S 2 | sandbox produces a release PR with the Keep a Changelog sections | todo |
| PVA-M1.11 | ADR-0012 (flat layout), ADR-0015 (licence exceptions), ADR-0016 (weekly PR and SLA) | S 2 | ADRs merged with Confirmation sections | in-progress (ADR-0012 and ADR-0015 in this PR; ADR-0016 with PVA-M1.3) |

Exit (safe point): develop green on the release profile; one weekly PR observed or simulated; image builds reproducibly with SBOM. Risks: Dependabot group behaviour differs from the docs (mitigated by the guard); `engineering-standards` repo not yet created (E1) so reusable workflows do not exist (mitigation: vendor the workflows into this repo and switch to `uses:` later, same job names); ruleset script needs owner action. Cross-repo: `engineering-standards` (E1), `vps-ops` none yet.

## M2 Quality net (L, 109 h)

| ID | Item | Effort | Acceptance criteria | Status |
|---|---|---|---|---|
| PVA-M2.1 | Mechanical ruff migration (100 columns, double quotes) as its own PR with `.git-blame-ignore-revs`; safe autofixes; family fixes; per-file ignores; `requires-python >= 3.14`; Pyrefly non-blocking job | M 10 | `ruff check` 0 with the ecosystem families (S2 scope for docstrings); `ratchets/ruff.json` at 0 for fixed families; mypy still 0 | todo |
| PVA-M2.2 | import-linter contracts in warn mode with negative fixtures; complexity ratchet file; vulture | M 5 | `lint-imports` reports 0 broken contracts; `ratchets/complexity.json` holds the 19 baseline functions | todo |
| PVA-M2.3 | Coverage with branch, combined data from static and `database` jobs, floors, diff-cover 90% | S 4 | combined branch coverage recorded; interim floor = max(76, combined) in `ratchets/coverage.json`, valid only until the M4 exit (2026-12-11); diff coverage gate blocks a PR with an untested change | todo |
| PVA-M2.4 | **Golden set v1**: schema v2 loader, 60 items, grader registry with the 5 new graders | L 14 | strata counts per `assistant-quality.md` section 3; loader rejects a malformed item; all deterministic graders unit-tested; item review by the owner for Spanish naturalness (owner action, about 1.5 h for 60 items at 1.5 min each; not counted in agent-hours) | todo |
| PVA-M2.5 | Cassette record and replay at the provider port, scripted adversarial cassettes, `assistant-quality` profile in CI; (optional, owner-authorized) record real cassettes | M 8 (+2) | golden replay 100% in CI with no network; a changed prompt hash fails with a clear re-record message; fork PR lane works without secrets | todo |
| PVA-M2.6 | **Full set v2**: cleaning, qrels audit, 30 new items, `evals/full/baseline/`, ranx metrics, retrieval repair steps 1 and 2 | L 14 | 288 + 30 items valid; baseline report committed; `ratchets/retrieval.json` per family and language; overall recall@5 ≥ 0.85 on the fixture lane (no English recall target, OD-32); the 4 new English items and the 3 golden English items pass the polite-Spanish-reply grader | todo |
| PVA-M2.7 | Red-team pack from 22 to about 48 attacks mapped to OWASP LLM01, 07, 08, 09, 10 | M 5 | 40 to 60 attacks, 100% handled; each class has at least 3 | todo |
| PVA-M2.8 | Ten Hypothesis properties with profiles `ci` and `nightly` | M 7 | all pass at 1000 examples nightly; shrunk failures recorded as regression examples | todo |
| PVA-M2.9 | mutmut spike (CPython 3.14, `forkserver`), baseline, thresholds | M 6 | scoped baseline score recorded in `ratchets/mutation.json`; PR incremental run under 30 min; equivalent-mutant list reviewed | todo |
| PVA-M2.10 | oasdiff gate, Schemathesis (50 PR, 500 nightly, 3 stateful links), SSE conformance, security matrix (100% of mutating routes), fault-injection tests | L 10 | `oasdiff breaking` 0 without label; matrix test fails if a route is unlisted; fault tests assert degraded behaviour | todo |
| PVA-M2.11 | Locust SSE load harness (12 concurrent streams, fixture provider) nightly | M 5 | thresholds from `testing.md` section 1 asserted nightly; baseline recorded | todo |
| PVA-M2.12 | `scripts/scorecard.py` aggregating CI artifacts into `scorecard.json`, ratchet baselines, nightly workflow failing on regression | M 8 | `scorecard.json` produced nightly; a deliberately regressed baseline fails the job | todo |
| PVA-M2.13 | ADR-0010, ADR-0011, ADR-0017; prompt lock test and `prompt-changelog.md` | S 3 | changing `INSTRUCTIONS` without a version bump fails a unit test | todo |

Exit: `scorecard.json` produced nightly; no gate in warn mode older than 14 days; golden set 100% in cassette replay. Risks: mutmut or ranx incompatible with CPython 3.14 (spikes and fallbacks defined); ruff migration conflicts with open PRs (run it alone); recording real cassettes needs owner authorization and spend (fixture and scripted lanes still gate; P3 floor 90 stands). Cross-repo: none blocking; consumers learn nothing new until M3.

## M3 Phase A polish (M, 43 h)

| ID | Item | Effort | Acceptance criteria | Status |
|---|---|---|---|---|
| PVA-M3.1 | Complete `openapi.json` (add analytics ingest), new `openapi.internal.json` (health, ops, analytics read), contract revision 1.6 (current is 1.5), examples; handoff to storefront and backoffice repos | M 6 | `contracts.export --check` green; oasdiff shows additive-only changes; cross-repo consumer-compile jobs green | todo |
| PVA-M3.2 | Logging: `LOG_STREAM`, `httpx` and `httpcore` at WARNING, aggregate external events, `prompt_version` in the `run` event, request-id propagation test, `Clock` injection in `official_help` and `telemetry` | S 4 | a corpus run emits JSON on stdout and no log line on it; 0 `datetime.now` outside bootstrap (AST test) | todo |
| PVA-M3.3 | Health aliases `/healthz` and `/readyz` with `version` and `schema_version`; generated env schema; handoff note for `vps-ops` | S 4 | both path families return 200; env schema test against `.env.example`; ADR-0018; in the same PR the Dockerfile `HEALTHCHECK` switches to `/healthz` and the container-structure-test asserts it (the old `/health/live` and `/health/ready` stay served) | todo |
| PVA-M3.4 | Docs: README rewrite, Diátaxis moves with link fixes, regenerate `docs/reference/evaluation.md`, rewrite `ci.md` and `dependency-updates.md`, ADR Confirmation sections, ADRs 0013 and 0014 | L 14 | lychee 0 broken links; README headings check green; no stale counts (docs-numbers check) | todo |
| PVA-M3.5 | Weak-family repair beyond the lexicon: out-of-scope and purchase-process routing checks; list catalog content gaps for the owner (support hours, purchase steps) | M 6 | recall@5 per family at or above the M2 baseline; gaps listed as owner questions in `docs/explanation/business-questions.md` | todo |
| PVA-M3.6 | First independent re-score (fresh agent, three lenses) | M 4 | `scorecard.md` updated with evidence; every P0 and P1 closed | todo |
| PVA-M3.7 | (Owner-authorized, spend-gated) record real golden cassettes, first live pass^3 | S 3 | report committed under `evals/reports/`; if any item fails, it is fixed or quarantined with owner and deadline | todo |
| PVA-M3.8 | `docs/reference/api-contract.md` with the RFC 9457 mapping and per-operation request, response and SSE examples | S 2 | every operation documented with an example that validates against the schema | todo |

Exit: P0 and P1 closed with evidence; first re-score recorded; no regression versus M2 ratchets. Risks: documenting health aliases before `vps-ops` consumes them (old paths stay); owner authorization for M3.7 may lag. Cross-repo: `pequeverso` refreshes its contract snapshot; `pequeverso-backoffice` compiles against `openapi.internal.json`; `vps-ops` reads the new health and env schema.

## M4 Architecture and TypeScript or typing (L, 71 h)

| ID | Item | Effort | Acceptance criteria | Status |
|---|---|---|---|---|
| PVA-M4.1 | Split `create_app` and `lifespan` into wiring, lifespan and routes | M 8 | functions ≤ 10; runtime shutdown, cohort and container smoke tests unchanged | todo |
| PVA-M4.2 | `fail_closed` as a rule table | S 3 | one test per rule; messages unchanged | todo |
| PVA-M4.3 | `ChatService` `start` and `events` into named steps | L 12 | golden replay and cancel, replay and budget-race tests unchanged; mutation score not lower | todo |
| PVA-M4.4 | `finalize` and `check_content` stage extraction | M 6 | same | todo |
| PVA-M4.5 | Analytics router and validators | S 4 | analytics HTTP tests unchanged | todo |
| PVA-M4.6 | The remaining 11 functions above 10 | M 8 | `ratchets/complexity.json` empty | todo |
| PVA-M4.7 | import-linter in enforce mode, empty baseline; AST test reduced to banned calls and SQL and Cypher location | S 3 | negative fixtures fail the build | todo |
| PVA-M4.8 | `.cjs` to `.mts`, tools job, Node pin aligned with the fleet | S 2 | `node --test` green on the `.mts`; no `.cjs` tracked | todo |
| PVA-M4.9 | Execute PVA-D12: retire or keep the SQLite fixture profile and the one-shot ledger-extension script | M 6 | decision recorded in ADR-0019 and applied | todo |
| PVA-M4.10 | Python 3.15 non-blocking CI job; decide Pyrefly blocking | S 2 | job present; decision in the PR | todo |
| PVA-M4.11 | Ruff and docstring ratchets to zero for the enforced scope | M 6 | `ratchets/ruff.json` empty | todo |
| PVA-M4.12 | Coverage ratchet to the ecosystem floor: raise branch coverage (combined) to ≥ 85 with tests, not exclusions, and set `ratchets/coverage.json` to 85 | S 3 | combined branch coverage ≥ 85 on `develop` by the M4 exit (2026-12-11); the interim 76 floor is removed | todo |

Exit: guards enforce with an empty baseline; 0 type errors; contract cross-jobs green. Risk: behaviour drift while splitting `chat.start` (mitigation: golden replay, mutation before and after, one function per PR, architecture review agent).

## M5 API and conversational UX (M, 26 h)

The API has no visual layer; rubric lens 2 maps to error clarity, streaming UX, message quality, contract docs and consumer consistency.

| ID | Item and acceptance | Effort | Status |
|---|---|---|---|
| PVA-M5.1 | Streaming UX check: time-to-first-delta and inter-event gaps asserted in the live lane and in the load nightly | S 3 | todo |
| PVA-M5.2 | Conversational polish driven by the judge criteria (needless clarification, generic support guidance, repetitive cards) through the prompt gate; needs live runs, spend-gated | M 8 | todo |
| PVA-M5.3 | Contract documentation completeness: every event and error with an example | S 4 | todo |
| PVA-M5.4 | Consumer parity: storefront and backoffice contract tests pass against API 1.7 (blocks revision, PVA-M5-X) | S 3 | todo |

Exit: P1, P2, P4, P5 and P6 at or above 95 on an independent score; P3 at 90 or above.

## M6 Excellence verified (L, 42 h)

| ID | Item and acceptance | Effort | Status |
|---|---|---|---|
| PVA-M6.1 | Mutation scores at target (75 on scoped modules): kill survivors by tests, not by loosening | M 10 | todo |
| PVA-M6.2 | Judge validation with owner labels (40 pass and 40 fail per criterion bootstrapped by two independent agents, owner spot-check of 20% once, DR-05) and judged quality ≥ 95% on the full set; deterministic graders gate until validated; owner time about 1 h for the one-time 20% spot-check (about 32 of 160 labels, 2 min each) | M 6 | todo |
| PVA-M6.3 | Full-set live run: hybrid retrieval recall@5 ≥ 0.90 per family, English is checked only for a polite Spanish reply, OD-32; spend-gated, PVA-D13: USD 2 per campaign, USD 8 per month, DR-04 | M 6 | todo |
| PVA-M6.4 | Independent three-lens re-score; close remaining gaps | M 8 | todo |
| PVA-M6.5 | Two consecutive green nightly scorecards at ≥ 95 per axis, or ≥ 90 where the plan names the blocker; `ratchets/coverage.json` branch floor ≥ 85 | S 2 | todo |
| PVA-M6.6 | MV-R (VPS readiness, OD-64; part of the M6 exit): release-candidate API image built by the `release` profile with SBOM, provenance and a verified digest, kept as a CI artifact or in a private registry namespace without deploying (DR-13); Postgres 18 and Neo4j 5.26 images likewise; `vps-ops` registry entry and Coolify configuration as code for this API; secrets inventory (names only) and SOPS template; backup, monitoring and alert configuration validated with `promtool`; participation in the full-stack rehearsal on a disposable Ubuntu 26.04 VM and the day-one runbook | M 6 | todo |
| PVA-M6.7 | OD-09 copy refresh before release: README, repository description, topics and contract documentation updated to the final state from verified facts only; the catalog snapshot copy stays Spanish (es-419, tú, signed "Equipo de Pequeverso") | S 3 | todo |
| PVA-M6.8 | OD-53 sweep (also a standing check from M1): no `digitalproductsteam.com` reference anywhere (SECURITY.md, support contact in the catalog snapshot, docs, fixtures); a grep test fails on any remaining reference | S 1 | todo |

Exit: every axis ≥ 95 (D6, D7 and P3 may stay ≥ 90 only for VPS, spend or labels, stated in `scorecard.md`).

## M7 Release to main (S, 9 h; after all nine repos reach M6)

| ID | Item and acceptance | Effort | Status |
|---|---|---|---|
| PVA-M7.1 | Merge the release-please PR (owner), promote `develop` to `main` with a merge commit under the `release` profile | S 3 | todo |
| PVA-M7.2 | Immutable releases on; tag `v1.1.0` (contract v1 stays compatible, so a minor); build the image once; SBOM, provenance, verification; record the digest | S 3 | todo |
| PVA-M7.3 | PR to `vps-ops` `releases/production.lock` with digest, version and attestation URL | S 2 | todo |
| PVA-M7.4 | Automatic back-merge, CHANGELOG check, tag `checkpoint/M7` | S 1 | todo |

Order across repos (ecosystem 18.2): APIs first, then backoffices and sites, then `vps-ops` pins. Post-release check: image labels and `build` revision equal the release SHA.

## M8 Profile showcase (S, 2 h; after every repo reaches M7)

Provide the featured-project entry for the GitHub profile redesign (OD-08): description, topics, social preview and verified measured results (golden set size and gate, mutation score, release provenance) for this API; the profile README is owned by `gonzalomartinperez/gonzalomartinperez`. Exit: repo metadata matches the final state; `checkpoint/M8`.

## MV VPS activation (gated, M, 20 h for this repo)

Starts only after the owner buys the VPS and authorizes spend (ecosystem invariant 8).

| ID | Item and acceptance | Effort | Status |
|---|---|---|---|
| PVA-MV.1 | Deploy by digest through `vps-ops` (health and readiness checks, migrations gated by a fresh backup marker, graceful shutdown). | S 4 | todo |
| PVA-MV.2 | SLO dashboards and alerts from `deploy/monitoring/` (availability 99.5% monthly, non-LLM p95, separate time-to-first-token SLO), validated with `promtool`. | S 4 | todo |
| PVA-MV.3 | Online counters: price-replacement and discount-replacement rate pages the owner at any non-zero value; abstain-rate shift over 5 points in 7 days opens a ticket (content-free by design). | S 3 | todo |
| PVA-MV.4 | Live golden pass^3 = 100% against the deployed API under the spend cap. | S 2 | todo |
| PVA-MV.5 | Load run on the real host (3 times expected peak concurrent streams). | S 3 | todo |
| PVA-MV.6 | Owner activates the storefront assistant flag (owner-only). | S 1 (owner) | todo |

## Cross-repo dependencies (summary)

| Repo | Needs from this repo | This repo needs |
|---|---|---|
| `engineering-standards` (E1) | - | reusable workflows, rulesets script, templates, `standards.lock` |
| `pequeverso` | contract snapshot refresh after M3 and M7 | none |
| `pequeverso-backoffice` | `openapi.internal.json` and schemas after M3 | none |
| `vps-ops` | health aliases, env schema (M3), image digest (M7) | `releases/production.lock`, deploy contract checks |
| `portfolio-assistant-api` | optional reuse of `evals/` by copy later | read-only reference only |

Any change to image, health, contracts or `infra/docker` requires the matching `vps-ops` lock and inventory update (ecosystem 18.1).

## Assistant experience v2 tasks (see [assistant-experience.md](assistant-experience.md))

These rows are included in the totals of the milestone named in the Milestone column. Contract numbering in this repo: current revision 1.5; PVA-M3.1 ships 1.6 (complete spec, internal spec); PVA-M5-X ships 1.7 (blocks, progress, capabilities, feedback, memory).

| ID | Milestone | Task | Acceptance criteria | Effort | Status |
|---|---|---|---|---|---|
| PVA-M2-X | M2 | Test scaffolding: block and event JSON Schemas with examples, `guarantee.days` and block-price graders, item-schema extensions, memory isolation tests on a spy port, overhead harness, injection fixtures | at least 2 schemas with 6 examples each validate; new graders unit-tested at 100% of branches; memory isolation tests fail (red) against a stub for the right reason; overhead harness reports p50 and p95 per stage | M 8 | todo |
| PVA-M4-X | M4 | Ports and graph nodes (one structured call kept), validators in `validate_final`, block builder from the catalog snapshot, prompt prefix byte-stability test, flags default off | golden replay 100% on cassettes; every PVA-M2-X test green; all flags default off; ADR-0003 and ADR-0008 unchanged | M 8 | todo |
| PVA-M5-X | M5 | Contract revision 1.7: `blocks`, `run.progress`, `capabilities`, feedback endpoint, memory endpoints (flag off) | `contracts.export --check` green; `oasdiff` additive-only against 1.6; widget hides thumbs only when `capabilities.feedback` is false; consumer contract tests green | M 8 | todo |
| PVA-MV-X | MV | Live lane with latency; enable `progress_events`, `blocks_v2`; memory only after legal review (DR-07); `web_official_help` last, after ADR-0008 gates | live golden pass^3 = 100% with p95 latency recorded; each flag enabled alone with 7-day observation; rollback by flag tested; owner authorization for the run | S 3 | todo |

## Task status, critical path and RESUME

Status values: `todo`, `in-progress`, `done (PR #, SHA)`. Update the Status cell in the same PR that completes the task, and the "In-flight tasks" section of `progress.md` on each task merge.

Critical path (calendar): PVA-M1.2 (certifi, 2026-11-13) -> PVA-M1.4 (`ci-gate`) -> PVA-M2.1 (ruff migration, alone) -> PVA-M2.4 (golden set) -> PVA-M2.5 (cassettes) -> PVA-M2.12 (scorecard) -> PVA-M3.6 (re-score) -> PVA-M4.3 (`ChatService`) -> PVA-M6.1 and PVA-M6.2 -> PVA-M6.5 -> PVA-M7.1 (needs all nine repos at M6).

Wall-clock arithmetic: M0 to M6 is 1 + 40 + 109 + 43 + 71 + 26 + 42 = 332 agent-hours; over four parallel streams that is about 83 h per stream, at about 8 productive agent-hours per working day about 10.4 working days of pure work. The calendar targets (2026-11-10 to 2026-12-18, 29 weekdays) add owner merges, authorizations, labels and the serial ruff migration. M7, M8 and MV (31 h) are gated by other repos or by the owner.

Total: 1 + 40 + 109 + 43 + 71 + 26 + 42 + 9 + 2 + 20 = **363 agent-hours** (item rows and the assistant v2 tasks above, including 2 h of owner-authorized cassette recording).

RESUME (find the true next task mid-milestone):

```bash
git log --oneline --grep 'PVA-M'                       # merged task IDs in commit and PR titles
gh pr list --state all --search 'PVA-M in:title'       # open and merged task PRs
grep -n '| todo |\|in-progress' docs/master-plan/roadmap.md | head -5   # first todo row is the next task
```

Put the task ID (for example `PVA-M1.2`) in every task branch name, PR title and merge commit.
