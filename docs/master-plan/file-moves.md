# File moves, renames, conversions and deletions

Source of truth is `file-index.csv` (412 tracked files at develop `6912579`). This file lists every path that changes location, format or existence, with the motive. Edits in place (`edit`, `rewrite`) are in the index only. Every move is a `git mv` in a PR of its own scope; every inbound link is fixed in the same PR and checked by lychee. No move changes a frozen, hash-bound evidence file.

## 1. Moves, conversions, merges and deletions (tracked files)

| From | To | Action | Motive | Milestone |
|---|---|---|---|---|
| `.claude/skills/api-review-dependency-update/SKILL.md` | `.agents/skills/api-review-weekly-dependencies/SKILL.md` | rewrite | review of the single weekly PR; renamed because the eligibility assessment is retired (PVA-D9) | M1 |
| `.github/workflows/dependency-policy.yml` | `.github/workflows/deps-weekly-guard.yml` | rewrite | pull_request_target policy workflow removed; replaced by the shared weekly guard (no PR-head trust) | M1 |
| `.github/workflows/quality.yml` | `.github/workflows/ci.yml` | rewrite | one ci.yml: classify job, shared reusable workflows, ci-gate (renamed from checks via ruleset script), profiles per ecosystem 6.0 | M1 |
| `app/ai/prompt.py` | `app/ai/prompt.py (+ app/ai/prompt.lock.json)` | edit | formalize PROMPT_VERSION: content hash lock, bump test, prompt changelog (assistant-quality.md section 9) | M2 |
| `docs/ci.md` | `docs/reference/ci.md` | rewrite | describes the five-job aggregate named checks; rewrite for profiles and ci-gate | M3 |
| `docs/dependency-updates.md` | `docs/how-to/dependency-updates.md` | rewrite | describes the retired classifier; rewrite for the weekly single PR and the vulnerability SLA | M3 |
| `docs/evaluation.md` | `docs/reference/evaluation.md` | rewrite | counts are stale (23 retrieval, 24 conversation, 22 guard cases vs 20/19/14 stated); numbers generated from reports (no volatile facts) | M3 |
| `tests/test_architecture.py` | `tests/test_architecture.py (+ .importlinter)` | edit | layer and third-party rules move to import-linter contracts; AST keeps banned-call and SQL/Cypher location rules; negative fixtures kept | M2 |
| `.agents/skills/api-change-contract` | `.claude/skills/api-change-contract` | move | symlink direction inverted with the canonical move | M1 |
| `.agents/skills/api-change-use-case` | `.claude/skills/api-change-use-case` | move | symlink direction inverted with the canonical move | M1 |
| `.agents/skills/api-maintain-knowledge` | `.claude/skills/api-maintain-knowledge` | move | symlink direction inverted with the canonical move | M1 |
| `.agents/skills/api-release-and-hotfix` | `.claude/skills/api-release-and-hotfix` | move | symlink direction inverted with the canonical move | M1 |
| `.agents/skills/api-review-dependency-update` | `.claude/skills/api-review-weekly-dependencies` | move | symlink follows the renamed skill | M1 |
| `.agents/skills/api-verify-release` | `.claude/skills/api-verify-release` | move | symlink direction inverted with the canonical move | M1 |
| `.claude/skills/api-change-contract/SKILL.md` | `.agents/skills/api-change-contract/SKILL.md` | move | ecosystem 15.1: canonical in .agents/skills, relative symlink from .claude/skills (currently inverted) | M1 |
| `.claude/skills/api-change-use-case/SKILL.md` | `.agents/skills/api-change-use-case/SKILL.md` | move | ecosystem 15.1: canonical in .agents/skills, relative symlink from .claude/skills (currently inverted) | M1 |
| `.claude/skills/api-maintain-knowledge/SKILL.md` | `.agents/skills/api-maintain-knowledge/SKILL.md` | move | ecosystem 15.1: canonical in .agents/skills, relative symlink from .claude/skills (currently inverted) | M1 |
| `.claude/skills/api-release-and-hotfix/SKILL.md` | `.agents/skills/api-release-and-hotfix/SKILL.md` | move | ecosystem 15.1: canonical in .agents/skills, relative symlink from .claude/skills (currently inverted) | M1 |
| `.claude/skills/api-verify-release/SKILL.md` | `.agents/skills/api-verify-release/SKILL.md` | move | ecosystem 15.1: canonical in .agents/skills, relative symlink from .claude/skills (currently inverted) | M1 |
| `.github/dependabot-policy.json` | `-` | delete | allowlist for the retired classifier | M1 |
| `app/application/chat.py` | `app/application/chat.py (+chat_steps.py)` | split | start (29) and events (17) become named steps behind characterisation tests and golden cassettes; no behaviour change | M4 |
| `app/bootstrap/container.py` | `app/bootstrap/container.py (+wiring.py, lifespan.py, routes.py)` | split | create_app has cyclomatic complexity 36; split into wiring, lifespan and route installation, each <= 10 (PVA-D4) | M4 |
| `docs/agent-skills.md` | `docs/reference/agent-skills.md` | move | Diataxis (ecosystem 14.2); inbound links fixed in the same PR and checked by lychee | M3 |
| `docs/api-contract.md` | `docs/reference/api-contract.md` | move | Diataxis (ecosystem 14.2); inbound links fixed in the same PR and checked by lychee | M3 |
| `docs/architecture.md` | `docs/explanation/architecture.md` | move | Diataxis (ecosystem 14.2); inbound links fixed in the same PR and checked by lychee | M3 |
| `docs/business-questions.md` | `docs/explanation/business-questions.md` | move | open owner questions with defaults; owner-only decisions list links here | M3 |
| `docs/catalog.md` | `docs/reference/catalog.md` | move | Diataxis (ecosystem 14.2); inbound links fixed in the same PR and checked by lychee | M3 |
| `docs/deployment-contract.md` | `docs/reference/deployment-contract.md` | move | Diataxis (ecosystem 14.2); inbound links fixed in the same PR and checked by lychee | M3 |
| `docs/engineering-standards.md` | `CONTRIBUTING.md` | merge | review standard and four-session ownership fold into CONTRIBUTING.md and AGENTS.md; ecosystem.md is the standard; file deleted after merge | M1 |
| `docs/execution-plan.md` | `docs/archive/execution-plan-2026-09.md` | move | historical status table; superseded by docs/master-plan/roadmap.md | M3 |
| `docs/graph-retrieval.md` | `docs/explanation/graph-retrieval.md` | move | Diataxis (ecosystem 14.2); inbound links fixed in the same PR and checked by lychee | M3 |
| `docs/handoffs/backoffice.md` | `docs/reference/handoffs/backoffice.md` | move | cross-repo contract handoff; reference | M3 |
| `docs/handoffs/storefront-transition.md` | `docs/reference/handoffs/storefront-transition.md` | move | cross-repo contract handoff; reference | M3 |
| `docs/handoffs/vps-ops.md` | `docs/reference/handoffs/vps-ops.md` | move | 195-line handoff; trim volatile measurements in the move PR; reference | M3 |
| `docs/knowledge-operations.md` | `docs/how-to/knowledge-operations.md` | move | Diataxis (ecosystem 14.2); inbound links fixed in the same PR and checked by lychee | M3 |
| `docs/observability/README.md` | `docs/reference/observability.md` | move | one file does not need a folder | M3 |
| `docs/official-web-evidence.md` | `docs/explanation/official-web-evidence.md` | move | Diataxis (ecosystem 14.2); inbound links fixed in the same PR and checked by lychee | M3 |
| `docs/product-analytics.md` | `docs/reference/product-analytics.md` | move | Diataxis (ecosystem 14.2); inbound links fixed in the same PR and checked by lychee | M3 |
| `docs/reference-adoption.md` | `docs/explanation/reference-adoption.md` | move | provenance record of ideas adapted from portfolio-assistant-api (licence evidence); keep | M3 |
| `docs/runtime-baseline.md` | `docs/reference/runtime-baseline.md` | move | Diataxis (ecosystem 14.2); inbound links fixed in the same PR and checked by lychee | M3 |
| `docs/security.md` | `docs/explanation/security.md` | move | Diataxis (ecosystem 14.2); inbound links fixed in the same PR and checked by lychee | M3 |
| `evals/conversations.json` | `evals/archive/conversations.json` | move | 24 live scenarios: best ones promoted to golden items, file retired after promotion | M2 |
| `evals/guards.json` | `evals/red-team/guards.json` | move | 22 scripted misbehaving outputs become the seed of the PR red-team pack (target 40-60) | M2 |
| `evals/reports/corpus-fixture.json` | `evals/full/baseline/corpus-fixture.json` | move | becomes the committed baseline report (ratchet input), regenerated by the full-set job | M2 |
| `evals/retrieval.json` | `evals/retrieval/retrieval-smoke.json` | move | 23-case smoke becomes qrels for ranx; docs claimed 20 cases (stale) | M2 |
| `scripts/dependabot_policy.py` | `-` | delete | read-only eligibility classifier is moot under one weekly PR merged manually by the owner (PVA-D9) | M1 |
| `tests/fixtures/product-analytics-pointer.test.cjs` | `tests/js/product-analytics-pointer.test.mts` | convert | ecosystem 10.1: no .cjs; Node type stripping runs .mts; reformat the 28 dense lines | M4 |
| `tests/fixtures/product-analytics.html` | `tests/js/fixtures/product-analytics.html` | move | sits beside the only test that reads it | M4 |
| `tests/test_dependabot_policy.py` | `-` | delete | policy script is retired with the single weekly PR rule (PVA-D9); replaced by tests/test_dependabot_config.py | M1 |
| `tests/test_prompt_post32.py` | `tests/test_prompt_contract.py` | move | rename: the file name encodes a past incident id, not behaviour; add prompt hash lock test | M2 |
| `evals/corpus/<family>.json` (18 files) | `evals/full/<family>.jsonl` | convert | full set v2: JSONL schema v2, qrels audited, weak families extended; ids, groups and splits preserved so history stays comparable | M2 |

Deleted without replacement: `.github/dependabot-policy.json`, `scripts/dependabot_policy.py`, `tests/test_dependabot_policy.py` (retired classifier, PVA-D9). `.github/workflows/dependency-policy.yml` is replaced by `deps-weekly-guard.yml`.

## 2. Not moved on purpose

| Path | Reason |
|---|---|
| `evals/end_to_end*.json` (4 files), `evals/knowledge/*.json` | frozen manifests bound by SHA-256 in `docs/verification/` records; moving or editing them breaks provenance |
| `docs/verification/**` (41 files, 5.6 MB) | dated evidence, immutable history, never relabelled |
| `docs/decisions/ADR-000N-*.md` | ADR paths stay stable (ecosystem 14.2); new ADRs continue the pattern `ADR-00NN-title.md` (deviation from the fleet `NNNN-title.md`, recorded in `docs/decisions/README.md`) |
| `app/**`, `contracts/**`, `migrations/**`, `catalog/**` | flat `app/` layout kept (PVA-D2); contracts and catalog are generated |
| `infra/docker/**` | same paths; contents edited |

## 3. Files added by the plan (not tracked yet)

| Path | Purpose | Milestone |
|---|---|---|
| `docs/master-plan/**` | this plan (README, scorecard, audit, target-state, assistant-quality, testing, ci-cd, standards, docs-and-community, skills, dependencies, roadmap, progress, RESUME, sources, ecosystem, rubrics, file-index.csv, file-moves.md, ci-profile.json, research/, audit/) | M0 |
| `.github/workflows/ci.yml, nightly.yml, deps-weekly-guard.yml, security.yml, release.yml` | profiles, nightly and weekly jobs, release | M1 |
| `.github/ci-profile.json` | path map (draft in the plan) | M1 |
| `.github/CODEOWNERS, ISSUE_TEMPLATE/{bug,feature}.yml, ISSUE_TEMPLATE/config.yml, PULL_REQUEST_TEMPLATE.md` | community and review scaffolding | M1 |
| `CONTRIBUTING.md, SECURITY.md, SUPPORT.md, CODE_OF_CONDUCT.md` | community files | M1 |
| `justfile, .hadolint.yaml, .grype.yaml, release-please-config.json, .release-please-manifest.json, .git-blame-ignore-revs, .importlinter` | single check command and tool configuration | M1-M2 |
| `.claude/settings.json` | permission denies for keys, live flags, admin merges (owner approves) | M1 |
| `.agents/skills/{api-run-golden-set,api-add-golden-item,api-triage-vulnerability,api-checkpoint-milestone,api-review-weekly-dependencies}/` | new skills, each with evals/triggers.json and evals/evals.json | M1-M3 |
| `evals/golden/golden.jsonl, evals/golden/cassettes/**, evals/golden/README.md` | golden set v1 and cassettes | M2 |
| `evals/graders.py, evals/cassette.py, evals/runner.py, evals/__init__.py` | shared graders, record and replay at the provider port, runner | M2 |
| `evals/full/<family>.jsonl, evals/full/baseline/` | full set v2 and committed baseline report and run | M2 |
| `evals/red-team/` | attack pack (seed: guards.json) | M2 |
| `evals/judge/<criterion>.v1.md, evals/judge/labels/` | judge rubrics and owner labels | M2, M6 |
| `evals/reports/<date>-<sha>-<lane>.json` | committed summaries of live runs (no transcripts) | M3 |
| `ratchets/*.json` | ratchet baselines (scorecard.md) | M2 |
| `scripts/scorecard.py, scripts/verify_release.py` | scorecard aggregation, release ancestry checks moved out of the skill | M2, M1 |
| `app/ai/prompt.lock.json` | prompt content hash lock | M2 |
| `app/bootstrap/{wiring,lifespan,routes}.py, app/application/chat_steps.py` | decomposition targets | M4 |
| `contracts/openapi.internal.json` | health, ops, analytics read operations | M3 |
| `docs/{tutorials,how-to,reference,explanation}/**, docs/reference/{prompt-changelog,dependency-health}.md, docs/how-to/run-evaluations.md, docs/tutorials/first-conversation.md` | Diátaxis docs | M3 |
| `docs/decisions/ADR-0010..0019` | new ADRs (target-state.md section 8) | M1-M4 |
| `tests/test_dependabot_config.py, tests/test_prompt_contract.py (renamed), tests/test_security_matrix.py, tests/test_properties_*.py, tests/test_sse_conformance.py, tests/test_faults.py, tests/load/locustfile.py` | new tests by testing.md | M1-M2 |
| `tests/js/product-analytics-pointer.test.mts` | converted from .cjs | M4 |
