# Dependency updates and conservative auto-merge

## Current state (2026-09-27)

| Control | State |
|---|---|
| Dependabot version updates (`.github/dependabot.yml`) | uv (weekly), GitHub Actions (weekly, grouped), Docker base images (monthly). All target `develop` |
| Dependabot alerts and security updates | **Enabled** (repository settings). Security PRs target the default branch, which is `develop`; cooldowns do not delay them |
| Policy workflow (`dependabot-policy.yml`) | Evaluates every Dependabot PR and records the decision in the job summary |
| Native auto-merge | **Off, fail-closed.** This is a private repository on GitHub Free: branch protection and rulesets are unavailable (API 403), so required checks cannot be enforced and auto-merge would not be gated. The workflow enables auto-merge only when the base branch reports protection. Repository setting `allow_auto_merge` is off |

**To activate unattended merges (owner decision):**
1. Upgrade to a plan with protected branches for private repositories (GitHub Pro or Team). The
   repository's visibility is not ours to change.
2. Protect `develop`: require the `checks` status and `Dependabot policy / Evaluate eligibility`,
   require branches to be up to date (strict), no bypass.
3. Enable "Allow auto-merge".

The workflow is already deployed on `develop`, so nothing else changes. Until then, eligible PRs
are labelled by the summary as eligible, and a maintainer merges them after CI passes.

## Eligibility policy (`scripts/dependabot_policy.py`, `.github/dependabot-policy.json`)

A PR is eligible only if **all** of these hold (authenticated API data at the evaluated head;
titles, labels and branch names are never inputs):

- Author is the Dependabot app (login `dependabot[bot]`, type `Bot`, id 49699333). The head is
  in this repository (not a fork). The base is `develop`. The PR is open, not draft, and its
  head equals the SHA the run was started for.
- Every commit is authored by Dependabot and GitHub-verified. Any human commit forces manual
  review.
- Only `pyproject.toml` and `uv.lock` are modified (nothing added, removed or renamed).
- `pyproject.toml` differs only in dependency version specifiers (a parsed TOML comparison).
  Scripts, tool settings, new dependencies or group moves force manual review.
- Every package whose locked version changes (direct or transitive) qualifies:
  - **patch** for allowlisted packages: fastapi, uvicorn, httpx, pydantic-settings, low-risk
    transitive helpers, pytest, ruff, mypy and their helpers;
  - **minor** only for dev tools: pytest, ruff, mypy and helpers. They are not in the image
    (`--no-dev`), and a regression shows up as a CI failure.
- Mergeable state is not `dirty` or `unknown`, and the required check `checks` did not fail or
  get cancelled. Pending is fine: native auto-merge waits for required checks.

**Always manual:**
- major, prerelease, downgrade and unknown version schemes;
- 0.x minor bumps (FastAPI, uvicorn, httpx, ruff are 0.x);
- `openai` (provider SDK, only fake-client tested);
- `starlette` (sessions, cookies, SSE);
- `pydantic` / `pydantic-core` (validation boundary);
- the TLS stack (`httpcore*`, `truststore`, `certifi`) and `python-dotenv` (config loading);
- GitHub Actions and Docker base images;
- mixed groups; lockfile-only changes without a version change.

Security updates follow the same rules: they get prompt human attention when not eligible, and
are never auto-qualified because they are security updates.

## Re-evaluation and rebasing

- The policy runs on `opened`, `reopened`, `synchronize` (new commits or rebases), `edited`
  (for example a base change) and `ready_for_review`. The newest run cancels older ones. An
  ineligible result turns off any auto-merge left on the PR. Auto-merge is bound to the
  evaluated head with `--match-head-commit`, so a later commit cannot inherit it.
- The workflow never approves: no approval rule exists today, and bot approval would not
  replace a future human-review requirement. If one is added, fully unattended merges stop
  until the owner decides.
- `rebase-strategy: auto`: Dependabot rebases its PRs when `develop` moves or they conflict,
  which triggers CI and the policy again. Dependabot stops rebasing a PR that someone else has
  edited, and very old PRs may need `@dependabot rebase` or `@dependabot recreate`. There is no
  custom rebase bot.

## Operating

| Need | Action |
|---|---|
| Pause all automation | Set `open-pull-requests-limit: 0` in `.github/dependabot.yml` (PR), or disable the workflow in Actions settings |
| Force manual review on one PR | Push any commit or comment `@dependabot ignore`. A human commit makes the PR ineligible, and auto-merge is disabled on the next run |
| Tighten or widen the allowlist | Edit `.github/dependabot-policy.json` in a PR with a test in `tests/test_dependabot_policy.py` |
| Recover from a bad merged update | Open a normal PR on `develop` that reverts the lockfile change (`git revert <sha>`) or pins the previous version, then `@dependabot ignore this patch version` |

## Workflow security

- `pull_request_target` runs the base commit's policy with a sparse checkout (two files) and
  `persist-credentials: false`. The PR's code, dependencies and scripts are never checked
  out, installed or run.
- The `decide` job is read-only (`contents`, `pull-requests`, `checks`: read). Only `apply` gets
  `contents` and `pull-requests: write`, and it runs `gh` with fixed arguments and values from
  environment variables. No PAT, no secrets, no deployment credentials. Actions are pinned by SHA.
- CI (`quality.yml`) runs on the PR's own `pull_request` event with a read-only token and no
  secrets, as GitHub does for Dependabot.

## Live verification (2026-09-27)

- After the config reached `develop` (`c0f842e`), Dependabot's first run opened PR #3
  (`build(docker): Bump astral-sh/uv from 0.12.10 to 0.12.19`, head `5c776f8`). The uv and
  Actions ecosystems had no updates.
- The `Dependabot policy` workflow ran on `pull_request_target` (run 36336971467). Identity checks
  passed; the decision was `eligible: false`, reason "unexpected files changed: Dockerfile".
  Auto-merge stayed off (`autoMergeRequest: null`). `Quality` also ran on the PR with
  Dependabot's read-only token and passed.
- PR #3 is left open for human review (base-image change). If merged, also bump `UV_VERSION` in
  `quality.yml` to keep CI and the image on the same uv.
- **Not yet observed live:** an *eligible* uv patch PR (none was available) and the
  enable-auto-merge path (impossible until branch protection exists).
