# Existing owner decisions (register of decisions already taken)

Generated 2026-11-09 from read-only reads of the eight repositories (origin integration branches), the owner's persistent memory notes, the legacy ai-business-ops decision log and the new register `owner-decisions.md` (OD-xx). Purpose: agents must not re-ask any row marked "in force". Nothing here is invented: every row cites its source. No secrets or customer personal data are included (seller identity values are deliberately not reproduced; they live in `pequeverso:content/es/legal/seller.ts`).

Status vocabulary: **in force**; **superseded by OD-xx**; **conflicts with OD-xx / another repo** (see "Conflicts"); **stale doc** (the decision stands, the doc text is outdated).

Source shorthand: `PV` = pequeverso (origin/develop), `PF` = portfolio (origin/main), `PFAPI` = portfolio-assistant-api, `PFBO` = portfolio-backoffice, `PVAPI` = pequeverso-assistant-api (develop), `PVBO` = pequeverso-assistant-backoffice (develop), `VPS` = vps-ops, `MK` = pequeverso-marketing, `MEM` = the owner's persistent agent memory notes (local, not in git), `LEG` = ai-business-ops `.../decisions/decision-log.md` (read-only legacy).

## 1. pequeverso (site)

| ID | Decision (as currently in force) | Date | Source | Status |
|---|---|---|---|---|
| EX-PV-01 | Hotmart owns payment, delivery and refunds; the site never emits `InitiateCheckout` or `Purchase`; upsell/downsell only through the Hotmart funnel widget; a thank-you URL is not proof of payment. | 2026-09 (AGENTS) | PV:AGENTS.md "Non-negotiables" | in force |
| EX-PV-02 | Business facts (prices, composition, guarantee days, checkout URL, social profiles) are configuration, never copy. Never invent testimonials, results, guarantees or claims. | 2026-09 | PV:AGENTS.md; config/commerce.ts | in force (restated by OD-51) |
| EX-PV-03 | Single price in USD (US$14,99 Grafismo Fonetico); Hotmart converts to local currency and the buyer sees the final total with taxes before paying; `localCurrencyNote` shown beside every price. Main PDF plus bonuses are all included in the single price. | 2026-09-24 | PV:docs/content-model.md:61; config/commerce.ts:9,42 | in force; gap on ARS display (Q-L6) |
| EX-PV-04 | Guarantee = Hotmart 7 days (`guaranteeDays = 7`); legal withdrawal windows honored manually (see OD-50). | 2026-09 / OD 2026-11-09 | PV:config/commerce.ts:12; OD-50 | superseded by OD-50 (site must document manual process; check pages) |
| EX-PV-05 | Seller is an Argentine natural person (persona humana); legal pages published with the owner's consent; seller-side law is Argentine (Ley 24.240, CCyC, Ley 25.326); Spanish legal anchoring (LSSI/AEPD/RDL 1/2007) removed; EU/Spain appear only as buyer markets. | 2026-09-24 | PV:docs/legal-checklist.md "What changed on 2026-09-24"; content/es/legal/seller.ts | in force |
| EX-PV-06 | Full seller identification left the footer on the accountant's advice; it stays on `/aviso-legal/`, `/terminos/`, `/privacidad/` one click away on every page. | 2026-09-26 | PV:docs/legal-checklist.md:40 | in force, caveat (Res. SCI 270/2020 art. 2 reads "easy visibility"; Q-L2) |
| EX-PV-07 | Jurisdiction: Argentine law applies without prejudice to the consumer's mandatory local law; the consumer chooses the forum, Bahia Blanca is one option and the agreed forum only for non-consumers. Data controller is the Titular. | 2026-09-24 | PV:docs/legal-checklist.md; content/es/legal/argentina.ts | in force (needs lawyer review, Q-L8) |
| EX-PV-08 | Legal pages set: `/aviso-legal/`, `/privacidad/`, `/cookies/`, `/terminos/`, `/compras-y-reembolsos/`, `/arrepentimiento/` (noindex, "Boton de arrepentimiento" footer link), `/soporte/`. Placeholders `[[LIKE_THIS]]` allowed until the owner supplies data; deploy refuses to ship them. | 2026-09-24 | PV:docs/legal-checklist.md; AGENTS.md | in force |
| EX-PV-09 | One support/privacy/arrepentimiento mailbox; the owner's Hotmart mailbox `legalEmail` appears only on the six legal routes (enforced by `tests/unit/legal-email.test.ts`). Support response "48 horas habiles", arrepentimiento code within 24 h. | 2026-09-24 | PV:docs/legal-checklist.md "Still true" | in force |
| EX-PV-10 | Consent model: opt-out. The Meta Pixel measures from the first page view; the banner (Aceptar / Rechazar / Configurar, geo-blind, equal weight) is the withdrawal control; rejecting never limits the site or purchase. `DEFAULT_CHOICE` in `consent.ts` is the one-line switch to opt-in. | 2026-09-14 | PV:docs/tracking.md:94-116,153-158; ADR-0003; legal-checklist.md:60,264 | in force; conflicts with OD-32 (Spain) and its own legal note (C-01) |
| EX-PV-11 | Meta Conversions API relay runs inside our own Node server (zero dependencies, strict event allowlist), sent only while marketing measurement is allowed; at most one new variable. | 2026-09-20 | PV:ADR-0005 | in force; requires standalone build (C-03) |
| EX-PV-12 | Tracking adapters behind consent (`analytics`, `marketing`, consent v2); tracking events, source/placement attribution (src/sck) are a future improvement, not now. | 2026-09-13 / 2026-10-13 | PV:ADR-0003; docs/specs/home-hub.md:104; MEM pequeverso-tracking-later | in force |
| EX-PV-13 | Affiliate products (Hotmart) are recommended through short redirects `/<slug>/` to an affiliate link held in an env variable; the site shows a visible affiliate disclosure beside the course button, in hub footers/404, and `/aviso-legal/#afiliados`; no price, reviews, ratings or health promises on the site chapter. | 2026-10-12/13 | PV:docs/affiliates.md:54-75; content/es/home.ts | in force on the site; conflicts with MK on social copy (C-02) |
| EX-PV-14 | Native shopping assistant ships disabled (`NEXT_PUBLIC_ASSISTANT_ENABLED` unset/false in every publishable build); enabling needs the owner's explicit authorization, a rebuild, and the assistant privacy section in `/privacidad/` first. Assistant is advisory only (no checkout, cart or tracking). Post-purchase offers never appear in it. | 2026-10-05 | PV:ADR-0008; AGENTS.md; docs/assistant.md:15 | in force |
| EX-PV-15 | Hostinger is connected to `main` as a Node.js Web App (standalone build, `/hbuilds/` builder); every merge to `main` builds and publishes; verify `build-info.json` SHA. Variables only in hPanel/env, none inline. | 2026-10-13 | PV:docs/deployment.md:5; AGENTS.md "Workflow"; MEM pequeverso-hostinger-autodeploy | in force (AGENTS "static export (default)" is stale, C-03) |
| EX-PV-16 | Branch flow: task -> squash PR into `develop`; release `develop` -> `main` with a merge commit; hotfix only with the owner's explicit per-fix OK, then back-merge. | 2026-09-27 | PV:AGENTS.md; MEM main-branch-hotfix-authorization | in force; AGENTS still names a "Branch policy" check (C-05) |
| EX-PV-17 | Design system: Tailwind v4 + shadcn (Base UI), light theme only (no `.dark`, no dark variant); TypeScript 7 everywhere with strictest flags. | 2026-09-24 | PV:ADR-0006 (item 3), ADR-0007 | in force (dark mode refused; OD-41 does not require it) |
| EX-PV-18 | Retired operator brand: the site is Pequeverso only (no "Digital Products Team"); public product name Grafismo Fonetico. | 2026-09-20 | PV:tests/unit/content-invariants.test.ts:19; MK DEC-2026-09-12-nombre-publico | in force |
| EX-PV-19 | Demo videos are labelled "Video ilustrativo" and legal pages state they may be AI-generated (rights confirmed by the owner). | 2026-09-24 | PV:docs/media.md:203; legal-checklist.md | in force on the site (differs from social, C-06) |
| EX-PV-20 | Accessibility (WCAG 2.2 AA, reduced motion, CLS <= 0.1, LCP <= 2.5 s) and media provenance (manifest, 5 MB/25 MB budgets) are acceptance criteria. | 2026-09 | PV:AGENTS.md | in force |
| EX-PV-21 | Cutover to pequeverso.com is the owner's job (runbook ~1 h, low-traffic window); legal follow-ups (AAIP registration, etc.) are not blocking cutover. | 2026-09-24 | PV:docs/migration.md:53,70 | in force |

## 2. pequeverso-assistant-api

| ID | Decision | Date | Source | Status |
|---|---|---|---|---|
| EX-PVAPI-01 | Fixture mode by default; never use a real API key or run `--live`/paid calls without explicit current owner authorization. Pequeverso uses its own OpenAI project, key and budget, never the portfolio's. | 2026-09 | PVAPI:AGENTS.md:16-18 | in force |
| EX-PVAPI-02 | Spend caps default to US$10/month and US$1/day, with worst-case reservation under a PostgreSQL advisory lock before every call; knowledge jobs hard-capped at the same values. | 2026-09/10 | PVAPI:app/bootstrap/config.py:51-53; knowledge_jobs.py:50-51; docs/security.md:11 | in force |
| EX-PVAPI-03 | Model `gpt-6-luna` with medium reasoning effort. | 2026-10 | PVAPI:ADR-0004; deployment-contract.md:159 | in force |
| EX-PVAPI-04 | Assistant is Spanish-only (native storefront, no selector); v1 clients stay compatible. English cases only verify a polite Spanish reply. | 2026-10-12 | PVAPI:ADR-0006; ADR-0004 (superseded part) | in force (restated by OD-32); ADR-0004 EN+ES is superseded |
| EX-PVAPI-05 | Conversation data retained 24 h after last activity, then deleted (purge every 10 min); operations data is content-free (no messages, session ids, client keys, emails); IPs HMAC-hashed. | 2026-09-27 | PVAPI:docs/security.md:51-54; docs/execution-plan.md:6 | in force |
| EX-PVAPI-06 | The post-purchase offer and paid extras never appear before purchase or in the assistant; children's identifying data is never requested; guarantee and price facts come from the catalog, not the prompt. | 2026-09-24 | PVAPI:docs/catalog.md:17; AGENTS.md:21-24 | in force |
| EX-PVAPI-07 | Production deployment, DNS and storefront activation are deferred to vps-ops and a separate explicit owner activation; activation needs a reviewed API artifact and an owner-approved rebuild. | 2026-10 | PVAPI:docs/execution-plan.md:15; docs/handoffs/vps-ops.md:188; ADR-0008/0009 | in force |
| EX-PVAPI-08 | Real-model evaluation was owner-authorized once on 2026-10-12 (236 + 53 queries); any further paid run needs fresh authorization. Platform-evidence search is bounded and not production-authorized. | 2026-10-12/13 | PVAPI:docs/execution-plan.md:14; ADR-0008 | in force |
| EX-PVAPI-09 | Optional private observability (OpenTelemetry/Prometheus/Grafana) is allowed on owner request; ledger stays content-free; runtime tracing disabled. | 2026-10-12 | PVAPI:ADR-0005 ext., ADR-0007 | in force |
| EX-PVAPI-10 | Versioned commercial GraphRAG adopts the portfolio architecture (supersedes the no-embedding choice only when it ships). Repository is public (owner request 2026-09-27). | 2026-10-17 | PVAPI:ADR-0009; ADR-0002; docs/execution-plan.md:7 | in force / implementation in progress |
| EX-PVAPI-11 | Branch flow: `develop` -> `main` only as a release when the owner asks; hotfix to `main` only with explicit authorization in the current conversation; no "Branch policy" workflow (rulesets only); never `--admin`. | 2026-09-27 | PVAPI:AGENTS.md:45-54; MEM branch-flow-no-policy-automation | in force |

## 3. pequeverso-assistant-backoffice (GitHub: pequeverso-backoffice)

| ID | Decision | Date | Source | Status |
|---|---|---|---|---|
| EX-PVBO-01 | Backoffice sign-in is OAuth only (Google/GitHub) through Better Auth, invitation-gated: only the configured owner and people the owner invites; no password login, no open signup. | 2026-10-05 | PVBO:docs/adr/005 | in force |
| EX-PVBO-02 | Identity and access live in a dedicated private PostgreSQL provisioned by vps-ops; membership checked on every protected request. | 2026-10-05 | PVBO:docs/adr/006 | in force |
| EX-PVBO-03 | Operational data comes only from the API's private `/internal/v1/ops/summary` (server-to-server, 256 KiB cap, pinned contract); never display prompts, answers, buyer data, cookies or secrets; fixture data is labeled synthetic. | 2026-10-05 | PVBO:docs/adr/007; AGENTS.md | in force |
| EX-PVBO-04 | Analytics reads default OFF; the owner-authorized analytics report is not deployment or trusted-edge proof. | 2026-10-18 | PVBO:AGENTS.md; docs/product-analytics.md | in force |
| EX-PVBO-05 | The public conversation lives in the storefront; the earlier "one app, two shells", plain-text renderer and same-origin session ADRs are superseded. TypeScript 7 is the only type checker. | 2026-10-05 | PVBO:docs/adr/001,003,004 (superseded); 002 | in force / superseded history |
| EX-PVBO-06 | `main` receives only `develop` releases or an owner-authorized `hotfix/*`; nothing is deployed without explicit owner authorization. | 2026-09-27 | PVBO:AGENTS.md | in force |

## 4. portfolio (site)

| ID | Decision | Date | Source | Status |
|---|---|---|---|---|
| EX-PF-01 | Public personal portfolio, not a store of private career data; no personal claims, metrics or employer materials without approval; never change hosting, DNS or repo visibility without an explicit request. | 2026-09 | PF:AGENTS.md | in force |
| EX-PF-02 | No accept-cookies banner on the portfolio; analytics are off by default and cookie-free (a discreet accurate footer/privacy notice); any measure needing consent is not shipped. Pequeverso's banner is a separate owner decision. | 2026-10-17 | PF:docs/specs/product-analytics.md:13-16; AC-1 | in force |
| EX-PF-03 | Native portfolio assistant approved, but it must stay disabled until activation; analytics collection off independently of assistant rollout. | 2026-10 | PF:docs/specs/native-assistant.md:5; enterprise-architecture-maps.md:163 | in force |
| EX-PF-04 | Hosting is managed Node.js on Hostinger from `main` (no static export); deployment confirmed 2026-09-12. | 2026-09-12 | PF:docs/deployment.md:6,23 | in force |
| EX-PF-05 | Keep the solar-system background (owner requires it; "0 WebGL contexts" rubric note). Reading-route background (D2) is still open. | 2026-10 | PF:docs/master-plan/scorecard.md:73; README.md:121-126 | in force / D2 open |
| EX-PF-06 | Restore with criteria: MoonPay, ZeroDev, Google Gemini and Pydantic AI return to `/stack`, carousel and hero list with evidence link; PyTorch/TensorFlow/NumPy/pandas only on `/stack`. | 2026-10-24 | PF:docs/specs/ai-engineer-positioning-v3.md:93 (AC-17) | in force |
| EX-PF-07 | Displayed company marks and the named client are owner-approved; professional facts and Spanish/Rampy copy are owner-approved inputs only. | 2026 | PF:docs/assets/company-marks.md:5; docs/specs/professional-profile.md:7 | in force |
| EX-PF-08 | Dependency updates are manual by owner decision (Dependabot proposes weekly npm PRs; no native auto-merge). | 2026-10 | PF:docs/dependency-updates.md:5,75 | superseded by OD-20/OD-22 (single weekly PR, security-update PRs off) - stale doc |
| EX-PF-09 | HSTS preload is the domain owner's decision (not enabled by a build). Private vulnerability reporting enablement is an owner decision. | 2026-10 | PF:next.config.mjs:32; docs/master-plan/research/standards-and-index.md:1325 | in force / open |
| EX-PF-10 | Branch workflow: tasks into `develop`, only `develop` opens a release PR to `main`, merge commits, no bypass; interface EN + neutral Latin American Spanish. | 2026-09 | PF:AGENTS.md "Branch workflow" | in force |
| EX-PF-11 | shadcn/ui migration expansion approved; owned primitives with Tailwind utilities, CSS Modules preserved for layout/identity/motion. | 2026-09-19 | PF:docs/specs/shadcn-migration.md:3; AGENTS.md | in force (OD-41 now requires full Tailwind 4 token system) |

## 5. portfolio-assistant-api

| ID | Decision | Date | Source | Status |
|---|---|---|---|---|
| EX-PFAPI-01 | Fixture mode default; never read/log/use a real key or run paid calls without explicit authorization; only approved public portfolio content enters the corpus. | 2026-09 | PFAPI:AGENTS.md | in force |
| EX-PFAPI-02 | Monthly OpenAI budget capped at US$10 (config rejects more); conversation retention default 7 days (1-30). | 2026-10 | PFAPI:app/bootstrap/config.py:56,60,162 | in force (confirm with Q-A1) |
| EX-PFAPI-03 | Shared KVM 4 VPS and one assistant origin; production owned by vps-ops/Coolify (ADR 003 supersedes the app-owned stack). | 2026-09-27 | PFAPI:ADR 002, 003 | in force |
| EX-PFAPI-04 | Dependency/image vulnerability findings are advisory for deployment (do not auto-block); dependency maintenance manual. | 2026-10-19 | PFAPI:docs/deployment-contract.md:417 | in force (consistent with VPS policy; OD-22 for update flow) |
| EX-PFAPI-05 | PostgreSQL consolidation within Portfolio and canonical adapters accepted; Python 3.14 stays the runtime by owner decision until the shared Python 3.15 gate. | 2026-10-12/18 | PFAPI:ADR 005, 006; docs/verification/postgres18-2026-10-12.md:27 | in force; cross-check with EX-VPS-06 |
| EX-PFAPI-06 | Web chat remains off by default; production activation belongs to owner-approved vps-ops runs; backup destination/retention/key custody and API source license are open owner decisions. | 2026-10 | PFAPI:docs/verification/web-context-2026-10-13.md:109; IMPLEMENTATION_STATUS.md:164 | in force / open (Q-A2) |

## 6. portfolio-backoffice

| ID | Decision | Date | Source | Status |
|---|---|---|---|---|
| EX-PFBO-01 | Shared VPS, one public assistant origin; native portfolio chat and authenticated private operations (supersedes iframe delivery); one portfolio backoffice with separate project features. | 2026-09-27 | PFBO:docs/adrs/002,004,006 | in force |
| EX-PFBO-02 | Sign-in Google/GitHub only; verified owner plus invited viewers; no password login or open signup; membership live-checked in PostgreSQL. | 2026-10 | PFBO:AGENTS.md; ADR 004, 007 | in force |
| EX-PFBO-03 | Missing metrics are "unavailable", never zero or fixture data; no prompts or answers shown; no API keys in browser bundles. | 2026-10 | PFBO:AGENTS.md | in force |
| EX-PFBO-04 | `/privacy` states actual cookies and processing without claiming "cookieless"; contact is the existing portfolio contact page, not an invented legal entity or postal address. | 2026-10-17 | PFBO:docs/privacy-review.md | in force; jurisdiction/legal basis unresolved (Q-L9) |
| EX-PFBO-05 | Promote `develop` to `main` only with explicit owner authorization; dependency/image CVEs advisory for deployment. | 2026-10-19 | PFBO:AGENTS.md; docs/deployment-contract.md:241 | in force |

## 7. vps-ops (main-only)

| ID | Decision | Date | Source | Status |
|---|---|---|---|---|
| EX-VPS-01 | Coolify is the sole deployment authority; never run independent compose up/down or Docker mutations; never print secrets or raw environments. | 2026-10 | VPS:docs/adr/001; AGENTS.md | in force (Compose + Caddy is the recorded exit per OD-60) |
| EX-VPS-02 | Host baseline Ubuntu 26.04 LTS with direct Coolify secret delivery (replaces proposed 24.04). | 2026-10-12 | VPS:docs/adr/002 | in force (matches OD-60) |
| EX-VPS-03 | The VPS is not purchased/provisioned; deployment stays disabled until the owner provides the server and authorizes activation. | 2026-10-19 | VPS:docs/security/vulnerability-policy.md; README.md:287 | in force (matches OD-61) |
| EX-VPS-04 | Vulnerability findings (dependency and image) are advisory and never auto-block deployment; keep findings visible, never claim "vulnerability-free". | 2026-10-19 | VPS:docs/security/vulnerability-policy.md | in force (OD-22 governs update PRs) |
| EX-VPS-05 | Public edge: Cloudflare for future VPS hostnames while preserving the Hostinger Business CDN; owner confirmed both active 2026-10-19. DNS/nameserver migration is a separate owner decision. | 2026-10-18/19 | VPS:docs/adr/005; README.md:94 | in force |
| EX-VPS-06 | One PostgreSQL instance per project with separate application databases; PostgreSQL is Pequeverso's only default production relational engine; no cross-project DB containers. | 2026-10-17/18 | VPS:docs/adr/006; docs/handoffs/integration-matrix.md:260 | in force |
| EX-VPS-07 | Python 3.15 everywhere only when all in-scope consumers support it. | 2026-10-18 | VPS:docs/adr/008 | in force (OD-62 LTS-consistency) |
| EX-VPS-08 | Shared GraphRAG target for both assistants; shared bounded analytics with project-specific marketing: Meta/campaign integration is Pequeverso-only, none in Portfolio; unmeasurable-with-consent items stay disabled. | 2026-10-17/18 | VPS:docs/adr/004, 007 | in force |
| EX-VPS-09 | Privacy handoff: application owners own their notices and consent controls; before activation each flow needs evidence (actual cookies, provider disclosure, retention, accurate affiliate disclosure for Pequeverso commerce). No legal entity, address, governing law or retention is asserted by ops. | 2026-10-17 | VPS:docs/handoffs/privacy-and-accessibility.md | in force |
| EX-VPS-10 | Project backoffice transition (one portfolio backoffice, Pequeverso backoffice repo) verified against GitHub metadata. | 2026-10-17 | VPS:docs/handoffs/project-backoffice-transition.md | in force |

## 8. pequeverso-marketing (main-only; decisions/ has 47 DEC files)

Superseded (kept for history, not in force): DEC-2026-07-28 hub as destination, 08-01 primera persona / rotacion de acentos, 08-03 aprender-a-leer, 08-04 horarios linea base, 08-23 plan automatizacion Metricool, 08-24 camino de compra, 09-12 sitio propio, 09-13 una accion por red / franjas 14-20, 09-27 utm-y-dominio.

| ID | Decision | Date | Source | Status |
|---|---|---|---|---|
| EX-MK-01 | Organic validation: Meta Ads closed (ROAS ~0.72); do not reactivate paid ads on intermediate metrics; returning to ads needs repeatable organic message, defensible margin, reliable tracking. | 2026-07-20/21 | MK:DEC-2026-07-20-cierre-meta-ads; DEC-2026-07-21-validacion-organica | in force |
| EX-MK-02 | Pricing: Grafismo Fonetico US$14,99 one-time via Hotmart; upsell Imprime y Juega US$14,99 and downsell US$7,49 only inside the post-purchase funnel; prices only from `config/offer.json`. | 2026-07-26 | MK:DEC-2026-07-26-precios | in force |
| EX-MK-03 | No anchor price (no strikethrough, no "total value"); no urgency or scarcity without a real end date. | 2026-09-27 | MK:DEC-2026-09-27-sin-precio-ancla; open-questions A5 | in force |
| EX-MK-04 | Public name is "Grafismo Fonetico"; "Trazos y Sonidos" is internal and never shown to customers; ads never mention the operator brand (legal pages keep seller data). | 2026-09-12 / 2026-05-11 | MK:DEC-2026-09-12-nombre-publico; DEC-2026-05-11-sin-marca-operadora-en-anuncios | in force |
| EX-MK-05 | Quantities: "mas de 400 paginas" and "kit" by default; "9 PDF y 414 paginas" only when precision resolves a doubt. | 2026-08-03 | MK:DEC-2026-08-03-cantidades-mas-de-400 | in force |
| EX-MK-06 | Guarantee wording: "7 dias de garantia" without naming Hotmart in copys or images; never a learning guarantee; never "garantizado/100% efectivo". | 2026-11-09 | MK:brand/product-facts.md:18; brand/claims.md:35 | in force (matches OD-50) |
| EX-MK-07 | Results, achievements and first-person dramatizations are allowed (owner consulted his accountant); only verifiable false business facts block (fake reviews, ratings, customer figures, unissued endorsements, false prices/anchors). First-person is never presented as an identified real customer. | 2026-09-27 | MK:DEC-2026-09-27-copy-orientado-a-resultados; brand/claims.md:80-86; brand/ai-and-minors.md | in force; FTC risk recorded |
| EX-MK-08 | Testimonials: none used, real or invented; proof is the demonstration, concrete content and the guarantee. | 2026-10-24 | MK:playbooks/copywriting.md:163; copy-scoring.md:170; open-questions "Resueltas" | in force (restated by OD-51) |
| EX-MK-09 | No ad/affiliate/AI/pediatrician notices in copys, comments, stories, voice-over or on-image labels; disclosure lives only in native platform toggles (TikTok third-party commercial content for the affiliate; Metricool AI flags `isAiGenerated`/`isAigc`/`isAiGeneratedContent`; Facebook has no AI toggle so none). Owner accepts the recorded PROFECO/FTC risk; reopen if a network or authority objects, if ads are run, and review before 2027-01-25. | 2026-10-25 | MK:DEC-2026-10-25-sin-avisos-en-copys | in force; conflicts with Spain/EU (C-02) |
| EX-MK-10 | TikTok: YouTube title of the day; `commercialContentOwnBrand: true` for Grafismo, third-party for the affiliate; AI declared via platform flags while covers/voices are AI-generated. | 2026-09-13 / 2026-10-25 | MK:DEC-2026-09-13-tiktok-titulo-y-divulgacion; DEC-2026-10-25 | in force; whether to keep declaring AI on pieces with nothing synthetic is open (open-questions B8) |
| EX-MK-11 | AI people images exception: AI-generated still images of non-existent people incl. children and babies are allowed for Grafismo and the affiliate if an adult is present, clothed, no names/ages/schools, never presented as real clients; includes TikTok (owner accepts removal risk). Real photos/videos of children: adult hands by default. No voice cloning. | 2026-10-12/18 | MK:brand/ai-and-minors.md:58-90 | in force |
| EX-MK-12 | AI images are illustrative; do not redo for cover mismatches in the kit fan (kit shown on landing); redo only clear defects (misspelled text, wrong price US$14,99, deformed hands/faces). Images/carousels passing visual QA >= 80 are approved without the owner; videos and covers still need owner approval. | 2026-09-27 / 2026-10-31 | MEM ai-images-tolerant; MK:DEC-2026-10-31-estaticos-aprobados-por-qa | in force |
| EX-MK-13 | Images always JPG (1080x1350; TikTok 1080x1920 `-tiktok.jpg`), PNG deleted. | 2026-10-03 | MK:DEC-2026-10-03-imagenes-siempre-en-jpg | in force |
| EX-MK-14 | Links: clean URL without UTM in organic (`links.tracking = none`); copys write `pequeverso.com/grafismo-fonetico` (no https, no trailing slash); copys alternate `home` vs `product` link per piece (EXP-006); inside images/videos always `pequeverso.com`. | 2026-09-27 / 10-02 / 10-17 | MK:DEC-2026-09-27-url-limpia; DEC-2026-10-02-enlace-corto-en-copys; DEC-2026-10-17-copys-alternan-home-y-producto | in force |
| EX-MK-15 | Social bio: a single link `pequeverso.com`, no parameters, no extra links; per-origin tracking is a future improvement. | 2026-10-13 | MEM pequeverso-tracking-later; OD-52 | in force |
| EX-MK-16 | Facebook captions keep the clean link plus the automatic first comment (Meta's link-post cap does not affect this page, per owner and own data); revisit only on a sudden reach drop. | 2026-09-27 | MEM facebook-links-in-caption-ok; MK:open-questions D7 | in force (OD-52) |
| EX-MK-17 | All organic traffic goes directly to pequeverso.com; TikTok link in profile; one video goes out the same day on all four networks. | 2026-09-27 | MK:DEC-2026-09-27-trafico-directo-a-la-pagina; AGENTS.md:97 | in force |
| EX-MK-18 | Old domain digitalproductsteam.com is left as is: no redirects, no renewal work; a purchase from an old link skips the upsell funnel and that is accepted; the owner updates bios and published Facebook links himself. | 2026-09-13 / 2026-09-27 | MEM old-domain-left-as-is; MK:DEC-2026-09-13-dominio-viejo-vence, DEC-2026-09-27-reemplazo-completo-pagina-vieja; LEG 2026-09-13 | in force (superseded the LEG "keep >= 12 months" pending item) |
| EX-MK-19 | Metricool: scheduling through the official MCP (Starter plan) and the brand Drive (`Metricool/<year>/<month>/<day>`); the owner's copy to Drive is the approval; never publish in the past or duplicate; YouTube thumbnail ERROR is a Metricool bug, not ours. | 2026-09-13 / 09-27 | MK:DEC-2026-09-13-programacion-por-mcp; playbooks/metricool.md:274 | in force |
| EX-MK-20 | Drive folder `Metricool` is shared "anyone with the link" on purpose; never flag or ask to restrict; `social revoke` only informs. | 2026-09-27 | MEM drive-link-sharing-owner-decision; MK:playbooks/metricool.md:160 | in force |
| EX-MK-21 | This repo is the home of organic marketing; ai-business-ops is read-only legacy (never modify or clone). The Drive service-account key stays in `~/.secrets`, never printed or committed. | 2026-09-27 | MEM pequeverso-marketing-repo, pequeverso-drive-key; MK:DEC-2026-09-27-repo-de-marketing | in force |
| EX-MK-22 | Affiliate program: from October 2026 add Hotmart affiliate products; the owner chooses each product; objective is maximum revenue (~US$30 commission per sale); do not veto or be demanding; only stop risks to accounts or legality (health/guaranteed-result claims in OUR copy, scam). First affiliate: baby-feeding course, US$49,99 may appear in copy as "US$49,99"; "+2000 estudiantes" allowed (verifiable on Hotmart); no fear hooks (choking etc.), commercial pains only; say "el curso de alimentacion para bebes", never "la guia". | 2026-09-27 / 10-12 / 10-25 / 11-09 | MEM affiliates-revenue-first; MK:DEC-2026-09-27-ampliar..., DEC-2026-10-12-afiliado-alimentacion-bebes; playbooks/lecciones-iteraciones.md:49-54; open-questions Resueltas | in force |
| EX-MK-23 | Copy scoring: every copy per network scored 1-100; scheduled only at >= 85 with seven gates passed; judge from a different model than the writer; competitors never named or compared; no free sample by DM; clarity gate is "fundamental". | 2026-10-24 / 11-09 | MK:DEC-2026-10-24-sistema-de-puntuacion-de-copys; playbooks/copy-scoring.md:334 | in force |
| EX-MK-24 | Language and voice: neutral Latin American Spanish with "tu" in all text (customers are from all of LatAm, not just Argentina); voices rotate Argentine, Colombian and Mexican accents; the lint flags voseo; quoted phrases use double quotes. | 2026-10-04 / 10-18 | MK:DEC-2026-10-18-angulos-variados-y-acentos-en-voz; DEC-2026-09-19-audios-neutros-y-cta; AGENTS.md:11-12; brand/voice.md:29 | in force (OD-51/OD-32) |
| EX-MK-25 | Comenta LEER/BEBE works on YouTube and in the voice of all four networks; TikTok copy keeps "Escribenos por mensaje"; ManyChat Pro monthly trial (30 days, Facebook page, no AI add-on) with keyword -> DM, no promise of automatic reply. | 2026-10-17 / 10-25 | MK:DEC-2026-10-25-comentar-en-youtube; DEC-2026-10-17-manychat-prueba-mensual | in force |
| EX-MK-26 | Schedule: Facebook 11:00, YouTube 18:00, Instagram 20:00, TikTok 21:00 daily; moving times outside a band the owner declared good needs the owner. Brand identity (blue isotype, navy/cream, coral only for the buy action) approved. | 2026-10-18 / 08-04 | MK:DEC-2026-10-18-horarios-ganadores; DEC-2026-08-04-identidad-visual; AGENTS.md:125 | in force |
| EX-MK-27 | Agent autonomy: decide only operational matters; ask the owner only about brand tone contradicting what exists, new promises/claims, personal or legal data, costs/plan changes, moving times. Collect owner questions in `decisions/open-questions.md`; reply in Spanish. | 2026-09-27 | MEM pequeverso-autonomy; MK:AGENTS.md:125 | in force |
| EX-MK-28 | No Thanksgiving content (LatAm audience), decided by the agent under owner delegation (recorded in open-questions "Resueltas"). Hashtags: closed vocabulary with `#grafismosfoneticos`, Instagram max 5. | 2026-10-25 / 08-03 | MK:open-questions Resueltas; DEC-2026-08-03-vocabulario-de-hashtags | in force |

## 9. Cross-repo (workflow, identity, tooling)

| ID | Decision | Date | Source | Status |
|---|---|---|---|---|
| EX-X-01 | Only the `gonzalomartinperez` GitHub identity may appear in commits, PRs, `gh`; never the owner's secondary GitHub account or its email; never set a repo-local email from session context. | 2026-09-27 | MEM github-identity-rule | in force (OD-15) |
| EX-X-02 | Merge only when CI is green: `gh pr checks <n> --watch && gh pr merge`; never chain with `;`. | 2026-09-27 | MEM merge-only-green-ci | in force (OD-14) |
| EX-X-03 | `main` only receives releases from `develop`; hotfix directly to `main` needs explicit per-fix owner authorization in the current conversation; never `--admin`, never push to main, never edit rulesets to force a merge; at the end only `main` and `develop` remain, in sync. | 2026-09-27 | MEM main-branch-hotfix-authorization | in force; reframed by OD-11 (main promoted once at M7) |
| EX-X-04 | Branch flow is a working agreement: no "Branch policy" workflow; rulesets only (PR + strict aggregate checks, no force/delete, no bypass, merge commits). | 2026-10 | MEM branch-flow-no-policy-automation | in force (OD-14 adds layers for private repos) |
| EX-X-05 | Never `pkill -f`; kill by verified PID (check `/proc/<pid>/cwd`). | 2026-10-13 | MEM no-pkill-f | in force (OD-74) |
| EX-X-06 | Web stack preferences: Tailwind 4 complete design system with owned CVA primitives, everything possible in TypeScript (TS 7, Node 24 type stripping); sibling repos are guides, not templates. | 2026 | MEM web-stack-preferences | in force (OD-41) |
| EX-X-07 | Workspace: repos under `~/projects/github/<owner>/<repo>`, never `/mnt/c` or `/mnt/d`; keep >= 100 GB free on drive C:. | 2026-11 | /home/gmperez/projects/github/AGENTS.md | in force (OD-63) |
| EX-X-08 | Never use `git stash`; use WIP commits; preserve concurrent changes of other agents. | 2026-09-27 | MEM pequeverso-autonomy; MK:AGENTS.md:113; PVBO:AGENTS.md | in force |
| EX-X-09 | Dependency and image CVEs are advisory for deployment (owner, 2026-10-19), maintenance manual. | 2026-10-19 | VPS:docs/security/vulnerability-policy.md; PFAPI deployment-contract.md:417; PFBO deployment-contract.md:241 | in force (OD-20/22 define the PR flow) |
| EX-X-10 | Apps ship assistants/analytics/ad-tech disabled by default; each production activation (assistant, analytics reads, paid model calls, DNS, VPS apply) needs separate explicit owner authorization. | 2026-10 | PV:ADR-0008; PVAPI:AGENTS.md; PFAPI; VPS:README.md:287 | in force (OD-05, OD-61) |

## Legal and compliance (consolidated)

### Decisions already taken

1. Seller: Argentine natural person; identity (name, CUIL, domicile) published on legal pages with consent (2026-09-24); removed from the footer on the accountant's advice (2026-09-26). Values live in `pequeverso:content/es/legal/seller.ts`.
2. Governing law: Argentina, without prejudice to the buyer's mandatory local law; consumer chooses forum; Bahia Blanca is one option (EX-PV-07). Data controller: the Titular (Ley 25.326, Decreto 1558/2001, AAIP).
3. Legal pages: aviso legal, privacidad, cookies, terminos, compras y reembolsos, arrepentimiento (Boton de arrepentimiento), soporte; per-country buyer-rights table with only verified periods.
4. Refunds: Hotmart guarantee 7 days (OD-50); longer legal windows (Spain/EU 14 d, Argentina and Chile 10 d) honored manually by email with manual refund; the 24 h arrepentimiento code must be operated by the owner.
5. Currency/pricing: single USD price, local-currency note, Hotmart shows final total; no anchor price; no fake urgency.
6. Consent/tracking: opt-out Meta Pixel + CAPI relay (2026-09-14), geo-blind banner; portfolio has no banner and analytics off; Meta/marketing integration is Pequeverso-only (VPS ADR-007).
7. Disclosure: site keeps an affiliate disclosure and "Video ilustrativo"; social copy carries no disclosures (DEC-2026-10-25), only native toggles.
8. AI: assistants disabled; assistant privacy section required before activation; 24 h retention (Pequeverso), 7 d default (portfolio); no training/ZDR claims.
9. Testimonials: none. Affiliate: revenue first, risk-only brakes.
10. Old domain lapses (domain 2026-11-25, mail plan 2026-12-22 per LEG); no redirects.
11. Hotmart facts are owner/Hotmart data, never invented; pages must not promise anything inconsistent with config (OD-50).

### Gaps that need an owner answer (questions with recommendation)

| # | Question | Recommendation |
|---|---|---|
| Q-L1 | Place the "Boton de arrepentimiento" on the first screen (Disp. SSDCyLC 954/2025 art. 1) - header/topbar link? | Yes: add a header/topbar link to `/arrepentimiento/` in the redesign (small cost; removes the only hard compliance gap). |
| Q-L2 | Restore full seller identification in the footer (Res. SCI 270/2020 art. 2 "easy visibility") or keep the 2026-09-26 accountant-advised choice? | Keep the decision but get the accountant's/lawyer's written confirmation; if unsure, show name + contact mailbox in the footer and keep CUIL/domicile on legal pages. |
| Q-L3 | AAIP database registration (Ley 25.326 art. 21) - who and when? | Owner does it via TAD (free); schedule before M7 promotion to main. |
| Q-L4 | Data Fiscal (F. 960/D) on the home page - applicable? | Ask the accountant; add to footer only if required. |
| Q-L5 | Consent: keep opt-out, or switch to prior consent (opt-in) at least for EU/Spain, given OD-32 now says Spain is a possible market? | Switch `DEFAULT_CHOICE` to opt-in for marketing (global, one-line change; tests encode current policy and must change). Cost: lower pixel counts; benefit: removes the only item the repo itself flags as non-compliant with ePrivacy/Ley 25.326 art. 5. |
| Q-L6 | Prices in pesos for Argentine visitors (Res. SIyC 4/2025) and "precio sin impuestos nacionales"? | Show an ARS reference price to Argentine visitors only if a lawyer says checkout totals are not enough; otherwise record the lawyer's opinion in the checklist. |
| Q-L7 | Affiliate and AI disclosure outside LatAm (Spain/EU: UCPD, national advertising law, AI transparency rules) given DEC-2026-10-25? | Keep no-notice copy for LatAm, but turn on every native toggle (TikTok, Instagram/Facebook branded-content tools when available) and decide whether Spain-targeted content gets a minimal "Colaboracion comercial" note; get lawyer confirmation before targeting Spain. |
| Q-L8 | Lawyer review (provincia de Buenos Aires) of the jurisdiction clause, CCyC 1116 b) reliance, Chile (PDF good or service) and the country table. | Commission one review before M7 (production promotion); budget is the owner's. |
| Q-L9 | Portfolio backoffice/assistant: applicable jurisdiction, legal basis, IAM/audit cleanup policy, provider regions, backup expiry (privacy-review unresolved list). | Owner answers jurisdiction once; engineering sets cleanup/retention defaults (e.g. 7-day conversations, 90-day audit) for approval. |
| Q-L10 | Pequeverso assistant privacy section in `/privacidad/` (24 h retention, OpenAI as processor, human contact). | Write it in the refactor, keep assistant disabled; activation stays a separate owner decision. |
| Q-L11 | Guarantee beyond 7 days: the checklist recommended 15 days, OD-50 chose 7 + manual honoring. | No action; make sure `/terminos/` and `/compras-y-reembolsos/` describe the manual 14/10-day path exactly as OD-50. |
| Q-L12 | Old mailbox/domain: ai-business-ops lists "create new mailboxes and update Hotmart and legal pages before 2026-12-22". | Confirm Hotmart and legal pages use only the new mailbox before 2026-11-25; time-critical (16 days). |
| Q-L13 | Should the AI declaration stay on pieces with nothing synthetic (open-questions B8) and what label do Facebook posts get? | Keep platform flags on only when synthetic content exists; leave Facebook as is (no toggle). |
| Q-L14 | Fear-angle limits and health claims for the baby-feeding affiliate (open D4). | Already narrowed by 2026-11-09 (no fear hooks); close D4 with that decision. |

## Conflicts

| ID | Conflict | Recommendation |
|---|---|---|
| C-01 | EX-PV-10 (opt-out consent, 2026-09-14) vs OD-32 (Spanish-speaking audience, possibly Spain) and PV's own legal note (opt-out does not meet AEPD/ePrivacy prior-consent; Ley 25.326 art. 5 requires express consent). | Treat as owner question Q-L5; recommend opt-in default for marketing. Until answered, agents must not change `DEFAULT_CHOICE` and must not describe the site as compliant for Spain. |
| C-02 | EX-MK-09 (no ad/affiliate/AI notices in social copy) vs Spain/EU practice, PROFECO/FTC guidance (already recorded as accepted risk) and VPS handoff requirement "accurate affiliate disclosure" (EX-VPS-09); also inconsistent with the site (EX-PV-13 keeps disclosure). | Keep the LatAm decision (owner accepted risk, reopen conditions already recorded), add the native toggles, and require a disclosure the moment Spain/EU is targeted or ads run (Q-L7). Do not remove the site-side disclosure. |
| C-03 | PV:AGENTS.md says "static export (default)" and "both build targets must keep working"; ADR-0001 default is export; reality since 2026-10-13 is Hostinger standalone (CAPI relay needs a Node server); portfolio never used static export. | Declare standalone canonical in AGENTS/ADR-0001 (new ADR), keep static only as a CI parity build if the owner wants a fallback, and remove "static export (default)" wording. Stale doc, not a new owner decision. |
| C-04 | EX-PV-04 legal-checklist recommendation (15-day guarantee) vs OD-50 (7 days + manual honoring). | OD-50 wins; mark owner action 2 as resolved-by-OD-50 and check that legal pages describe the manual process. |
| C-05 | PV:AGENTS.md requires "ci + Branch policy" checks and describes squash-to-develop; MEM branch-flow-no-policy-automation says no Branch policy workflow (rulesets only); OD-14 adds five layers for private repos. | Drop "Branch policy" from AGENTS and ruleset docs; rely on rulesets + `ci-gate` (OD-72). Stale doc. |
| C-06 | Site labels demo videos "Video ilustrativo" and says AI-generated (EX-PV-19), social removed such labels (EX-MK-09). | Acceptable by surface; keep the site statement (cheap, defensible) and note it as intentional so agents do not "harmonize" it away. |
| C-07 | PF dependency docs: "manual by owner decision" with weekly Dependabot npm PRs vs OD-20 (one PR per repo per week, all ecosystems, Monday 09:00 ART) and OD-22 (security-update PRs off). | OD-20/OD-22 supersede; update PF/PFAPI/PFBO docs in M-plans. |
| C-08 | PFAPI keeps Python 3.14 "by owner decision" (2026-10-12) vs VPS ADR-008 Python 3.15 everywhere (2026-10-18, gated) vs OD-62 (LTS, one canonical config). | Keep 3.14 until the ADR-008 gate (all consumers supported) passes, then migrate both APIs together; record as one planned change. |
| C-09 | PVAPI ADR-0004 (Spanish and English) vs ADR-0006/OD-32 (Spanish-only). | ADR-0006 and OD-32 win; mark ADR-0004 language part superseded. |
| C-10 | Retention differs by product: PVAPI 24 h vs PFAPI default 7 days; PV privacy page must state the Pequeverso number only. | Intentional; do not unify unless the owner asks. |
| C-11 | OD-11 says main promoted once at M7 and hotfix needs authorization; MEM says release develop -> main "when the owner asks to sync" (per release). | Compatible; OD-11 is stricter for the refactor window only. |
| C-12 | MK allows first-person dramatizations (EX-MK-07) while testimonials are banned (EX-MK-08) and OD-51 forbids invented testimonials. | Not a contradiction if dramatizations are never presented as real customers; keep that line in the scoring gates and flag any "reseña/cliente real" wording. |
| C-13 | Pequeverso light-theme-only (ADR-0006) vs portfolio themes and OD-43 (families share palette direction). | No conflict: dark mode is refused for Pequeverso only; do not add a dark variant there without a new owner decision. |
| C-14 | The old domain/mail expiry dates (2026-11-25 / 2026-12-22) still require mailbox and Hotmart updates though "no renewal work" is decided. | See Q-L12; not a reversal of the old-domain decision. |
