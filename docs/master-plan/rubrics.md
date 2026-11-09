# Ecosystem rubrics v2 (fixed, 2026-11-09)

Applies to all seven repositories. Rubric versions are frozen once the first scored review is recorded; any change bumps the version and rescores the baseline. Scores never compensate across axes: the target is **≥ 95 on every axis** (floor **90** where an axis depends on an unauthorized input such as the VPS, paid model calls or human labelling, and the plan must say so).

Scoring rules (all lenses):

- A criterion without evidence is unmet. Evidence = CI run, report artifact, screenshot set, metric file or signed checklist, with commit SHA and date.
- 95–100: every criterion met with evidence. 85–94: every critical (C) criterion met. < 85: a critical criterion unmet.
- Caps: a failing required check caps the lens at 70; a committed secret caps Security at 40; a contract break without the major-version path caps Architecture at 60.
- Where a repo has light and dark themes, each theme is scored and the minimum counts.
- Evaluators are independent: they see the repo, the evidence and this rubric, never the planner's reasoning.

## Lens 1 — Senior developer (all repos)

| # | Axis | Critical criteria (C) and measurement |
|---|---|---|
| D1 | Architecture | C: dependency rule enforced by an automated guard with negative fixtures and an empty violation baseline; composition root; server/client boundary (web) or ports/adapters (Python). Measured by guard output. |
| D2 | Code quality | C: zero lint/type errors under strict config (TS strict + erasable syntax; mypy --strict); complexity ≤ 10 per function (ratcheted); no dead code (knip / vulture-equivalent). |
| D3 | Tests | C: unit + integration (real DBs in containers) + contract + E2E per repo type; branch coverage floor and diff coverage ≥ 90%; mutation score on core layers ≥ target (ratchet); 0 flaky tests in required checks over 30 days. |
| D4 | CI/CD | C: one aggregate required gate; dynamic (affected-only) execution with fail-closed aggregate; PR p50 within budget; build once, deploy same digest; weekly single Dependabot PR rule. |
| D5 | Security & supply chain | C: SHA-pinned actions, least-privilege tokens, zizmor, secret scanning, CodeQL (where available), SBOM + provenance for images, vulnerability policy with SLA, threat model for auth surfaces. |
| D6 | Performance | C: budgets enforced in CI (bundle, Lighthouse, latency p95 or CLI time as applicable). |
| D7 | Observability | C: structured logs without PII, request id propagation, health/readiness, SLOs defined (VPS-dependent parts may use floor 90). |
| D8 | Docs & DX | C: README follows the ecosystem template; ADRs (MADR) current; one-command setup; CHANGELOG; community files; agent docs and skills validated by activation evals. |

## Lens 2 — Senior product designer (web repos; for APIs: API & conversational UX; for vps-ops: operator UX)

| # | Axis | Critical criteria and measurement |
|---|---|---|
| P1 | Visual design & system | C: all colors/spacing/type from tokens (DTCG source), fluid type scale, no literals outside tokens (lint). |
| P2 | Interaction & motion | C: motion 150–300 ms, transform/opacity only, reduced-motion honoured (test), loading/empty/error states for every async view. |
| P3 | Accessibility | C: WCAG 2.2 AA; axe 0 serious/critical in every theme/locale; keyboard path to every primary action; target size ≥ 24 px; Lighthouse a11y = 100. |
| P4 | Responsive & cross-browser | C: 320–1920 px without overflow; Chromium, Firefox, WebKit (iPhone profile) green; visual regression baseline approved. |
| P5 | Theme parity | C: where a second theme exists, it scores within 2 points of the first; if a repo is single-theme by ADR, the ADR must cite evidence. |
| P6 | Consistency & identity | C: shared primitives, coherent identity kept (polish, not rewrite). |

APIs: P1→error/response contract clarity (RFC 9457-style, bilingual where applicable), P2→streaming UX (progress events, time to first token), P3→assistant message quality (golden set 100%, language, abstention), P4→contract docs/examples, P5/P6→consistency with consumers.
vps-ops: operator UX = CLI ergonomics, runbook clarity, dry-run safety, error messages.

## Lens 3 — Senior e-commerce/CRO (pequeverso) · Senior recruiter (portfolio trio) · Senior SRE (vps-ops)

CRO: value proposition above the fold (5-second test), trust signals (real only), purchase path to Hotmart (clicks, clarity, price/guarantee visibility), perceived speed (field CWV p75), assistant messaging (grounded, discloses AI, no invented facts), SEO (structured data, metadata, sitemap), privacy-respecting analytics with consent.
Recruiter: first screen clarity, proof (measured results), writing quality, credibility, calls to action, polish, differentiation.
SRE: deploy safety (digest, rollback rehearsed), backups + restore drill, hardening baseline, secrets handling, monitoring/alerting, incident runbooks, DR targets (RPO/RTO).

## Automatic measurement

Each repo ships `scorecard` tooling (TS in web repos, Python in Python repos) that aggregates CI artifacts into `scorecard.json` (per-axis inputs + pass/fail per criterion), runs nightly and on release, and fails on regression against the committed ratchet baseline. Designer, CRO, recruiter and SRE judgement axes are recorded per release by an independent evaluator agent against this rubric, with evidence links.
