# Skills and harness — pequeverso-assistant-api

Applies ecosystem section 15 and `research/08-docs-readme-skills.md` sections 5 to 6. Goal (owner requirement 6): an agent harness good enough that the owner does not review code. Repository AGENTS.md rules win over any user-level skill.

## 1. Audit of the six existing skills

All six are short and procedural (23 to 45 lines each), validated by `scripts/validate_skills.py` and `tests/test_skills.py`, and keep the rule that skills never add authority for paid calls, deployment, cross-repository edits or protected-branch changes (AGENTS.md).

| Skill | Lines | Job | Findings | Action |
|---|---:|---|---|---|
| `api-change-contract` | 26 | change v1 HTTP/SSE or private ops contract without breaking consumers | description has no "Use when" trigger; no oasdiff or expand/contract steps | rewrite description; add oasdiff and `contract-major` steps; M3 |
| `api-change-use-case` | 32 | change prompts, answer rules, evidence or evaluations | two jobs in one (behaviour code and evaluation data); no golden-set step; does not mention the prompt lock | split: keep for rules and evidence, add golden-set and prompt-lock steps; promote evaluation data work to the new skills below |
| `api-maintain-knowledge` | 23 | re-sync catalog from a pinned storefront commit | fine; add the post-sync golden and full-set run and the catalog sha stamp | edit |
| `api-release-and-hotfix` | 45 | develop to main release, authorized hotfix | long inline command list is fragile (match-head-commit, ancestry checks) | move the ancestry and diff checks to `scripts/verify_release.py`; keep the skill as instructions |
| `api-review-dependency-update` | 24 | review one Dependabot PR with the read-only assessment | the assessment is retired (PVA-D9) | replace by `api-review-weekly-dependencies` |
| `api-verify-release` | 23 | verify a release candidate without paid calls | add golden replay, SBOM and attestation verification | edit |

Cross-cutting findings: canonical location is inverted (canonical in `.claude/skills/<name>/`, relative directory symlinks in `.agents/skills/<name>`); target is canonical `.agents/skills/<name>/SKILL.md` with `.claude/skills/<name>` relative symlinks to `../../.agents/skills/<name>` (ecosystem 15.1; Codex, Gemini and Copilot read `.agents/skills`). Frontmatter has `name` and `description` only: add `metadata: {owner, last-reviewed, version}`. Descriptions follow "Does X. Use when ... even if ... Do not use for ..." with the key trigger first and at most 1,024 characters. No activation evals exist.

## 2. New skills (one job each)

| Skill | Job | Guards |
|---|---|---|
| `api-run-golden-set` | run replay, record cassettes, or run the live lane; read the report | live and recording steps start with the authorization check from AGENTS.md (explicit current owner authorization, private key file outside the repo, bounded ledger, never print the key); cassette lane needs none |
| `api-add-golden-item` | turn a failure (owner report, red-team success, full-set failure) into a golden item with schema v2, qrels, assertions and the right stratum | enforces the 60-item stratum counts and the quarantine rule |
| `api-triage-vulnerability` | apply the SLA table to a scanner finding: reachability, fix or ignore with issue and expiry, manual path PR | never opens a second Dependabot PR; no secrets in issues |
| `api-checkpoint-milestone` | at a milestone: confirm green release profile, update `progress.md`, ecosystem table, tag `checkpoint/M<n>` command for the owner-approved push | reads `RESUME.md`; never pushes to `develop` directly |
| `api-review-weekly-dependencies` (replaces the old review skill) | review the single weekly PR: lockfile diff, licence check, SBOM diff, image digest changes, the vulnerability table | merge stays with the owner |

That makes 10 skills; each is under 150 lines with fragile steps in `scripts/`.

## 3. Activation evals (ecosystem 15.1)

Each skill gets `evals/triggers.json` (about 20 queries: 8 to 10 positives, 8 to 10 near-miss negatives, fixed 60/40 train/validation split) and `evals/evals.json` (2 to 3 output evals with assertions, run with and without the skill). Protocol: 3 runs per query on a clean context; a positive passes if triggered in at least half the runs, a negative passes if triggered in fewer than half; precision and recall reported on the validation split only. Gate: a skill change is not merged if validation trigger accuracy drops by more than 10 points or the output delta turns negative. Total bank: 10 skills, about 200 queries and 25 output evals.

Sample bank (near-misses are what make it useful):

| Skill | Positive (should trigger) | Near-miss negative (must not) |
|---|---|---|
| `api-run-golden-set` | "replay the golden set against my prompt change" | "run the unit tests" |
| `api-run-golden-set` | "record cassettes for the new items" (needs authorization check) | "explain what the golden set is" |
| `api-add-golden-item` | "the assistant promised a discount in this run, make it a regression item" | "add a unit test for check_answer" |
| `api-triage-vulnerability` | "Grype flags libsqlite3 HIGH with no fix, what do we do" | "bump FastAPI to the latest" |
| `api-release-and-hotfix` | "promote develop to main" | "merge this task PR into develop" |
| `api-change-contract` | "add a field to the session response" | "rename a private helper" |

Staleness: monthly check on `last-reviewed` (180 days opens an issue); lines that never change agent behaviour are deleted. Output-eval fixtures never contain secrets or real conversations.

## 4. Hooks and permissions (hard rules are not prose)

Proposed `.claude/settings.json` (committed, owner approves the grant): deny reads of `.env*` except `.env.example` and of any `*.env.local` or private key file path; deny shell commands containing `--live` or `run_bounded_real_eval.py --live` unless the session carries the owner's authorization marker; deny `gh pr merge --admin`, `git push` to `develop` or `main`, `git push --force`. The user-level guard hooks (destructive commands, force-push to main or develop, `reset --hard`) already exist and are not worked around. An agent that fails twice at the same thing gets a script, lint rule or hook before more prose.

## 5. Review chain per PR (ecosystem 15.2), repo-specific parts

1. Author agent opens a PR from a task branch with test evidence and the PR template complete.
2. `ci-gate` green: lint, types, architecture, tests, coverage, mutation where scoped, contracts, security, golden replay when the profile applies.
3. Independent reviewer agent (read-only, given the diff and the rubric, not the author's reasoning).
4. Second-model review (Codex via `codex-second-opinion`, advisory; every finding reproduced before acting; if unavailable the Claude reviewer repeats on a different tier and the PR records it).
5. Architecture review agent for structural PRs (the `create_app` split, contract changes, new modules), plus an adversarial second opinion for risky ones.
6. Strongest agents from the start for anything touching auth, migrations, budgets, spend, secrets or the answer policy.
7. Findings fixed or answered in the PR; a missing, partial or failed report is never "no problems".

Repo-specific definition of done additions: a prompt, catalog or answer-rule change carries re-recorded cassettes and a prompt-changelog row; a refactor PR carries before and after mutation scores for the touched module; every behaviour PR states what was verified and what was not (existing AGENTS.md rule).
