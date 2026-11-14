# Contributing

Thanks for helping. This file is short on purpose: run the checks, follow the branch flow, write a Conventional Commit. Agents also read [AGENTS.md](AGENTS.md), which stays authoritative for the non-negotiable rules (advisory and read-only, fixture mode by default, grounding enforced in code, versioned contract). Skills and these standards give procedures, never extra authorization. The skill catalog and its validator are described in [docs/agent-skills.md](docs/agent-skills.md).

## Run the checks

```bash
uv sync --locked   # install the reviewed dependency graph
just check         # the single local command; mirrors CI
```

`just check` is exactly:

```bash
uv run ruff check . && uv run ruff format --check . && uv run python -m scripts.ruff_ratchet && uv run lint-imports && uv run python -m scripts.complexity_ratchet && uv run vulture && uv run mypy && uv run pytest -n auto && uv run python -m contracts.export --check
```

Ruff enforces the ecosystem rule families (`pyproject.toml`). Findings that predate them live in `ratchets/ruff-legacy.toml` (per-file ignores) and `ratchets/ruff.json` (counts per file and code); `scripts/ruff_ratchet.py` fails on any new finding and on any legacy entry that no longer occurs. After fixing legacy findings, run `uv run python -m scripts.ruff_ratchet --write` to shrink both files; it never adds entries. Run `git config blame.ignoreRevsFile .git-blame-ignore-revs` once so `git blame` skips the mechanical reformat.

Import contracts (`.importlinter`) must pass and run in parallel with the AST architecture tests, which stay the authority until PVA-M4.7 (ADR-0011). The complexity ratchet (`ratchets/complexity.json`) rejects new or increased C901 findings above ten; after a reduction, run `uv run python -m scripts.complexity_ratchet --write` to tighten it. Vulture scans application, contract and script code at 80% confidence (mostly unused arguments and imports); add only verified false positives to `ratchets/vulture-whitelist.py`, with a reason for each entry. Preserve suspected dead code for review with `# TODO(PVA-M2.2): candidate dead code, verify`.

`just fmt` formats and applies safe lint fixes; `just test` and `just unit` run the full or the unit-only suite. CI runs the same commands; a PR merges only when the required check is green (`checks` today, becoming `ci-gate` with PVA-M1.4). Image changes also run `scripts/smoke_container.sh`.

## Property-based tests

Hypothesis defaults to the deterministic `ci` profile (100 examples); `nightly` runs 1000 examples:

```bash
HYPOTHESIS_PROFILE=nightly uv run pytest -q tests/test_properties_*.py
```

Add a shrunk failure as an `@example` regression case before fixing the bug. The local
Hypothesis example database (`.hypothesis/`) is ignored by Git.

## Branch flow

- Branch from `develop` as `feat/…`, `fix/…`, `chore/…`, `docs/…` or `deps/…` (`type/kebab-case`) and open the PR with `--base develop`. `main` receives releases only (promotion at M7, a merge commit).
- A hotfix goes to `main` only with the owner's explicit authorization given in the current conversation for that specific fix; see `.agents/skills/api-release-and-hotfix/SKILL.md`.
- Merge as a merge commit, never squash, never `--admin`, never by changing branch protection: `gh pr checks <n> --watch && gh pr merge <n> --merge --delete-branch` (never chain with `;`). Never push to protected branches or infer deployment permission from a passing CI run.
- Keep branches short-lived and PRs focused on one concern.

## Commit and PR convention

- PR titles follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`, `ci:`); the commits on the branch land on `develop` unchanged (merge commit), so every commit message is a Conventional Commit too.
- Fill in the PR template. The PR body states what was verified and what was not.
- Dependency updates arrive in one weekly Dependabot PR that the owner merges; see [docs/dependency-updates.md](docs/dependency-updates.md).

## Review and scope

Ship a finite improvement with evidence. Separate security and correctness findings from optional polish, and review the actual changed code, tests and failure paths. This adapts Google's [code-review standard](https://google.github.io/eng-practices/review/reviewer/standard.html) (improve code health) and Microsoft's [engineering checklist](https://microsoft.github.io/code-with-engineering-playbook/engineering-fundamentals-checklist/); they inform the process and are not claims of certification.

Review chain before a relevant merge: an independent reviewer agent checks behavior and architectural boundaries, and a second-model review gives an advisory read. State whether each review was by an agent or a person. Reproduce every finding before acting on it. Tests and citations are evidence with limits: a fixture completion does not establish real-model correctness, usefulness or conversion. Preserve original failed runs and label revalidation after changes. Never remove assertions, raise budgets or deadlines, bypass protections or conceal retries to get a green result.

Prompt changes (from M2): re-record the cassettes, keep the golden set green and add a row to the prompt changelog. The prompt text is never the only place a guarantee lives.

Coordinated work across the storefront, this API and the backoffice: each path and lockfile has one owner at a time, work happens in separate worktrees, a frozen commit is announced before another session pins it, and nobody resets, stashes, prunes or overwrites another session's work. Consumers copy contract artifacts from committed producer revisions.

## Architecture and typing

Dependency direction points inward. Domain and application use only the standard library and ports; HTTP, SDK and database objects stay outside (`tests/test_architecture.py`, [docs/architecture.md](docs/architecture.md)). Use the existing strict mypy and Ruff configuration; do not add `Any`, casts, ignores or new framework layers to hide a dependency error. External Pydantic schemas reject malformed catalog input before it maps to domain values; file and HTTP sources share that parser, so a second parser needs parity tests and a deliberate decision. Wire models live in `app/presentation/{schemas,events}.py`; regenerate `contracts/` with `uv run python -m contracts.export` and keep v1 backward compatible.

## Reproducibility, support and CI

- `uv sync --locked` installs the reviewed graph. `uv.lock`, pinned tool versions and image digests in `infra/docker/<service>/Dockerfile` are authoritative; do not silently refresh locks during verification.
- Prefer an officially supported LTS line where the project publishes one; do not label every tool or image LTS. See [docs/runtime-baseline.md](docs/runtime-baseline.md) and [docs/dependency-updates.md](docs/dependency-updates.md).
- A container tag is not an immutable artifact: pin the reviewed digest, rebuild the exact source SHA, record its identity and smoke health/readiness, non-root and read-only behavior, persistence and shutdown. Keep vulnerability findings visible; no local scan or build alone establishes production readiness.
- Every relevant PR passes the required current-head checks (Ruff, strict typing, full pytest, contract checks, secret and workflow checks, container smoke; see [docs/ci.md](docs/ci.md)). Add deterministic regressions for real defects; use fakes or isolated services for external failures.
- Treat skips, retries and flaky outcomes separately from the green badge. Inspect requested screenshots. Report measured timings and distinguish fixtures from the real provider. Publish only reviewed evidence, without secrets or private conversations.

## Secrets, operations and handoff

Provider credentials stay in the backend's private configuration. Never commit secrets, `.env*` files, customer data or real conversations (this repository is public). Tests use fixtures and fake SDK clients; no real key, paid evaluation, budget increase or `--live` run happens without the owner's current authorization. Application owners supply immutable images, health/readiness, bounded shutdown and persistent-path and secret requirements; `vps-ops` owns deployment, the reverse proxy, Coolify and shared monitoring; the backoffice's merge policy is governed by its own repository. A rollback must preserve newer conversations and accounting (never restore an old database over newer ledger writes); see [docs/deployment-contract.md](docs/deployment-contract.md). Unknown usage or availability stays unknown, never a fabricated zero or success.

## Reporting security issues

See [SECURITY.md](SECURITY.md). Never open a public issue for a vulnerability. For help, see [SUPPORT.md](SUPPORT.md).
