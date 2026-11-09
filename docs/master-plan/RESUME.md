# RESUME — pequeverso-assistant-api master plan

Self-contained brief for any Claude account, machine or agent with no access to earlier chats. Nothing is resumed from memory.

## 1. What this is

`pequeverso-assistant-api` is the public backend of the Pequeverso shopping assistant: FastAPI, LangGraph, PostgreSQL with pgvector, a Neo4j projection, OpenAI behind a provider port. It is advisory and read-only: no orders, payments or account changes; prices and claims come only from a catalog snapshot, enforced in code. The native assistant speaks Spanish only (neutral Latin American Spanish, "tú"; ADR-0006). It is not deployed and the storefront widget is disabled until the owner buys a VPS and authorizes activation.

The master refactor brings it to the ecosystem standard (`ecosystem.md`) and the rubrics (`rubrics.md`), with an assistant-quality gate: a 60-item golden set at 100% and a full set of about 320 cases (`assistant-quality.md`). Planning date 2026-11-09, baseline develop `6912579245506bbd60f745243905ce4974dfbfe9`. The plan authorizes no code, deploy, spend or production change by itself; the owner decides each phase.

## 2. Read order

1. This file, then `progress.md` (current milestone and next item).
2. `README.md` (decisions PVA-D1 to PVA-D19, all resolved by delegation), then `owner-decisions.md` and `owner-decisions-existing.md` (binding registers; read before acting on anything they cover).
3. `roadmap.md` (the first `todo` row; use the RESUME command in its last section to find the true next task mid-milestone).
4. `scorecard.md`, `audit.md` (numbers and findings).
5. The file for the work at hand: `assistant-quality.md`, `testing.md`, `ci-cd.md`, `target-state.md`, `standards.md`, `docs-and-community.md`, `skills.md`, `dependencies.md`.
6. `file-index.csv` and `file-moves.md` before moving or deleting anything.
7. The repository's own `AGENTS.md` (its rules win), then the ecosystem tracker (`engineering-standards/progress/ecosystem.md`; until that repo exists the interim tracker is the table in `progress.md` of `vps-ops`).

## 3. First commands

```bash
cd ~/projects/github/gonzalomartinperez/pequeverso-assistant-api
git fetch -q && git checkout develop && git pull --ff-only
git log -1 --format='%H %s'                      # compare with progress.md
git tag --list 'checkpoint/*'                    # start at or after the latest checkpoint
gh auth status                                   # account must be gonzalomartinperez only
uv sync --locked
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q -p no:cacheprovider
uv run python -m contracts.export --check
git switch -c chore/<short-task-name>            # one task branch per item
```

Before M1.5 lands the full suite takes about 4 minutes serial; database and container tests need the CI services or an isolated service lease (never another session's containers).

## 4. Ready-to-paste prompt

```text
You are resuming the pequeverso-assistant-api master refactor. You have no chat history.
Work in ~/projects/github/gonzalomartinperez/pequeverso-assistant-api.
1. Read docs/master-plan/RESUME.md, progress.md, roadmap.md and the repo AGENTS.md. AGENTS.md wins on conflicts.
2. Check out develop at or after the latest checkpoint/M<n> tag. Do not trust anything not in git.
3. Find the true next task: `git log --oneline --grep 'PVA-M'`, `gh pr list --state all --search 'PVA-M in:title'`, then the first `todo` row in roadmap.md (set it `in-progress`; put its ID in branch, PR title and merge commit). Create a task branch (feat/, fix/, chore/, docs/ or deps/), implement it with tests at the right layer, update docs, ADRs, the changelog entry and AGENTS.md or skills when behaviour changes.
4. Run the checks in AGENTS.md. Run an independent reviewer agent on the diff (and a second-model review when available). Reproduce every finding before acting.
5. Open a PR to develop (never push to develop or main). Merge only with green CI: gh pr checks --watch && gh pr merge. Never use --admin.
6. Never run live or paid evaluations, read private key files, or spend money without the owner's explicit current authorization in this conversation. The fixture and cassette lanes need none.
7. At the end of a milestone update progress.md and the ecosystem table, and ask the owner to approve pushing the checkpoint/M<n> tag.
Report in Spanish at the end when the owner works in Spanish; repository documents stay in English.
```

## 5. Owner inputs and delegated resolutions

All PVA decisions are resolved by delegation (`README.md` section 6; owner-decisions register, Delegated resolutions); PVA-D12, D13, D14, D15 and D17 are therefore binding as recorded there, not open. Owner inputs (3, the only ones): (1) the one-time 20% spot-check of judge labels (DR-05, about 1 h); (2) owner-only repository and release actions: applying the ruleset requiring `ci-gate`, private vulnerability reporting on, Dependabot security updates off, GitHub App or PAT for release-please, merging the weekly Dependabot PR, the release-please PR and the promotion to `main` (M7); (3) the standing per-run authorization before any live or paid run, including the VPS purchase and activation (MV; DR-04 caps apply).

Still never the planner's to do, whatever the input above: legal and commercial facts (prices, guarantees, refund terms, testimonials, privacy text, support hours; list them as questions in `docs/explanation/business-questions.md`); hotfix authorization (explicit, in the current conversation, for that specific fix); granting scopes (tokens, GitHub App, Coolify); accepting a vulnerability exception; changes to the ecosystem decisions log. These fall under owner inputs (2) and (3) or need a fresh explicit owner message.

## 6. Non-negotiable rules

- Flow: task branch, PR into `develop`, green `ci-gate` (today named `checks`), strict and up to date, merge commit (no squash) with a Conventional Commit PR title. `main` only at M7 (promotion with a merge commit); no hotfixes before M7 (OD-11, DR-01).
- Merge only with green CI: `gh pr checks --watch && gh pr merge`; never chain with `;`; never `--admin`; never change protection to get a merge through.
- No secrets in git, images, logs, build args or issues; `.env*` stay ignored; the repository is public; synthetic data only; never a real conversation.
- Dependabot weekly rule: exactly one dependency PR per week (Monday 09:00 America/Argentina/Buenos_Aires, target `develop`, all ecosystems together); an unmerged PR is updated or superseded, never duplicated; security-update PRs stay off; critical advisories ride the weekly PR or the manual single-dependency PR.
- Audience and domain: the assistant is Spanish-only (OD-32; English only verifies a polite Spanish reply); no reference to `digitalproductsteam.com`, only pequeverso.com (OD-53).
- Never `pkill -f` (it kills the shell and other sessions' watchers); stop processes by a verified PID.
- GitHub identity is `gonzalomartinperez` only, in commits and `gh`; never the secondary account.
- Repository rules that survive the refactor: advisory and read-only; fixture mode by default; grounding enforced in code, never only in the prompt; no invented prices, policies, discounts, scarcity or testimonials; the v1 contract changes only backward compatibly (regenerate `contracts/`); operations data stays content-free; other repositories are read-only from here.
- No deploys, DNS or production changes from this repository (`vps-ops` owns them).
- Guard hooks block destructive commands; do not work around a block, ask the owner.

## 7. Current state pointers

Milestone and next item: `progress.md`. The first task is PVA-M1.2 (certifi, manual PR merged by 2026-11-13, SLA ends 2026-11-16). In-flight tasks: `progress.md`. Open decisions and their recommendations: `README.md`. Scorecard baseline and targets: `scorecard.md`. Ratchets will live in `ratchets/` once M2 lands.
