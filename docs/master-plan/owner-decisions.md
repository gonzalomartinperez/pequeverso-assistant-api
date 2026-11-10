# Owner decisions register

Canonical, byte-identical in every repository at `docs/master-plan/owner-decisions.md`. Agents (Claude Code and Codex) must read it before acting on anything it covers, and must never contradict it. Only the owner changes an entry; a change is recorded as a new dated entry that supersedes the old one (the old one stays, marked superseded). Linked from every repo's `AGENTS.md`.

Owner: Gonzalo Martín Pérez (GitHub `gonzalomartinperez`). All entries dated 2026-11-09 unless stated.

## Companion register

Decisions taken before 2026-11-09 in each repository (ADRs, decision logs, AGENTS rules, owner memory) are consolidated with sources, status and conflicts in `owner-decisions-existing.md` (same folder, byte-identical in every repo). Where it lists a conflict, the conflict's recommendation is pending owner confirmation; until then follow the newer OD entry, and for legal items follow the existing in-force decision and raise the question.

## How to use this file

- If a task touches a topic below, follow the entry exactly; if the entry seems wrong for the situation, stop and raise it as an owner question instead of deviating.
- Planner recommendations that the owner overruled are noted so agents do not "fix" them back.

## Delegated resolutions (owner, 2026-11-09: "resolve them yourself")

The owner delegated every open decision of the nine plans, the ecosystem standard (E1–E14), the legal questions (Q-L1–Q-L14) and the conflicts (C-01–C-14) to the planner. Rule: **each open decision is resolved as its plan's recommendation**, recorded in that plan's README as "Resolved (delegated)". The ones below are stated explicitly because they change operations, money, legal posture or production:

| ID | Resolution |
|---|---|
| DR-01 | Consent (PV-D1, C-01): opt-in banner with no pre-selected marketing; Meta Pixel and any marketing tag load only after consent; CAPI relay respects the same record. Owner decision (2026-11-09): NO hotfixes now — it ships with the refactor at M7 like everything else (scheduled early in M3 on `develop`). The owner accepts the interim legal risk. |
| DR-02 | Social disclosure (MKT-D1, C-02): restore minimal, clear disclosure — affiliate notice on every piece promoting the affiliate guide, AI notice when an image or voice is generated, and a fixed note in bios. Supersedes DEC-2026-10-25 for those cases. |
| DR-03 | Central standards repository (E1): create public `gonzalomartinperez/engineering-standards` (no secrets) for shared workflows, templates, skills, agent definitions, hooks, tokens and the ecosystem tracker. |
| DR-04 | Live-eval spend caps: USD 2 per evaluation campaign and USD 8 per month per assistant; production assistant budget stays at the existing USD 10 per month per project; hard stop in code. |
| DR-05 | Judge calibration labels: the planner bootstraps labels with two independent agents and the owner spot-checks a 20% sample once; until validated, release gates rely on deterministic graders only. |
| DR-06 | Withdrawal by email (PV-D2): the owner commits to answer withdrawal requests within the legal windows (EU 14 days, AR/CL 10 days) and refund manually; support pages, reply template and content tests ship in M3. |
| DR-07 | Legal pack (PV-D8, Q-L1–Q-L14): implement the recommended texts (withdrawal button, privacy and cookies for AR/MX/CL/ES-EU, accessibility statement) and flag in `progress.md` that a lawyer review is recommended before M7; agents never present legal text as legal advice. Seller identification in the footer stays removed as the accountant advised (EX-PV-06, in force); it is shown only where the law or Hotmart requires it. |
| DR-08 | Production target for pequeverso: standalone only; retire static export at M4; ADR-0001 superseded. |
| DR-09 | Test runner for the four TypeScript repos: one spike decides for all four (Vitest 4 preferred if StrykerJS works with TS 7; otherwise node:test + Stryker tap-runner); same choice everywhere. |
| DR-10 | Node 26 LTS for backoffices after two weeks of dual CI; Python 3.14 latest patch; Postgres 18 trixie; Neo4j 5.26 LTS (Neo4j vs Postgres graph decided by spike in each API at M4). |
| DR-11 | Analytics for pequeverso: cookieless counter (Umami) with consent-aware events; Hotmart native pixel for purchases; webhook→CAPI only at MV. |
| DR-12 | Images and scanning: Grype default; Docker Hardened Images only as a 30-day pilot. |
| DR-13 | Image publication to GHCR and deploy apply stay disabled until MV; when the VPS exists, owner authorizes activation in one step. |
| DR-14 | Domain and mail: the live site and Hotmart already use only pequeverso.com (verified 2026-11-09: no old-domain reference in site source); remaining references are repo docs and SECURITY.md on `develop` (GitHub's default branch for pequeverso), fixed early in M1; no hotfix needed. |

## Scope and goals

| ID | Decision |
|---|---|
| OD-01 | The refactor covers nine repositories: portfolio, portfolio-assistant-api, portfolio-backoffice, pequeverso, pequeverso-assistant-api, pequeverso-backoffice, vps-ops, pequeverso-marketing, dropshipping-ops. Each has its own master plan under the same ecosystem standard. |
| OD-02 | Target: ≥ 95 on every rubric axis in every repo ("perpetual excellence": ratchets, automated scorecard, re-score cadence). Floor 90 only where VPS, paid model calls or human labels block an axis, stated in the plan. |
| OD-03 | One standard way of working across all repos; shared rules defined once (ecosystem standard, shared workflows, templates); each repo documents only justified deviations. |
| OD-04 | Pragmatism: rigor where it reduces real risk; no ceremony. |
| OD-05 | The agent harness must be good enough that the owner does not review code. Owner-only touchpoints: decisions, weekly dependency PR merge, milestone summaries, production activation, spend, legal and commercial facts, promotion to main. |
| OD-06 | Tools: only Claude Code and OpenAI Codex. Claude orchestrates, plans, designs, reviews and decides; Codex executes scoped work and gives the second-model review; each reviews the other's diffs. |
| OD-07 | Planner has full creative and technical freedom; if something needed was not requested, adopt it. |
| OD-09 | After the refactor, all public copy is refreshed to match the final state: portfolio (EN/ES, case studies, project descriptions, CV-linked facts from career-ops) and Pequeverso (store, legal and support pages), plus READMEs and repo descriptions; verified facts only. Scheduled in M6, before release. |
| OD-08 | Maximize GitHub profile value: public repos are showcases. Final milestone M8 (after all repos reach M7): an outstanding redesign of the GitHub profile README and presentation (pinned repos, descriptions, topics, social previews), consistent with the portfolio identity and using only verified facts from career-ops. |

## Branching, releases, visibility

| ID | Decision |
|---|---|
| OD-10 | Release repos (portfolio, portfolio-assistant-api, portfolio-backoffice, pequeverso, pequeverso-assistant-api, pequeverso-backoffice): task branch → PR → `develop` with green `ci-gate`; `main` only by release. |
| OD-11 | During the refactor everything integrates into `develop`; `main` is promoted once per repo when the whole refactor is done (M7). Production sites on Hostinger stay unchanged until then. Any earlier change to `main` needs explicit owner authorization (hotfix). |
| OD-12 | Main-only repos: `vps-ops`, `pequeverso-marketing` and `dropshipping-ops` (documentation, orchestration, content, research and operations repos). Task branch → PR directly to `main` with green checks; versions as tags on `main` (marketing may tag closed weeks `semana/AAAA-Www`). No `develop`. |
| OD-13 | Visibility: the six product repos are public; `vps-ops`, `pequeverso-marketing` and `dropshipping-ops` are private (sensitive operations; creative direction; a new business line the owner is exploring for the future, unrelated to Pequeverso). Superseded: an interim decision to make vps-ops public. Planner recommended private. |
| OD-14 | No GitHub Pro. Private repos enforce the flow with five layers: Claude/Codex hooks blocking direct pushes to protected branches; versioned git pre-push hook installed by setup; merge only with green CI (`gh pr checks --watch && gh pr merge`); scheduled commit-provenance audit opening an issue on violations; full CI. |
| OD-15 | Never use `--admin` merges; never force-push protected branches; GitHub identity is `gonzalomartinperez` only. |

## Dependencies and security

| ID | Decision |
|---|---|
| OD-20 | Exactly one dependency PR per repo per week containing all ecosystems; Monday 09:00 America/Argentina/Buenos_Aires; targets `develop` (main-only repos: `main`); must be green; owner merges manually; never N PRs for N dependencies. |
| OD-21 | If last week's PR is unmerged, it is updated or superseded, never duplicated; at most one dependency PR open per repo. |
| OD-22 | Dependabot security-update PRs disabled; alerts on; a daily job records findings silently and the Monday summary notifies (OD-75); critical fixes ride the weekly PR (owner accepts the up-to-a-week wait). |

## Assistants (portfolio-assistant-api, pequeverso-assistant-api)

| ID | Decision |
|---|---|
| OD-30 | Two eval tiers. Golden set with a 100% release gate (cassette replay on PRs touching assistant quality; live run before release). Full set run on demand (model, prompt or retrieval change; major release), reported by family and locale, no 100% gate; real failures are promoted into the golden set. |
| OD-31 | Sizes: Pequeverso golden ≈ 60, full ≈ 320; portfolio golden ≈ 80 (bilingual), full ≈ 450 with ≈ 100 sealed holdout. Full-set targets: recall@5 ≥ 0.90 per family, EN–ES gap ≤ 3 pp (portfolio), critical invariants 100%, judged quality ≥ 95% with a validated judge. |
| OD-32 | Pequeverso sells only to a Spanish-speaking audience (Latin America and possibly Spain). Its assistant and store are Spanish-only (neutral es-419, tú); English cases only verify a polite Spanish reply. |

## Design

| ID | Decision |
|---|---|
| OD-40 | Designer-grade, unique UI/UX in all four web products, keeping each identity (polish and elevate) within strict performance and accessibility budgets; Pequeverso prioritizes conversion. |
| OD-41 | All four web apps use Tailwind 4 with a complete semantic token system and owned CVA primitives; TypeScript everywhere (TS 7). |
| OD-42 | Backoffices share one view, IA, layout, component and state standard, each with its own identity fit to its purpose. |
| OD-43 | Portfolio family palette starts from blues (owner preference, tech association): deep navy to electric blue with cyan accent; Pequeverso keeps its warm, kid-friendly identity anchored on its navy. Blues are a starting preference, not a constraint. |
| OD-44 | Portfolio hero: a particle system morphing between exactly 10 unique figures, including sphere, cube, wormhole, toroidal helix (coiled spring with joined ends) and triangle/tetrahedron, plus five chosen for quality and identity; inspired by Stephan Livera's Claude motion reel; must respect performance budgets and reduced motion. |

## Commerce and legal (Pequeverso)

| ID | Decision |
|---|---|
| OD-50 | Hotmart allows one global guarantee, set to 7 days. Longer legal withdrawal windows (Spain/EU 14 days; Argentina and Chile 10 days) are honored manually by email with a manual refund. The site documents this process and never promises anything inconsistent with config. |
| OD-51 | Never invent testimonials, numbers or claims; commercial facts come only from config. Public copy in neutral Latin American Spanish with tú, signed "Equipo de Pequeverso". |
| OD-53 | The old domain digitalproductsteam.com will not be renewed (auto-renewal cancelled by the owner for everything on it: domain, mail and hosting; domain expires 2026-11-25, mail plan 2026-12-22). No redirects. Every reference (Hotmart support email, legal pages, site, docs, social bios) must use only the current pequeverso.com domain and mailbox before 2026-11-25; a content test fails on any remaining reference to the old domain. Owner confirmed (2026-11-09) that Hotmart (sales page, upsell, downsell and thank-you URLs) already points to pequeverso.com; remaining references are docs, SECURITY.md contact and marketing history. |
| OD-52 | Facebook copy may keep links in captions (owner decision, data-backed). The bio uses a single link to pequeverso.com without parameters. |

## Infrastructure

| ID | Decision |
|---|---|
| OD-60 | VPS: Ubuntu 26.04 LTS with Coolify, hardened (dashboard only via SSH tunnel or Tailscale, 2FA, single account, pinned version, critical-advisory upgrade window, independent backups, monthly restore drill). Planner noted Coolify's advisory history; Compose + Caddy is the recorded exit. |
| OD-61 | vps-ops is the control plane to deploy and orchestrate every current and future project, scalable to more projects and hosts (declarative registry, project templates, digest-based deploy pipeline with approvals and rollback). Apply stays disabled until the VPS exists and the owner authorizes it. |
| OD-64 | VPS readiness: everything is prepared and rehearsed before the VPS is bought (release-candidate images with provenance, vps-ops registry and Coolify config as code, monitoring and backups, full-stack rehearsal on a disposable Ubuntu 26.04 VM, day-one runbook) so that the day the VPS exists everything is live within about two hours; owner steps limited to purchase, DNS and entering secrets. |
| OD-65 | Idea (not a commitment): dropshipping-ops may later deploy services to the VPS when the business is real. Keep its code VPS-ready by default (containerizable packages, health endpoints, env-ref secrets, registry entry template in vps-ops) without building anything VPS-specific now; vps-ops onboarding by template (OD-61) covers it. |
| OD-62 | Containers consistent across repos on LTS versions with one canonical configuration per stack. |
| OD-63 | Keep at least 100 GB free on Windows drive C:; check before disk-heavy work. |

## Work process

| ID | Decision |
|---|---|
| OD-70 | Plans first: no implementation starts until all nine master plans are merged (M0). |
| OD-71 | Milestones M0–M7 (+ MV) are safe points with `checkpoint/M<n>` tags, `progress.md` and `RESUME.md`; the work must be resumable from any Claude account without chat history. |
| OD-72 | CI is dynamic per PR type (profiles) with one fail-closed `ci-gate`, standardized and optimized across repos. |
| OD-73 | Every test type that guards a real risk is adopted (catalog in the ecosystem standard §11.0), including unit, integration, contract, E2E, visual, accessibility, performance, mutation, property-based, load, security and data tests. |
| OD-74 | Never `pkill -f`; kill processes only by verified PID. |
| OD-75 | Email noise budget (owner, 2026-11-10): at most one dependency/vulnerability email per week per repo, everything grouped. Dependabot opens one grouped PR per week (OD-22). Dependabot alert emails use GitHub's weekly digest (owner account setting), never per-alert email. The daily vulnerability job and `deps-weekly-guard` never mention the owner and never open a new issue per finding: they update one pinned tracking issue per repo silently; only the Monday run posts the weekly summary that notifies. Actions emails: failed workflows only. Supersedes any older text in this folder saying a daily job or alerts notify per finding. |
