# Progress log — pequeverso-assistant-api

Updated only at milestones (ecosystem 3A). Append a new section per milestone; never rewrite history. A new session reads `RESUME.md` first.

## M0 — Plan written (pending merge to develop)

| Field | Value |
|---|---|
| Milestone | M0 Plans merged (the docs-only PR of `docs/master-plan/` into `develop` is the exit action) |
| Date | 2026-11-09 |
| develop SHA at baseline | `6912579245506bbd60f745243905ce4974dfbfe9` (merge of PR #98, 2026-10-19); `origin/main` `e3e69960472b68c2ae8955e720c81893a2138803` |
| Checkpoint tag | `checkpoint/M0` after the plan PR merges (owner-approved push) |

### Scorecard snapshot (planner estimates, provisional until the M3 independent re-score; `scorecard.md`)

| Lens 1 | D1 | D2 | D3 | D4 | D5 | D6 | D7 | D8 | mean |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 88 | 80 | 72 | 72 | 70 | 55 | 72 | 65 | 71.8 |

| Lens 2 (API mapping) | P1 | P2 | P3 | P4 | P5 | P6 | mean |
|---|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 80 | 85 | 62 | 78 | 85 | 85 | 79.2 |

Lens 3 (assistant messaging for CRO): 80.

### Measured baseline (develop `6912579`, details in `audit.md`)

1,698 tests passed, 45 skipped; line coverage 84.95%, branch 76.5% (local, services absent); mypy strict 0 errors; ruff 0 on the current rule set (1,331 findings on the ecosystem families); 19 functions above complexity 10 (max 36, `create_app`); Trivy: 1 CRITICAL (`certifi 2026.7.22`, GHSA-6q48-6c7w-9gw2) and 51 HIGH, all base-OS; recall@3 0.689 and recall@5 0.737 overall, English 0.167 (6 cases), out-of-scope 0.00, support 0.364, stale-data 0.40, purchase-process 0.429; real-model review 195 of 245 turns acceptable (0 P1, 4 P2).

### What changed

Only `docs/master-plan/` is added (planning). No code, deploy, spend or production change.

### Next item

**PVA-M1.2 — P0 certifi.** Replace `.github/dependabot.yml` with the weekly multi-ecosystem group, close the 8 stale `dependabot/*` branches with a pointer, have the owner switch Dependabot security updates off. certifi is fixed by the manual PR `fix/deps-certifi` (certifi `2026.10.18` only), opened by 2026-11-11 and merged by 2026-11-13; the first weekly PR follows on Monday 2026-11-16 09:00 America/Argentina/Buenos_Aires. Then M1.4 (`ci.yml` and `ci-gate`).

### Known issues

- Dependabot currently opens several PRs and has 8 remote branches; the 7-day critical SLA for certifi ends on 2026-11-16 (manual PR by 2026-11-13).
- Local coverage understates PostgreSQL adapter coverage (service-gated tests); the combined value is unknown until M2.3.
- No live model evidence exists for `develop`; the last real runs used the 2026-10-18 and 2026-10-19 sources.
- `AGENTS.md` still says `main` is the default branch and requires the check named `checks`.
- `docs/reference/evaluation.md` case counts are stale (see `audit.md` P2-3).

### Pending owner decisions

none: all PVA decisions are resolved by delegation (README section 6). Owner inputs (3, the only ones): (1) the one-time 20% spot-check of judge labels (DR-05, about 1 h); (2) owner-only repository and release actions: applying the ruleset requiring `ci-gate`, private vulnerability reporting on, Dependabot security updates off, GitHub App or PAT for release-please, merging the weekly Dependabot PR, the release-please PR and the promotion to `main` (M7); (3) the standing per-run authorization before any live or paid run, including the VPS purchase and activation (MV; DR-04 caps apply).

## M1 — Foundation (agent work merged; checkpoint pending)

| Field | Value |
|---|---|
| Milestone | M1 Foundation: every task merged or parked; `checkpoint/M1` is tagged by the orchestrator after verification |
| Date | 2026-11-14 |
| develop SHA | `cad7f5b1613a3f4f1a6b48ae6adeaf0caad500f0` (merge of PR #127) before this docs PR |
| Standards | `engineering-standards` v1.0.0 (`1f33be46bcb95f42f550f74608bc679cae5575ad`), `standards.lock` |

### What changed

| Task | PR | Result |
|---|---|---|
| PVA-M1.2 | #116 | certifi 2026.10.23 on develop (GHSA-6q48-6c7w-9gw2 fixed there); single weekly multi-ecosystem `dependabot.yml`; security-update PRs off, alerts on (verified) |
| PVA-M1.3 | #124 | classifier and `pull_request_target` workflow retired (about 750 lines); `deps-weekly-guard` caller; `tests/test_dependabot_config.py`; skill `api-review-weekly-dependencies` |
| PVA-M1.4 | #126 | `ci.yml` with `classify`, `.github/ci-profile.json`, shared docs and security jobs, `ci-gate`; `checks` kept as an alias until the ruleset switch; markdownlint and lychee green |
| PVA-M1.5 | #120 | pytest-xdist and pytest-randomly, `unit`/`services` lanes, `pyyaml` and `types-PyYAML` declared |
| PVA-M1.6 | #125 | Scorecard, daily vulnerability job (tracker issue #123), read-only settings check; CodeQL default setup enabled |
| PVA-M1.7 | #122 | hadolint, container-structure-test, dockle, CycloneDX SBOM artifact, Grype gate, reproducibility check; base Python 3.14.10 (liblzma5 pin dropped, zlib1g pinned until the base ships it) |
| PVA-M1.8 | #127 | community files and hooks from the standard (drift-checked), CONTRIBUTING (absorbs `docs/engineering-standards.md`), CODEOWNERS, justfile, retired-domain test, AGENTS workflow wording |
| PVA-M1.9 | #121 | `.agents/skills` canonical, metadata, trigger stubs, validator and tests |
| PVA-M1.11 | #118, #124 | ADR-0012, ADR-0015, ADR-0016 |
| Carry-overs | #119 | owner decisions (OD-76) and README template resynced; "daily job notifies" wording already followed OD-75; Biome not applicable (no `package.json`, PVA-D2b) |

Parked: PVA-M1.1 (E2 sandbox observation Monday 2026-11-16), PVA-M1.10 (release-please needs an owner GitHub App).

### Exit criteria evidence

- develop green on the full profile: every merge ran all jobs (push runs always run everything); last PR run all green including `ci-gate`.
- Weekly PR: configured and tested on develop; not observable yet (Monday 2026-11-16) and only effective once the config reaches `main` (see Known issues).
- Image builds reproducibly with SBOM: two consecutive `identical manifests` results (run 43556888072 and its re-run), SBOM artifact `sbom-app-cyclonedx`, 0 fixable High or Critical with one tracked, expiring ignore (CPython 3.14.11 unreleased, issue #123, expires 2026-12-14).
- CI durations (latest green PR run): classify 18 s, static 56 s, database 182 s, container 176 s, gate 15 s; job critical path about 4.5 min, wall time 8.8 min with runner queueing. The 10-run p50 for PVA-M1.5 and the docs-only budget are still to be measured.

### Known issues

- **GitHub reads Dependabot config, scheduled workflows, `workflow_dispatch` and `pull_request_target` from the default branch `main`** (PVA-D17). Until M7 or an owner-authorized hotfix: Dependabot keeps the old multi-PR config (first run Monday 2026-11-16 06:00 ART), the old classifier still runs on PRs, and `deps-weekly-guard` (schedule), `vuln-daily`, Scorecard and `drift` (schedule) do not run.
- Dependabot alert #1 (certifi) stays open because `main` still has certifi 2026.7.22.
- `.python-version` stays 3.14.8 (local uv 0.12.10 cannot install 3.14.10); the image runs 3.14.10.
- The Dependabot group is `weekly-all`; the standard name is `weekly` (drift warning only).
- HEALTHCHECK calls `/health/ready`; the plan text says `/health/live` (left unchanged, liveness semantics are out of M1 scope).
- Bytecode is compiled with one sorted `compileall` (`UV_COMPILE_BYTECODE=0`) for reproducibility, a justified deviation from ecosystem 8.2.

### Owner inputs needed

1. Authorize a hotfix to `main` limited to `.github/dependabot.yml` (and optionally the guard and scheduled workflows), before Monday 2026-11-16 06:00 ART, or accept several Dependabot PRs until M7.
2. Apply the `ci-gate` ruleset (`engineering-standards/scripts/apply-rulesets.sh --flow release`, dry run first), then remove the `checks` alias.
3. Enable private vulnerability reporting (SECURITY.md relies on it).
4. GitHub App or token for release-please (PVA-M1.10).

### Next item

PVA-M1.1 after the Monday observation (update ADR-0016), then M2 starting with PVA-M2.1 (ruff migration) once `checkpoint/M1` is tagged.

## M2 — Quality net (agent work merged)

| Field | Value |
|---|---|
| Milestone | M2 Quality net: every task merged |
| Date | 2026-11-15 (last M2 merge #144); M2.6 part B merged 2026-11-21 (#151) |
| Checkpoint tag | `checkpoint/M2` by the orchestrator |

| Task | PR | Result |
|---|---|---|
| PVA-M2.1 | #129, #130 | ruff format at 100 columns; ecosystem families with a legacy ratchet (`ratchets/ruff.json`) |
| PVA-M2.2 | #132 | import-linter contracts, complexity ratchet (19 functions), vulture |
| PVA-M2.3 | #136 | branch coverage floors, diff-coverage gate |
| PVA-M2.4 | #133, #134 | golden set v1 (60 items), schema v2 loader, grader registry |
| PVA-M2.5 | #138 | cassette replay at the provider port, golden gate in CI |
| PVA-M2.6 | #146, #151 | full set v2 (318 items), audited qrels, baseline, retrieval ratchet; repair steps 1 and 2 (Spanish folding, curated query lexicon): recall@5 0.730 to 0.880, holdout 0.757 to 0.843 |
| PVA-M2.7 | #142 | red-team pack mapped to OWASP LLM |
| PVA-M2.8 | #135 | ten Hypothesis properties, `ci` and `nightly` profiles |
| PVA-M2.9 | #140 | mutmut lane with a module ratchet (PR floor 60%) |
| PVA-M2.10 | #139, #144 | security matrix, fault injection, SSE conformance; oasdiff gate, Schemathesis, stateful links |
| PVA-M2.11 | #137 | Locust SSE load harness, nightly |
| PVA-M2.12 | #141 | `scripts/scorecard.py` and the nightly quality workflow |
| PVA-M2.13 | #131 | prompt lock per `PROMPT_VERSION` |
| PVA-M2-X | #145 | assistant v2 scaffolding with red memory tests |

## M3 — Phase A polish (agent work merged; checkpoint pending)

| Field | Value |
|---|---|
| Milestone | M3 Phase A polish: every task merged or parked; `checkpoint/M3` is tagged by the orchestrator after verification |
| Date | 2026-11-21 |
| develop SHA | `2675e7d` (merge of #151) plus the docs PRs #156 and #159 before this PR |

| Task | PR | Result |
|---|---|---|
| PVA-M1.1 (carried) | #152 | ADR-0016 records the observed weekly Dependabot run: one `weekly-all` PR at 09:24 ART on Monday, superseded by Dependabot itself, never two open; default branch is now `develop` |
| PVA-M3.1 | #154 | contract revision 1.6: analytics ingest in `openapi.json`, new `openapi.internal.json` (health, ops), oasdiff gate over both specs; ingest example kept apart from the pinned analytics source set |
| PVA-M3.2 | #149 | `LOG_STREAM`; CLIs log to stderr; third-party records below WARNING counted; `prompt_version` on terminal runs; only server-generated request ids logged; `Clock` injected; AST test for wall-clock calls |
| PVA-M3.3 | #148 | `/healthz` and `/readyz` with `version` and `schema_version`; generated `contracts/env.schema.json`; HEALTHCHECK on `/healthz`; ADR-0019 |
| PVA-M3.4 | #153, #155, #156, #158 | ADR Confirmation sections, ADR-0013 (RFC 9457 mapping, table tested) and ADR-0014; Diátaxis layout with a link guard; README on the template with the README check on; generated evaluation numbers with a `--check`; rewritten `ci.md` and `dependency-updates.md` |
| PVA-M3.5 | #151, #157 | per-family recall@5 at or above the M2 baseline; eight catalog content gaps as owner questions in `docs/explanation/business-questions.md` |
| PVA-M3.6 | this PR | first independent re-score, `scorecard.md` section "M3 independent re-score (2026-11-21)" |
| PVA-M3.8 | #159 | every operation of revision 1.6 documented with examples validated against the specs |

Parked: PVA-M3.7 (real golden cassettes and a live pass^3 need the owner's authorization and spend).

### Exit criteria evidence

- **P0 and P1:** P0-1 closed. P1-2 and P1-6 closed. P1-1 is partly closed: the golden gate runs in CI, but language and purchase-process recall stay below 0.70 and there is no live gate. P1-5 is mostly closed; image provenance and publication are scheduled for M7. P1-3 (complexity) is deferred to M4 by the plan. P1-4 (85% coverage floor) is deferred to PVA-M4.12, at the M4 exit. Source: the independent re-score.
- **First re-score recorded:** Lens 1 mean 80.8, Lens 2 mean 86.3, Lens 3 84 (`scorecard.md`).
- **No regression against the M2 ratchets:** retrieval raised; ruff, complexity, coverage and golden ratchets hold; the mutation PR floor passed on the changed `evidence.py`; `contracts.export --check` and `docs_numbers --check` green.

### Known issues

- `ratchets/mutation.json` has no recorded per-module scores (`modules: {}`). The PR floor applies, but the M2.9 baseline record is missing. To fix early in M4: record it from the weekly full-scope run.
- ADR numbering shifted. ADR-0018 is release tagging (M1.10) and ADR-0019 is the health aliases, so the plan's M4 ADR for the SQLite fixture profile (PVA-D12) takes the next free number.
- Recommendation for PVA-M4-X: in fixture mode, decline and no-information answers often lack the support link (`docs/explanation/business-questions.md`). A `validate_final` rule could attach it in code; confirm on the live lane.
- The ingest spec does not document the `Origin` header or the route/section pairing, and Schemathesis reaches only the disabled-channel 404 for ingest (#154 follow-ups).
- The local commit guard reads gitleaks' default rules, not `.github/gitleaks.toml`, so merge commits that touch manifest digest lines trip it. Prefer a rebase on unpushed task branches.

### Owner inputs needed

1. Authorize and fund PVA-M3.7: record real golden cassettes and run the first live pass^3.
2. Answer the catalog content questions 8 to 15 in `docs/explanation/business-questions.md`.
3. Still open from M1: private vulnerability reporting; merging the weekly Dependabot PR (#150). The `develop` ruleset already requires `ci-gate` (read 2026-11-21), so the `checks` alias job can be retired in M4.

### Next item

M4, starting with PVA-M4.1 (split `create_app`) once `checkpoint/M3` is tagged. Record the mutation baseline first.

## In-flight tasks

Updated on each task merge (one row per task from `roadmap.md` that is `in-progress` or finished since the last milestone; the roadmap Status column is authoritative). Find the true next task with the RESUME command in `roadmap.md` (last section).

| Task ID | Branch / PR | Status | Last update |
|---|---|---|---|
| PVA-M1.1 to M1.11 | #116, #118 to #127, #143, #152 | done | 2026-11-21 |
| PVA-M2.1 to M2.13, M2-X | see the M2 section | done | 2026-11-21 |
| PVA-M3.1 to M3.6, M3.8 | see the M3 section | done | 2026-11-21 |
| PVA-M3.7 | - | parked (owner authorization and spend) | 2026-11-21 |

## Ecosystem status (nine repositories; identical table in every repo)

| Repo | Plan | Milestone | Branch and SHA at planning (`git rev-parse origin/<branch>` after `git fetch -q`, 2026-11-09) | Notes |
|---|---|---|---|---|
| portfolio | v2 written | M0 | `develop` `0a1ff564f66475a1d9a360a9c927ac804accbf83` | bilingual site; hero particle system v2 |
| portfolio-assistant-api | v2 written | M0 | `develop` `e749ca762fb3f1e74225d9126d4eb1bbd88e2885` | RAG assistant API; eval and typing debt |
| portfolio-backoffice | v2 written | M0 | `develop` `e356b13d81d509e640b3b318c0d37c7b4abcce1c` | assistant and site analytics ops |
| pequeverso | v2 written | M0 | `develop` `cbf519ce9c49f35a2536d4606520221a4a6debe0` | Spanish-only store; consent opt-in ships at M7 |
| pequeverso-assistant-api (this repo) | v2 written | M0 | `develop` `6912579245506bbd60f745243905ce4974dfbfe9` | Spanish-only shopping assistant API; golden set and judge validation |
| pequeverso-backoffice | v2 written | M0 | `develop` `4d4fb9633f2d355ed80b3f05407cbd3a2a5cf5e0` | local folder `pequeverso-assistant-backoffice` |
| vps-ops | v2 written | M0 | `main` `f52c3e693250b17a2f8783f83cf1b5bf8097f238` | private, main-only; VPS not bought |
| pequeverso-marketing | v2 written | M0 | `main` `7d26bf4240c9034e339ee4545e5f883c75fd816f` | private, main-only; Spanish plan |
| dropshipping-ops | v2 written | M0 | `main` `8ff028365944ee69ef47fd7a871b1b63da4be089` | private, main-only; exploratory business line |

(SHAs read with `git -C <repo> rev-parse origin/<branch>` after `git fetch -q` on 2026-11-09; the other rows are refreshed from the ecosystem tracker when the M0 PRs merge; this repo does not own them.)
