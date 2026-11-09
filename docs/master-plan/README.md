# Master plan v2 — pequeverso-assistant-api

Dated 2026-11-09 against develop `6912579245506bbd60f745243905ce4974dfbfe9`. Language: English (repository documentation); the assistant itself speaks Spanish only (ADR-0006). **Planning only:** nothing in this folder authorizes code, deployment, spend or production changes; the owner decides each phase. This repository had no earlier plan, so there is no "Changes from v1" section; the plan is labelled v2 because it follows the fleet's v2 template and ecosystem standard v1 (`ecosystem.md`, `rubrics.md`), as the tracker in `progress.md` shows.

## 1. Purpose

Bring the Pequeverso shopping-assistant API to the ecosystem standard and keep it there: a hexagonal service that already enforces its commercial invariants in code (prices, guarantees and claims only from the catalog) gets a release gate for assistant quality, a quality net (coverage, mutation, properties, contracts, load), a dynamic and supply-chain-hardened CI, canonical containers, community files and a self-resuming harness. The first dated action is a P0: `certifi 2026.7.22` (CRITICAL, GHSA-6q48-6c7w-9gw2) is fixed by a manual single-dependency PR (`fix/deps-certifi`) merged by 2026-11-13; the first weekly dependency PR follows on 2026-11-16.

Baseline (measured 2026-11-09, `audit.md`): 1,698 tests, line coverage 85% (branch 76.5% local), mypy strict 0 errors, 19 functions above complexity 10 (max 36 in `create_app`), 51 base-OS HIGH findings and 1 CRITICAL dependency finding, `openapi.json` with 4 paths, retrieval recall@3 0.69 overall and 0.17 in English. Scores: Lens 1 mean 71.8, Lens 2 mean 79.2 (`scorecard.md`).

## 2. Owner requirements

Ecosystem requirements (verbatim intent, `ecosystem.md` section 2.1):

1. Nine master plans (OD-01), one per repo, polished to the maximum, grounded in deep 2025-2026 research.
2. "Perpetual excellence": quality does not degrade over time (ratchets, automatic scorecard, cadences).
3. Consistent READMEs across the nine repos.
4. Assistants: a golden set of RAG questions, 100% correct as release gate.
5. Complete testing: unit, integration, mutation, E2E, contract, visual, a11y, performance, security, load, property-based.
6. Agentic harness (skills, reviewers, evals) good enough that the owner does not need to review code.
7. Use the available skills and harness.
8. First-class, consistent containers: LTS versions, same base configuration, same practices.
9. CI at the maximum: dynamic (runs only what is affected), secure, fast.
10. Dependabot identical in all nine: exactly one PR per week per repo.
11. Maximum redesign of both backoffices (not this repo).
12. Master UI/UX on both public sites (not this repo).

Repo-specific, binding: ADR-0006 (Spanish-only native assistant, "tú", no language selector); two evaluation tiers (golden about 60 at 100% and full about 320 without a pass gate; `owner-decisions.md`); pragmatism (rigor where it reduces real risk, no ceremony); the repository's own AGENTS.md (advisory and read-only, fixture by default, no paid call without explicit current authorization, grounding in code, contract v1 backward compatible, content-free operations data); integration on `develop`, `main` for releases only; identity `gonzalomartinperez` only.

## 3. Method

1. Read the owner decisions, ecosystem standard, rubrics, template and the 13 research notes (8 cited and copied into `research/`).
2. Read the repository read-only at `origin/develop`: AGENTS.md, README, docs and 9 ADRs, CI, `pyproject.toml`, all of `app/`, evaluation scripts and data, tests layout, Dockerfiles, contracts.
3. Use the measured audit (pytest, coverage, mypy, ruff, Trivy, corpus and retrieval runs), and add three measurements that the audit lacked: recall@1/3/5/10 per family and language, ruff with the ecosystem families, and a format-migration count (`audit/`).
4. Apply the ecosystem standard and record only justified deviations (decisions PVA-D1 to PVA-D19).
5. Write the roadmap against ecosystem milestones M0 to M7 and MV with measurable acceptance.

## 4. Decisions table

Status: **planned** = the planner decided, reversible by the owner; **owner** = needs the owner (section 6). Sources are research notes in `research/` or repo evidence.

| ID | Decision | Why | Sources | Alternatives rejected | Status |
|---|---|---|---|---|---|
| PVA-D1 | Golden set of 60 items; English 5% (3 items: a polite-Spanish-reply and language-switch block) instead of the ecosystem minority-locale 30%; named stratum | Owner decision OD-32: Pequeverso sells only to a Spanish-speaking audience; assistant and store are Spanish-only (ADR-0006); English cases only verify a polite Spanish reply; owner size guidance 40 to 80 | ADR-0006, OD-32, `owner-decisions.md`, [03] | 30% or 15% English (tests a path the product does not serve); no English at all (the polite reply must be verified) | resolved (OD-32) |
| PVA-D2 | Keep the flat `app/` package, no `src/` layout; no Biome or `package.json` for 3 TypeScript files (D2b) | deployable service; imports across 225 Python files and the deploy contract name `app.*`; the `src/` benefit is already neutralized | `target-state.md` sections 6 and 7, [02] | `src/` migration; npm toolchain | planned |
| PVA-D3 | Keep the six layer names; enforce with import-linter plus a smaller AST guard | renames are ceremony; import-linter gives independence contracts and external-package rules | [02] section 2 and recommendations | rename to `ports/`, `api/`; AST-only | planned |
| PVA-D4 | Decompose the 19 functions above complexity 10, starting with `create_app` (36), behind the golden gate and mutation, with a complexity ratchet | rubric D2 critical criterion; the composition root is the one real structural defect | `audit/complexity-over-10.txt`, [10] | big-bang rewrite; raise the limit | planned |
| PVA-D5 | Record and replay cassettes at the provider port, not at HTTP with vcrpy | provider is already a port; streaming SDK internals and headers make HTTP cassettes brittle; prompt hash in the key forces deliberate re-record | [03] sections 3.2 and 14 (adapted) | vcrpy at HTTP; fixture provider only | planned |
| PVA-D6 | Keep the v1 error envelope and document its RFC 9457 mapping; no wire change | breaking change needs a major and ADR; messages are machine-first, user copy belongs to the storefront | `contracts/examples/errors.json`, ecosystem 18.1 | switch to `application/problem+json` now | planned |
| PVA-D7 | Keep the in-house allowlist JSON log formatter; no structlog | it enforces per-logger event and field schemas, stronger than structlog processors; fixing noise is a config change | `app/bootstrap/logging.py`, [02] section 10 | structlog | planned |
| PVA-D8 | The only judge is an independent Claude reviewer agent (different family from the OpenAI generator), advisory until validated against owner labels; never gates safety | no second paid provider key; the existing agent review practice becomes protocol; safety is deterministic | [03] section 7, ecosystem 12.3 | LLM judge via paid API; no judge | planned |
| PVA-D9 | One weekly Dependabot PR (multi-ecosystem group); retire the eligibility classifier workflow, script, JSON and test (750 lines); the ecosystem SLA supersedes the 2026-10-19 "image CVEs advisory" note; certifi is fixed by a manual single-dependency PR by 2026-11-13 (default, 3 days of SLA margin); later criticals use the weekly PR unless the SLA needs the manual path | owner rule and decision O1; the classifier decides nothing when the owner merges one PR; removes a `pull_request_target` workflow | `shared/dependabot-rule.md`, [05] sections 5 and 7 | keep per-PR classifier; separate security PRs | resolved (delegated) |
| PVA-D10 | Adopt ecosystem style: 100 columns, double quotes, extended ruff families, in one mechanical PR with `.git-blame-ignore-revs` | cross-repo consistency; ruff does it; 204 of 225 files change | `audit/ruff-ecosystem-families.txt`, [10] | keep 110 and single quotes | planned |
| PVA-D11 | Rename the required check `checks` to `ci-gate` through the ruleset script, with a transition job, never `--admin` | ecosystem 6.1 single gate name; avoids per-repo drift | ecosystem 6.5, [05] | keep `checks` | resolved (delegated); owner applies the ruleset |
| PVA-D12 | Decide the future of the SQLite fixture profile (`app/adapters/sqlite/`, 5 files) and the one-shot `scripts/extend_evaluation_envelope.py`: keep as credential-free default, or retire after PostgreSQL fixtures replace it | AGENTS.md makes SQLite the credential-free default; retirement removes code but changes the local profile | `file-index.csv`, ADR-0001, ADR-0009 | decide now | resolved (delegated) |
| PVA-D13 | Spend caps for live evaluations: USD 2 per evaluation campaign and USD 8 per month for the assistant's evaluations, hard stop in code; production assistant budget stays USD 10 per month (DR-04) | one golden k=3 run costs about USD 0.10 to 0.25; full set about 0.18 to 0.41 | `assistant-quality.md` sections 2 and 8, real-run records | no cap; larger cap | resolved (DR-04) |
| PVA-D14 | Judge calibration labels: the planner bootstraps 40 pass and 40 fail labels per judged criterion (2 criteria) with two independent agents; the owner spot-checks a 20% sample once (DR-05); until validated, release gates rely on deterministic graders only | judge validity needs labels (E11); until validated the judge is informational and the P3 floor is 90 | [03] section 7 | skip the judge; all labels by the owner | resolved (DR-05); owner spot-check |
| PVA-D15 | Licence exceptions by ADR: `psycopg` and `psycopg-pool` (LGPL-3.0, runtime, dynamic use), `hypothesis` (MPL-2.0, dev only) | no equivalent permissive library; neither is modified or shipped statically | `dependencies.md`, [10] | asyncpg, hand-written examples | resolved (delegated) |
| PVA-D16 | No promptfoo; in-repo pytest red-team pack with the existing graders; garak optional offline | graders exist in Python; promptfoo adds Node and OpenAI ownership | [03] section 11 | promptfoo | planned |
| PVA-D17 | Default branch: keep `main` (released state) and fix the wording; agents open PRs with `--base develop`. Option: switch the default to `develop` | ecosystem only requires releases on `main`; the public face stays the released state; wrong-base PRs are prevented by template and skill | AGENTS.md, ecosystem 3.1 | default `develop` (pequeverso uses it) | resolved (delegated) |
| PVA-D18 | Prompt versioning in git: keep `PROMPT_VERSION`, add a content-hash lock, changelog and pins in every run; no prompt hub | prompts must pass the same gate as code; runtime tracing is off by ADR | [03] section 12 | LangSmith prompt commits | planned |
| PVA-D19 | `requires-python >= 3.14` with a non-blocking 3.15 job; Dependabot `ignore` keeps the Python image on 3.14.x until fleet policy moves | ecosystem 8.1; a stale branch proposes 3.15.0 | [11] section 1 | follow 3.15 now | planned |

## 5. Limits of this plan

- A 100% golden result bounds the failure rate (about 5% at 60 items), it does not prove perfection; the plan reports per-stratum counts.
- Without an authorized live recording, the gate proves server-side enforcement against recorded and scripted outputs, not model behaviour. P3 (assistant message quality) therefore has a **floor of 90** until live pass^3 and owner labels exist; D6 and D7 have a **floor of 90** until the VPS exists (MV). Everything else targets 95.
- Retrieval recall targets of at least 0.90 per family need real embeddings (spend); on the offline lexical lane the target is 0.85 overall at recall@5. There is no English retrieval target (OD-32).
- Baseline scores are planner estimates anchored to evidence; the first independent re-score is M3. Coverage understates service-gated code until the combined measurement (M2.3).
- Unverified items stay marked where used: Dependabot group behaviour (ecosystem 5.4), mutmut and ranx on CPython 3.14, package licences, the certifi advisory text, release-please on `develop`.
- This plan cannot see consumer repositories' current state; cross-repo steps are listed as dependencies, not assumed done.
- The audit's `eval-corpus` outputs begin with log lines (noisy stdout), so JSON was extracted before analysis.
- Declined nice-to-have: none. The interim branch-coverage floor of 76% is dated (valid until the M4 exit, 2026-12-11; ≥ 85 by PVA-M4.12 and re-checked at PVA-M6.5). The interim tracker location is `vps-ops` until `engineering-standards` exists (RESUME section 2).

## 6. Open decisions: resolved by delegation (owner, 2026-11-09)

The owner delegated every open decision to the planner (`owner-decisions.md`, Delegated resolutions). Each row below is Resolved (delegated, 2026-11-09) as the recommendation. Owner inputs (3, the only ones): (1) the one-time 20% spot-check of judge labels (DR-05, about 1 h); (2) owner-only repository and release actions: applying the ruleset requiring `ci-gate`, private vulnerability reporting on, Dependabot security updates off, GitHub App or PAT for release-please, merging the weekly Dependabot PR, the release-please PR and the promotion to `main` (M7); (3) the standing per-run authorization before any live or paid run, including the VPS purchase and activation (MV; DR-04 caps apply).

| ID | Decision | Resolution |
|---|---|---|
| PVA-D12 | Retire or keep the SQLite fixture profile and the ledger-extension script | Resolved (delegated, 2026-11-09): Keep SQLite until the `database` job proves a PostgreSQL-only local profile (M4), then retire it with ADR-0019; retire `extend_evaluation_envelope.py` once the 2026-10 private ledgers are closed |
| PVA-D13 | Monthly cap for live evaluations | Resolved (delegated, 2026-11-09): USD 2 per evaluation campaign and USD 8 per month for evaluations, hard stop in code; production assistant budget stays USD 10 per month (DR-04); each live run still needs a current authorization (AGENTS.md) |
| PVA-D14 | Judge labels | Resolved (delegated, 2026-11-09): The planner bootstraps labels with two independent agents; the owner spot-checks a 20% sample once (DR-05); until validated the judge is informational and gates stay deterministic |
| PVA-D15 | LGPL and MPL exceptions | Resolved (delegated, 2026-11-09): Accept both with ADR-0015 |
| PVA-D17 | Default branch | Resolved (delegated, 2026-11-09): Keep `main`; add the PR template, AGENTS wording and skill rule; switch only if wrong-base PRs recur |
| PVA-D9 | Confirm that the ecosystem SLA supersedes the 2026-10-19 note that image CVEs are advisory and non-blocking | Resolved (delegated, 2026-11-09): Confirmed: the ecosystem SLA supersedes the 2026-10-19 note; it already lets base-image High wait for the next rebuild |
| PVA-D1 | English share of the golden set | Resolved (delegated, 2026-11-09): English is 5% (3 items), a politeness and language-switch block that verifies a polite Spanish reply (OD-32); revisit only if English traffic appears after activation |
| PVA-D11 | Run the ruleset script to require `ci-gate` | Resolved (delegated, 2026-11-09): Do it after the first green `ci-gate` run (M1.4) |
| Ecosystem E1, E2, E5, E11 | central standards repo, Dependabot sandbox, release-please location, eval spend and labelling | Resolved (delegated, 2026-11-09): follow `ecosystem.md` section 19 (DR-03 creates `engineering-standards`) |
| Also owner-only | Dependabot security updates off, private vulnerability reporting on, GitHub App for release-please, promotion to `main`, VPS purchase | Covered by owner inputs (2) and (3) above; the planner prepares each, the owner performs it when the roadmap reaches the item |

## 7. Index of files

| File | Content |
|---|---|
| [README.md](README.md) | this file |
| [scorecard.md](scorecard.md) | baseline per axis and lens, targets, measurement, ratchets |
| [rubrics.md](rubrics.md) | ecosystem rubrics v2 (byte-identical) |
| [audit.md](audit.md) | measured baseline, findings P0 to P2, inventory, what could not be measured; evidence under [audit/](audit/) |
| [target-state.md](target-state.md) | architecture, guards, typing, decomposition, contract changes, `.js` destinations, ADR list, migration order |
| [assistant-quality.md](assistant-quality.md) | golden set, graders, cassettes, full set, judge, red team, live lane, prompt versioning, budgets |
| [owner-decisions.md](owner-decisions.md), [owner-decisions-existing.md](owner-decisions-existing.md) | owner decisions register and pre-2026-11-09 decisions (byte-identical, binding) |
| [readme-template.md](readme-template.md) | README skeleton shared by all repos (byte-identical) |
| [assistant-widget.md](assistant-widget.md) | Assistant widget standard consumed by the storefront (byte-identical copy of `shared/`) |
| [assistant-experience.md](assistant-experience.md) | Assistant experience v2: performance, grounding, rich blocks contract, web access policy, opt-in memory, harness, evals, rollout |
| [testing.md](testing.md) | layers, numeric targets, every row of the test catalog, security matrix, properties, mutation, flake policy |
| [ci-cd.md](ci-cd.md) | profiles, graph, Dependabot rule and P0 path, supply chain, containers and Dockerfile, release, budgets; draft [ci-profile.json](ci-profile.json) |
| [file-index.csv](file-index.csv), [file-moves.md](file-moves.md) | every tracked file (412) with target and action; moves, deletions and additions |
| [standards.md](standards.md) | style choice, deviations, enforcement |
| [docs-and-community.md](docs-and-community.md) | README outline, Diátaxis, C4, community files, AGENTS.md edits |
| [skills.md](skills.md) | skill audit, new skills, activation evals, hooks, review chain |
| [dependencies.md](dependencies.md) | each current and proposed dependency |
| [roadmap.md](roadmap.md) | M0 to M7 and MV checklists with acceptance, effort, risks, cross-repo dependencies |
| [ecosystem.md](ecosystem.md) | ecosystem standard (byte-identical copy) |
| [progress.md](progress.md) | milestone log, starts at M0 |
| [RESUME.md](RESUME.md) | session-independent resume brief |
| [research/](research/) | the 8 research notes this plan cites (02, 03, 04, 05, 08, 09, 10, 11) |
| [sources.md](sources.md) | every external source with flags |
