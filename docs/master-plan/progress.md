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
- `docs/evaluation.md` case counts are stale (see `audit.md` P2-3).

### Pending owner decisions

none: all PVA decisions are resolved by delegation (README section 6). Owner inputs (3, the only ones): (1) the one-time 20% spot-check of judge labels (DR-05, about 1 h); (2) owner-only repository and release actions: applying the ruleset requiring `ci-gate`, private vulnerability reporting on, Dependabot security updates off, GitHub App or PAT for release-please, merging the weekly Dependabot PR, the release-please PR and the promotion to `main` (M7); (3) the standing per-run authorization before any live or paid run, including the VPS purchase and activation (MV; DR-04 caps apply).

## In-flight tasks

Updated on each task merge (one row per task from `roadmap.md` that is `in-progress` or finished since the last milestone; the roadmap Status column is authoritative). Find the true next task with the RESUME command in `roadmap.md` (last section).

| Task ID | Branch / PR | Status | Last update |
|---|---|---|---|
| (none started) | - | - | 2026-11-09 |

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
