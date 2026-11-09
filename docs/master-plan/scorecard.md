# Scorecard — pequeverso-assistant-api

Rubrics v2 (`rubrics.md`, byte-identical across the nine repos). Scores never compensate across axes; target is at least 95 on every axis, with a floor of 90 only where an unauthorized input blocks it (VPS, paid model calls, human labels), stated in the "Target" column. Caps from the rubric: a failing required check caps a lens at 70 (none failing today); a committed secret caps Security at 40 (gitleaks over full history is green); a contract break without a major path caps Architecture at 60 (none).

Baseline scores are the planner's estimates against the rubric on 2026-11-09 (develop `6912579`), each anchored to measured evidence in `audit.md`. They are provisional until the first independent re-score at M3 (rubric rule: a criterion without evidence is unmet; independent evaluators do not see the planner's reasoning). The owner's provisional numbers in `owner-decisions.md` (architecture 88, AI 62, CI and supply chain 72, docs 65, deploy 60) are kept consistent.

## Lens 1 — Senior developer

| Axis | Baseline | Evidence and unmet critical criteria | Target | Automatic measurement | Ratchet file |
|---|---:|---|---|---|---|
| D1 Architecture | 88 | AST guard with negative fixtures (`tests/test_architecture*.py`), composition root in `bootstrap`, ports as Protocols; unmet: import-linter contracts and independence between adapters, empty-baseline report | 95 | `lint-imports` plus AST test output | `ratchets/guards.json` (violations, 0) |
| D2 Code quality | 80 | ruff 0 and mypy strict 0 (123 files); unmet: complexity ≤ 10 (19 functions above, max 36), dead-code check, ecosystem ruff families (1,331 findings on app, scripts, contracts) | 95 | ruff JSON, mypy, vulture, complexity script | `complexity.json`, `ruff.json`, `mypy-errors.txt` (0) |
| D3 Tests | 72 | 1,698 passed; unmet: branch coverage floor (76.5% local), diff coverage, mutation, property tests, flake evidence, contract diff | 95 | coverage JSON, diff-cover, mutmut report, flake nightly | `coverage.json`, `mutation.json` |
| D4 CI/CD | 72 | single aggregate gate, SHA pins; unmet: dynamic execution, weekly single Dependabot PR, build-once release path | 95 | `ci-profile.json` test, weekly duration report, Dependabot guard result | `ci-duration.json` |
| D5 Security and supply chain | 70 | SHA-pinned, least privilege, zizmor, gitleaks, threat model (`docs/security.md`); unmet: CodeQL, SBOM, provenance, Scorecard, vulnerability SLA, 1 critical dependency finding | 95 | CodeQL, Scorecard score, osv, Grype, attestation verify | `image.json`, `scorecard-ossf.json` (score never drops more than 1) |
| D6 Performance | 55 | per-run latency and token fields are logged; unmet: budgets enforced in CI, load test | **90 until MV**, 95 after real-host load | Locust nightly, `pytest-benchmark`, live-lane percentiles | `perf.json` (regression 20%) |
| D7 Observability | 72 | allowlisted JSON logs without PII, request id, health and readiness, Prometheus and OTel opt-in, alert and Grafana files; unmet: SLOs defined and burn-rate alerts, log-noise fix, health names per contract | **90 until MV** (real dashboards need the VPS), else 95 | redaction and request-id tests, `promtool check`, env-schema test | `observability.json` |
| D8 Docs and DX | 65 | README present but off-template, 9 ADRs, CHANGELOG, skills validated structurally; unmet: README template, MADR Confirmation, community files, activation evals, no stale numbers | 95 | README heading check, lychee, docs-numbers check, skills evals | `docs.json` |
| **Lens mean** | **71.8** | (reported, not a gate) | | | |

## Lens 2 — Senior product designer, mapped for an API (error and response contract, streaming UX, assistant message quality, contract docs, consumer consistency)

| Axis | Baseline | Evidence and unmet criteria | Target | Automatic measurement | Ratchet file |
|---|---:|---|---|---|---|
| P1 Error and response contract clarity | 80 | stable machine codes, `request_id`, examples (`contracts/examples/errors.json`); unmet: RFC 9457 mapping documented (PVA-D6), complete schema coverage | 95 | contract tests, examples validate against schemas | `contracts.json` |
| P2 Streaming UX | 85 | closed SSE event set, heartbeat, cancel, `first_delta_ms` logged; unmet: time-to-first-delta budget asserted | 95 | SSE conformance tests, Locust, live-lane percentiles | `perf.json` |
| P3 Assistant message quality | 62 | deterministic gates in code and 0 gate failures in 288 fixture cases; real-model review 195 of 245 acceptable; unmet: golden set 100% gate, language and abstention strata, validated judge | **90 until live pass^3 and owner labels (PVA-D13, D14)**, then 95 | golden replay and live report, full-set metrics | `golden.json`, `retrieval.json` |
| P4 Contract docs and examples | 78 | 15 contract examples; unmet: OpenAPI covers 4 paths and 5 operations only, no oasdiff, per-operation docs | 95 | `contracts.export --check`, oasdiff, example validation | `contracts.json` |
| P5 Parity with the storefront | 85 | versioned snapshots; unmet: scheduled consumer-compile job | 95 | cross job in the contract profile | `contracts.json` |
| P6 Parity with the backoffice and ops | 85 | private ops schemas and telemetry examples; unmet: same cross job against `openapi.internal.json` | 95 | cross job | `contracts.json` |
| **Lens mean** | **79.2** | | | | |

## Lens 3 — Senior e-commerce and CRO (assistant messaging only; the store UI belongs to `pequeverso`)

| Criterion | Baseline | Evidence | Target | Measurement |
|---|---:|---|---|---|
| Assistant messaging: grounded, discloses AI, no invented facts, price and guarantee exact, abstains out of scope, human handoff offered | 80 | grounding enforced in code (`answer_policy.py`, `answers.py`); prompt identifies as AI when asked; `no_info` and `decline` offer a support route (graded); out-of-scope and support recall weak; no live conversion data (assistant disabled) | 95 (90 until live pass^3) | golden strata counts (price, guarantee, abstain, adversarial) all 100%; support-route assertion |
| Privacy-respecting analytics and consent | not scored here | product analytics channel is default off and content-free; consent UX is the storefront's | - | - |
| SEO, perceived speed | not applicable | API | - | - |

## Per-axis automatic measurement

`scripts/scorecard.py` (M2.12) reads CI artifacts (`coverage.json`, mutmut report, ruff JSON, mypy output, complexity JSON, Grype and Syft output, golden and full-set reports, oasdiff result, Locust CSV, `ci-profile` test result, Scorecard SARIF, README and link checks) and writes `scorecard.json`: per axis the inputs and a pass or fail per critical criterion of rubrics v2. Nightly and on release; it fails when any ratchet loosens or an axis input regresses against the committed baseline. Judgement axes (P3 narrative quality, Lens 3) are scored per release by an independent evaluator agent that sees only the repo, the evidence and the rubric.

## Ratchets (`ratchets/`, only tighten; loosening needs an ADR and the owner)

| File | Holds | Starting value |
|---|---|---|
| `complexity.json` | `file::function` to complexity for every function above 10 | 19 entries |
| `ruff.json` | findings per rule code | from `audit/ruff-ecosystem-families.txt`, reduced to 0 by M4 |
| `coverage.json` | branch floor, diff floor | 76 (local) then combined value until the M4 exit (2026-12-11); 85 from PVA-M4.12; 90 diff |
| `mutation.json` | score per scoped module | from the M2 baseline |
| `retrieval.json` | recall@3, @5, @10, MRR per family and language | `audit/recall-at-k.txt` |
| `golden.json` | per-item and per-stratum pass state (100%) | set at M2.5 |
| `perf.json` | latency, TTFT, tokens, cost per answer, benchmark timings | from the first live and load runs |
| `image.json` | size, findings by severity | from M1.7 |
| `contracts.json` | operation count, schema hashes | from M3.1 |
| `docs.json` | broken links 0, stale counts 0, README headings | M1 and M3 |
| `ci-duration.json` | p50 and p95 of the last 30 runs | M1 baseline |
| `guards.json` | architecture violations (0) | M2.2 |

## Re-score cadence

Automatic axes nightly and per release. Independent evaluator agent at M3, M6 and every release. Fresh-agent or human re-audit every quarter. Rubric version frozen once the first scored review is recorded.
