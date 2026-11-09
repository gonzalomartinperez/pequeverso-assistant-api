# Documentation and community — pequeverso-assistant-api

Applies ecosystem section 14 and `research/08-docs-readme-skills.md`. Language policy: repository documents are English; the assistant's user-facing language is Spanish by owner decision (ADR-0006), and any public-copy proposals are neutral Latin American Spanish with "tú". Owner-facing Spanish operational notes, if wanted, live in `docs/es/` only.

## 1. README (rewrite, ecosystem 14.1)

Today: 13 badges, a screenshot gallery, version and model facts written into prose (README says Python 3.14.8, PostgreSQL 18.6, contract revision 1.5, `gpt-6-luna`, USD 10 budget), and statements about branches. Target: the ecosystem skeleton, at most three badges (CI, release, license), no volatile facts (counts, versions and model names link to the source file or are generated).

Proposed outline:

1. **Title and one line**: "Pequeverso assistant API — advisory, read-only shopping assistant backend, grounded in code."
2. Badges: CI (`ci.yml` on develop), release, MIT license.
3. **Why**: what the assistant does and refuses (advisory, read-only, prices only from the catalog, no transactions); the Spanish-only native assistant (ADR-0006) in two sentences.
4. **Where it runs** (public repo, but deployment is private): environments and status (not deployed; storefront widget disabled by flag), runbook links into `vps-ops` (private, referenced by name only), release and rollback pointers.
5. **Architecture**: C4 level 1 and level 2 as Mermaid (context: visitor, storefront, API, backoffice, vps-ops, OpenAI, PostgreSQL, Neo4j, Hotmart procedure pages; container: API, public and private PostgreSQL schemas, Neo4j projection); the existing light and dark SVGs move into `docs/explanation/architecture/` and are linked.
6. **Quickstart**: one command, credential-free fixture profile: `just dev` (wraps `uv sync --locked` and uvicorn with `AI_PROVIDER=fixture`); second block: `just check`.
7. **Usage**: the five public operations with a `curl` session and SSE example from `contracts/examples/`.
8. **Tech stack**: a table generated from `pyproject.toml` and `.python-version`.
9. **Quality**: the scorecard summary (`docs/master-plan/scorecard.md`), golden-set status, links to CI evidence; no hand-typed numbers.
10. **Documentation**: the Diátaxis map below.
11. **Roadmap**: link to `docs/master-plan/roadmap.md` and `progress.md`.
12. **Contributing / Security / Support**: links to the three files.
13. **License**: MIT for owner-authored software; `NOTICE.md` for reserved brand, commercial content, media and data.

The screenshots and the dated galleries move out of the README into `docs/verification/` (already there); the README keeps one hero image at most. A CI script checks the required headings.

## 2. Docs system (Diátaxis, no site generator)

| Quadrant | Contents (target paths) |
|---|---|
| Tutorials | `docs/tutorials/first-conversation.md` (run the fixture API, create a session, stream an answer) — new |
| How-to | `docs/how-to/run-evaluations.md` (new), `knowledge-operations.md`, `dependency-updates.md` (rewritten for the weekly PR), `release-and-hotfix.md` (from the skill), `rotate-and-restore.md` pointer to `vps-ops` |
| Reference | `docs/reference/api-contract.md`, `catalog.md`, `deployment-contract.md`, `product-analytics.md`, `ci.md`, `evaluation.md`, `agent-skills.md`, `runtime-baseline.md`, `prompt-changelog.md` (new), `dependency-health.md` (new), `handoffs/` |
| Explanation | `docs/explanation/architecture.md`, `security.md` (threat model), `graph-retrieval.md`, `official-web-evidence.md`, `reference-adoption.md`, `business-questions.md` |
| Decisions | `docs/decisions/ADR-0001..0019` (stable paths, MADR 4 with Confirmation) |
| Evidence | `docs/verification/` (dated, immutable) |

Moves are listed in `file-moves.md`; every inbound link is fixed in the same PR and checked by lychee (also weekly). `docs/engineering-standards.md` is folded into `CONTRIBUTING.md` and AGENTS.md and deleted; `docs/execution-plan.md` is archived.

## 3. C4 and diagrams

Mermaid C4 level 1 and 2 in the README and `docs/explanation/architecture.md`; existing `.mmd` sources and generated SVGs are kept, with a CI check that the SVGs are regenerated from the `.mmd` (manifest at `docs/architecture/manifest.json` already records provenance). Structurizr is not adopted (no shared model yet).

## 4. Community files (public repo; per-repo copies synced from `engineering-standards`)

| File | State | Content |
|---|---|---|
| `LICENSE`, `NOTICE.md` | present | keep |
| `CONTRIBUTING.md` | missing | short: `just check`, branch flow (task branch, PR to develop, `ci-gate`), Conventional Commits, review chain, golden-set rule for prompt changes; absorbs `docs/engineering-standards.md` review standard |
| `SECURITY.md` | missing | private vulnerability reporting, acknowledgement in 5 days, scope (API, container), what is out of scope (storefront, backoffice, `vps-ops`); the contact is a pequeverso.com mailbox only, never the retired `digitalproductsteam.com` domain (OD-53, task M1.8) |
| `SUPPORT.md` | missing | where to ask; no conversation data in public issues |
| `CODE_OF_CONDUCT.md` | missing | Contributor Covenant |
| `.github/ISSUE_TEMPLATE/{bug,feature}.yml`, `config.yml` (`blank_issues_enabled: false`) | missing | forms; a "wrong assistant answer" form that asks for a synthetic reproduction, never a real conversation |
| `.github/PULL_REQUEST_TEMPLATE.md` | missing | summary, linked issue, evidence (CI run, report), docs and changelog touched, agent docs touched, risk, golden-set impact |
| `.github/CODEOWNERS` | missing | a map: `evals/golden/**`, `app/ai/prompt*`, `catalog/**`, `contracts/**`, `.github/workflows/**` owned by the owner |
| Repository settings | verify | secret scanning and push protection on; private vulnerability reporting on; Dependabot security updates off, alerts on; default branch decision PVA-D17 |

## 5. AGENTS.md and CLAUDE.md

AGENTS.md is the source (Claude imports it). Edits: the **Workflow** section currently says "`main` is the default and release branch; `develop` is the development branch" and that both are protected with the required status `checks`; rewrite to the ecosystem wording: work lands on `develop` through task branches, `main` receives releases only, hotfix only with explicit owner OK, required check `ci-gate`, merge command `gh pr checks --watch && gh pr merge`; open PRs with `--base develop`. Commands equal `just check`. Link `docs/master-plan/RESUME.md`. Keep the non-negotiables (advisory, fixture by default, grounding in code, no invented facts, versioned contract, layers, content-free operations data). Shorten: the **Optional product analytics** paragraph moves to `docs/reference/product-analytics.md` with a one-line pointer.

## 6. Docstrings and comments

Google docstrings where `standards.md` S2 enforces them; comments explain why. Generated reference: none (no docs site).

## 7. Docs CI

lychee (links, weekly cron too), markdownlint-cli2, Vale on English prose only (optional), skills validator, README heading check; a "no volatile facts" check fails when `docs/` or the README contains a count or version that also exists in a generated report (starting with `docs/reference/evaluation.md`, whose case counts are stale today).
