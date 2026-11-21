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

Coverage (`ratchets/coverage.json`, `scripts/coverage_gate.py`): the static CI job measures branch coverage, enforces `static_branch_floor` and requires 90% of the changed executable lines to be executed (diff coverage against the base revision); the database job combines its data with the static job's and enforces `branch_floor`. Floors only rise (`--write-floor`); locally run `uv run pytest -n auto --cov --cov-report=term` and `uv run coverage json` then `uv run python -m scripts.coverage_gate coverage.json --base origin/develop --floor static_branch_floor`.

Load harness: run `uv run python -m tests.load.sse_load --report /tmp/sse-load.json` locally (defaults: 12 visitors, 900 seconds). It launches an isolated fixture uvicorn subprocess with four generation slots, raised rate limits and zero synthetic token prices; no keys or paid calls are used. It asserts TTFE p95 < 1.5 s, event-gap p95 < 500 ms, errors and premature closes each < 0.5%, and RSS growth < 20% for runs of at least 600 seconds. Backpressure rejections (`busy`, four generation slots against twelve visitors) are reported separately as `rejected_rate`: informational, because the API rejects rather than queues beyond its slots; latency is measured on admitted runs. The nightly workflow (PVA-M2.12) runs it for 15 minutes. Use `--duration 30` for a short run; opt into the 10-second subprocess test with `PVA_LOAD_SMOKE=1 uv run pytest tests/test_sse_load_harness.py`.

Scorecard: `scripts/scorecard.py` turns measured inputs (static ratchets, coverage, golden replay, load, mutation, retrieval) into `scorecard.json` per rubric axis and fails when a metric is worse than its committed baseline in `ratchets/`. The `nightly` workflow runs it after the full suite, Hypothesis at 1000 examples, the golden replay and a 15-minute load run; it also runs on every push to `develop` (scheduled runs read workflows from `main`). Baselines only tighten.

`just fmt` formats and applies safe lint fixes; `just test` and `just unit` run the full or the unit-only suite. CI runs the same commands; a PR merges only when the required check is green (`checks` today, becoming `ci-gate` with PVA-M1.4). Image changes also run `scripts/smoke_container.sh`.

## Contract gate

`contracts/openapi.json` is generated (`uv run python -m contracts.export`). On every pull request CI runs `oasdiff breaking --fail-on ERR` between the base revision and the head (`scripts/contract_breaking.sh`); a breaking change fails unless the owner adds the PR label `contract-major` (v1 stays backward compatible, so use it only for a deliberate major step). Schemathesis checks the spec against the in-process fixture app, including three stateful flows declared as OpenAPI links (session to post message, cancel run, delete session): `uv run pytest tests/test_schemathesis_contract.py`. It runs 50 examples per operation; set `SCHEMATHESIS_MAX_EXAMPLES=500` for the nightly depth. A failure prints a `curl` reproduction. The run is slow on small hosts (a few minutes).

## Property-based tests

Hypothesis defaults to the deterministic `ci` profile (100 examples); `nightly` runs 1000 examples:

```bash
HYPOTHESIS_PROFILE=nightly uv run pytest -q tests/test_properties_*.py
```

Add a shrunk failure as an `@example` regression case before fixing the bug. The local
Hypothesis example database (`.hypothesis/`) is ignored by Git.

## Mutation testing

Mutmut 3.8 runs the scoped unit selection in `pyproject.toml` with explicit `fork` isolation
(on CPython 3.14). Run one module with
`timeout --kill-after=10s 30m uv run mutmut run --max-children 2 'app.domain.budget.*'`, then
`uv run python -m scripts.mutation_ratchet --changed app/domain/budget.py`.
The ratchet reads ignored `mutants/**/*.py.meta` JSON files. Scores count
killed / (killed + survived + timeout + suspicious). Exit 33 (no tests) counts as survived;
skipped (34), no-test (5) and type-check-only (37) results are excluded but reported.
Unchecked mutants (never run or interrupted: exit code null or 2) are not scored; a required
module with any unchecked mutant is an incomplete run and fails, and `--write` refuses to record
while any measured module has unchecked mutants. Equivalent mutants need individual reasons in
`ratchets/mutation.json` and remain in the raw score. Reduce scope before lowering a threshold.

Modes (`--mode {pr,full}`, default `pr`):

- `pr`: required modules are the changed scoped modules that have mutants; the floor is
  `max(pr_break 60, recorded score)`. Unchanged modules are ignored.
- `full`: every scoped module with mutants is required; the floor is its recorded score (0 if
  none) and the weekly target (75%) is printed. With an empty baseline it prints a
  `::notice::` and does not fail for that reason (it still fails on unchecked or missing results).
- Modules with zero mutants (no functions, `__init__.py`) are skipped; `--select` never emits
  patterns for them.

Changed paths come from `--changed PATH...` (local) or `--changed-file PATH` (NUL- or
newline-separated, as written by `git diff -z --name-only`; never word-split). `--select
--shard I/N` prints the full-scope patterns of shard I of N (round-robin by sorted path), and
`--prune-meta --shard I/N` deletes the `.meta` files of modules outside the shard so shard
artifacts merge as a plain union.

CI (`.github/workflows/mutation.yml`): a `classify` job picks the lane. `pr` mutates only the
changed scoped modules (30-minute budget). `full` runs 4 shards (85 minutes each, artifacts
`mutation-shard-1..4`), then an aggregate job runs `--mode full` over the merged metadata and
uploads it as `mutation-results-full`. The full lane runs weekly, on manual dispatch, on pushes
to `develop` that touch the scope, and on PRs that change the workflow or the ratchet script.

Recording the baseline: download the `mutation-results-full` artifact of a complete full run into
a directory, then run
`uv run python -m scripts.mutation_ratchet --mode full --results <dir> --write` and commit
`ratchets/mutation.json`. `--write` only raises values.

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
