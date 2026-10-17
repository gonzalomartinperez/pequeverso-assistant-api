# Pequeverso · Assistant API

![Python](https://img.shields.io/badge/Python-3.15.0-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-typed_HTTP-009688?style=flat-square&logo=fastapi&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-WAL_%2B_FULL-003B57?style=flat-square&logo=sqlite&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI-GPT--6_Luna-06305B?style=flat-square&logo=openai&logoColor=white)
![Effort](https://img.shields.io/badge/reasoning-medium-007E80?style=flat-square)
![Contract](https://img.shields.io/badge/contract-v1_%C2%B7_1.5-06305B?style=flat-square)
![Language](https://img.shields.io/badge/native_assistant-Espa%C3%B1ol-007E80?style=flat-square)
![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-opt--in-06305B?style=flat-square&logo=opentelemetry&logoColor=white)
![Prometheus](https://img.shields.io/badge/Prometheus-private_metrics-E6522C?style=flat-square&logo=prometheus&logoColor=white)
![CI](https://github.com/gonzalomartinperez/pequeverso-assistant-api/actions/workflows/quality.yml/badge.svg?branch=develop)

Backend of the Pequeverso shopping assistant: an **advisory, read-only** AI assistant that helps
adult buyers understand the Grafismo Fonético kit and the separately recommended affiliate
course, compare their published scope and reach the appropriate storefront flow. Public repository; no license is granted
(all rights reserved). `main` is the default and release branch; development happens on `develop`.

- Python 3.15.0, FastAPI, uv; SQLite (single process); OpenAI Responses (`gpt-6-luna`) behind a
  provider port; a deterministic **fixture provider is the default**.
- Versioned HTTP/SSE contract (v1, revision 1.5) for the storefront's native assistant, which
  calls the API cross-origin; private, token-protected operations summary for the backoffice
  (`pequeverso-backoffice`, renamed from `pequeverso-assistant-backoffice`; the original
  chat repository was `pequeverso-assistant-web`).
- The native assistant presents only neutral Latin American Spanish ("tú"), without a language
  selector. Every new native turn sends `response_language: "es"` and requires API revision1.4
  or later. Earlier API clients remain compatible when this field is absent, including their
  legacy ES/EN behavior and stored history; the existing wire enum is preserved.
- `gpt-6-luna` at **medium** reasoning effort when paid use is authorized; budget USD 10/month
  (configurable) with atomic reservations and confirmed / estimated / pending spend.
- Optional [official Hotmart procedure evidence](docs/official-web-evidence.md) is server-owned,
  bounded to three public articles and disabled by default; no autonomous searches or buyer-account tools.
- Grounded in a catalog exported from the storefront at a pinned commit; every product,
  link and price shown is server-validated.
- [Architecture and resource ownership](docs/architecture.md) keep SDK/HTTP/SQLite details outside
  the use cases. [Engineering standards](docs/engineering-standards.md) define review evidence,
  four-session ownership, reproducible locks/digests and supported-version policies.

The commercial goal is an informed purchase: answer the adult's question, explain the fit and
offer the authorized next step when relevant. Evidence and budget constraints remain binding;
a completed response or a valid citation does not establish semantic correctness. The storefront
assistant stays **disabled in publishable builds** until the VPS and activation gates are verified.

## The native assistant in use

The photograph below shows the actual **408 × 560 px compact panel** in the local storefront,
connected to this API over credentialed HTTPS/SSE. Its authored, non-personal sample question
received a real **GPT-6 Luna, medium** answer about digital delivery and the guarantee.
The visible answer matched the saved HTTP history and the exact completed-request replay;
the replay did not invoke the provider again. **This is local verification, not a deployed VPS
or an enabled production assistant.**

[![The real locally connected Spanish assistant in its compact storefront panel](docs/verification/native-assistant-2026-10-12/real-desktop-context.png)](docs/verification/native-assistant-2026-10-12/real-desktop-context.png)

| Complete real-model answer | Actual source disclosure |
| --- | --- |
| <a href="docs/verification/native-assistant-2026-10-12/real-desktop-answer.png"><img src="docs/verification/native-assistant-2026-10-12/real-desktop-answer.png" width="408" alt="Complete GPT-6 Luna answer about delivery after payment approval and the conditional seven-day refund request"></a> | <a href="docs/verification/native-assistant-2026-10-12/real-desktop-sources.png"><img src="docs/verification/native-assistant-2026-10-12/real-desktop-sources.png" width="408" alt="Expanded authorized digital-delivery and guarantee sources at a separate real scroll position"></a> |

Each image opens at its original **DPR 2** resolution. Source details use a separate genuine
scroll position; the panel was not enlarged and the photographs were not stitched.
The [gallery and provenance](docs/verification/native-assistant-2026-10-12/README.md) also show
the welcome, provisional streaming, complete mobile product card and recoverable network error.
Those additional states use the **fixture API** and are labeled separately. The two native
photo probes used independent browser sessions; their original capture failures are retained.
Neither a real-provider reload/mobile result nor a production deployment is claimed.
These dated captures retain their original storefront/API revisions in the gallery manifest;
they do not depict the later 2026-10-13 post-tool evaluation or its corrected backend.

## System at a glance

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/architecture/system-dark.svg">
  <img src="docs/architecture/system-light.svg" alt="Assistant API boundaries: public session and CSRF, validated evidence, API-owned SQLite, bounded OpenAI generation, separate backoffice PostgreSQL identity and future private vps-ops observability.">
</picture>

[Open full-size diagram](docs/architecture/system-light.svg) ·
[Dark version](docs/architecture/system-dark.svg) ·
[Editable Mermaid and provenance](docs/architecture/README.md).

The API owns SQLite catalog, conversations and accounting; the backoffice owns its separate
PostgreSQL identity database. Fixture is the default provider. An authorized real generation uses
one bounded OpenAI call; optional Hotmart retrieval reads only three fixed official articles and
is disabled by default. OTLP, private metrics and Grafana are integration responsibilities for
vps-ops, not evidence of deployment, VPS capacity or production readiness.

| Boundary | Responsibility |
| --- | --- |
| Storefront | Conversation UI, safe rendering and continuity; Hotmart checkout and existing consent remain unchanged |
| API | Sessions, language selection, grounding, streaming, cancellation, validation and budget reservations |
| SQLite | Isolated conversations and accounting; public catalog snapshots are separate from private messages |
| Backoffice | OAuth and roles on PostgreSQL; reads private, content-free operations data server-side |
| vps-ops | Publishes and deploys selected images; owns reverse proxy, Coolify, shared monitoring and backups |

There are no payment/order tools, embeddings, Neo4j, Redis or a graph orchestration framework.
Structured catalog facts remain present; exact request packing can prune optional passages and
old model-context text to retain the unchanged 24KB bound. Lexical ranking is measured separately.

## One question, one accountable generation

```mermaid
sequenceDiagram
  participant UI as Native assistant
  participant API as HTTP boundary
  participant App as Chat service
  participant DB as SQLite
  participant AI as GPT-6 Luna
  UI->>API: Session + Origin + CSRF + idempotency key
  API->>App: Validated visitor turn
  App->>App: Pack merchant context and complete source paragraphs within 24k
  App->>DB: Claim request + reserve worst-case spend
  App->>AI: Authorized evidence + history, medium, no retries
  AI-->>App: Structured deltas + usage
  App->>App: Normalize and check complete cumulative prefixes
  App-->>UI: Checked provisional message.delta
  App->>App: Resolve references + validate commercial claims
  App->>DB: Persist authoritative answer + settle known usage
  App-->>UI: message.completed + run.completed
  Note over App,DB: Known usage is settled.<br/>Missing usage retains its reservation.<br/>Partial answers are not stored.
```

Provider credentials exist only in the backend. Fixture is the default; real evaluations require
current owner authorization, private configuration and one shared conservative budget. Model
errors do not trigger a substitute model or an automatic generation retry.

Only complete sentence/paragraph prefixes passing the same bounded commercial checks as the
final answer can stream. A later invalid claim can still replace an earlier checked prefix;
the client must render the authoritative `message.completed`. Catalog guarantee checks apply
even when optional Hotmart retrieval is disabled or unavailable. These deterministic checks
do not establish complete semantic correctness or citation entailment.

Explicit resource page counts are checked against structured catalog metadata. Request packing
preserves products/resources and merchant policies, trims only model-context history and optional
documents when needed, and leaves saved conversations unchanged. Citations resolve only to
evidence actually sent in that generation. The [post-tool report](docs/verification/post-tools-2026-10-13.md)
preserves the original halted run separately from subsequent fixes and revalidation; completion
and agent review are distinct from semantic correctness and human acceptance.

## Quick start (clean checkout, no credentials)

```
uv sync --frozen
uv run uvicorn app.main:app --reload --port 8000      # fixture mode, bundled catalog, ./data/
curl -s -c /tmp/j -H 'Origin: http://localhost:3000' -H 'Content-Type: application/json' \
  -X POST localhost:8000/api/v1/session -d '{}'
```

Ask a question (replace `<csrf>` with `csrf_token` from the response):

```
curl -N -b /tmp/j -H 'Origin: http://localhost:3000' -H 'Content-Type: application/json' \
  -H 'X-CSRF-Token: <csrf>' -H 'Idempotency-Key: local-0001' \
  -X POST localhost:8000/api/v1/messages -d '{"content":"¿Qué incluye el kit?"}'
```

## Verify

```
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run pytest                                   # unit, HTTP/SSE contract, real-socket streaming, SQLite, budget races, evals
uv run python -m contracts.export --check       # pinned contract artifacts are current
uv run python scripts/evaluate_retrieval.py
uv run python scripts/evaluate_conversations.py # fixture safety + guards (no paid calls)
scripts/smoke_container.sh                      # image: non-root, read-only, SSE, restart persistence
```

## Documentation

| Topic | Doc |
|---|---|
| Public contract (sessions, SSE, references, freshness, errors, languages) and private ops API | `docs/api-contract.md` + `contracts/`; handoffs `docs/handoffs/storefront-transition.md` (native assistant) and `docs/handoffs/backoffice.md` (backoffice) |
| Architecture and decisions | `docs/architecture.md`, `docs/decisions/` |
| Security, privacy, retention | `docs/security.md` |
| Catalog source, sync, freshness | `docs/catalog.md` |
| Evaluation and live procedure | [Procedures](docs/evaluation.md), [historical real-model evidence](docs/verification/real-model-2026-10-12.md), [post-tool verification and limits](docs/verification/post-tools-2026-10-13.md) |
| Optional private telemetry, metrics and traces | `docs/observability/README.md` |
| Deployment handoff (vps-ops/Coolify) | `docs/deployment-contract.md` |
| Dependency updates and manual review | `docs/dependency-updates.md` |
| Reference adoption (portfolio-assistant-api) | `docs/reference-adoption.md` |
| Storefront transition, vps-ops handoff, open business questions | `docs/handoffs/storefront-transition.md`, `docs/handoffs/vps-ops.md`, `docs/business-questions.md` |
| Agent instructions and skills | `AGENTS.md`, `.agents/skills/` |

## Verification and operational limits

- Fixture suites verify the pipeline, guards and persistence; they do not measure model quality.
  Real model reports must distinguish usage-derived cost estimates from invoices and retain
  interrupted requests. See [evaluation](docs/evaluation.md).
- A catalog's Git revision proves provenance, not deployment or the final merchant checkout
  total. Expired prices are withheld. See [catalog freshness](docs/catalog.md).
- Logical deletion does not guarantee erasure from SQLite bytes, WAL or backups. Retention,
  encrypted off-server backup and an operational restore drill remain activation gates.
- Containers are non-root, read-only and resource-limited. Smoke the exact selected image,
  including active-stream shutdown; preserve the grace specified in the deployment contract.
- Prefer LTS branches where offered and supported stable releases elsewhere. Most libraries
  do not publish an LTS guarantee; pins, security review and reproducibility remain necessary.
- Python 3.15 is a supported stable branch, not an official LTS line. The selected Python
  OpenTelemetry SDK/exporter is 1.45.1; its locked tree includes three 0.66b1 beta packages.
  Prometheus 3.13 is the monitoring LTS target; Grafana and the collector have their own support
  and component-stability policies. vps-ops selects and deploys their final images.
  See the official [Python lifecycle](https://devguide.python.org/versions/),
  [Prometheus LTS schedule](https://prometheus.io/docs/introduction/release-cycle/),
  [Grafana policy](https://grafana.com/docs/grafana/latest/upgrade-guide/when-to-upgrade/) and
  [collector stability table](https://github.com/open-telemetry/opentelemetry-collector/blob/main/docs/component-stability.md).
- No build, screenshot or local test authorizes a deployment or production activation.

Task branches target `develop` through protected squash PRs. A release into `main` requires
separate owner authorization and a protected merge commit. Public repository, all rights reserved;
no license is granted. Never commit secrets, private evaluations or customer conversations.

Shared runtime/version acceptance: [runtime baseline](docs/runtime-baseline.md).

### Affiliate product coverage (2026-10-17)

The catalog now includes Grafismo Fonético and the separate third-party **Guía de Alimentación
para Bebés**, exported from storefront main `bddd36f45b319571f52029dfe4d6b3283cd71287`. The
course has no authorized published price, PDFs or page counts: those remain null. Its published
seven-day guarantee and affiliate disclosure stay product-scoped; the kit policy cannot transfer
to the course. Revision1.5 adds optional card kind/format/disclosure fields, with core defaults
for historical messages. See [catalog](docs/catalog.md) and [contract](docs/api-contract.md).
Fixture tests prove transport, grounded metadata, history and replay; they do not establish
real-model quality, a functioning affiliate redirect or readiness of an undeployed VPS.
