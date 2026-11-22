# CI profile

[CI](../../.github/workflows/ci.yml) runs on pull requests into `develop` or `main`
(opened, synchronized, reopened, labeled, unlabeled, edited or marked ready for review), pushes to
either branch, merge groups and manual dispatch. New PR runs cancel older runs on the same ref.

## Profiles

The pinned `classify` workflow reads [the live profile map](../../.github/ci-profile.json) and
combines the jobs from every profile matched by the PR's changed paths, branch and labels.
Pushes, merge groups and dispatches run all profiles. An unreadable or empty diff, an unmatched
path or an edit to the map also runs all profiles. A missing or invalid map fails classification.

| Profile | Matching paths or conditions | Jobs added |
| --- | --- | --- |
| `docs` | Markdown, `docs/**`, `LICENSE`, Markdown lint config and blame-ignore revisions | `docs`, `secrets` |
| `code` | Application, tests, scripts, evals, tools, catalog, migrations, ratchets, monitoring, agent skills and hooks, root config and lockfiles | `static`, `secrets`, `security` |
| `contract` | `contracts/**` | `static`, `secrets`, `security` |
| `assistant-quality` | AI, answer policy, claims, language, redaction, chat and catalog code, catalog data, eval fixtures and evaluation code | `static`, `secrets`, `security` |
| `container` | App code, Docker inputs, project and lock files, catalog, migrations, smoke probes and image lint/scan configuration | `static`, `container`, `database`, `secrets`, `security` |
| `database` | App code, real-store and graph tests, migrations, database Dockerfiles, smoke scripts and Python project/lock files | `static`, `database` |
| `workflow` | `.github/**` | `workflows`, `security`, `static`, `secrets`, `container`, `database` |
| `deps-weekly` | Head matches `dependabot/**` or PR has label `deps-weekly` | All profiles |
| `release` | `develop` into `main` or PR has label `release` | All profiles |

Only paths that match the `docs` profile exclusively take the docs fast path.
For example, `README.md` also matches `code`. Every `app/**` change selects
`container` and `database`, as does the `workflow` profile.

## CI jobs

| Job | Prerequisites | What it checks | Local equivalent or closest check |
| --- | --- | --- | --- |
| `classify` | CI event | Selects the profile and emits the job list using the PR file list from GitHub. | `uv run pytest -q tests/test_ci_profile.py` |
| `docs` | Selected by `classify` | Shared markdownlint-cli2 and offline Lychee links with fragments. Lychee excludes dated evidence under `docs/verification`. The README template check is disabled. | `markdownlint-cli2 '**/*.md'` and `lychee --offline --no-progress --include-fragments --exclude-path docs/verification './**/*.md'` |
| `security` | Selected by `classify` | Shared zizmor and actionlint. On PRs, dependency review checks vulnerabilities and the license allowlist, including the [ADR-0015 exceptions](../decisions/ADR-0015-dependency-licence-exceptions.md). The caller disables shared gitleaks. | `zizmor .github/workflows/` and `actionlint`. Dependency review uses the GitHub PR comparison. |
| `workflows` | Selected by `classify` | Workflow validation with actionlint and zizmor. | `actionlint -pyflakes=""` and `zizmor --min-severity low .github/workflows/` |
| `secrets` | Selected by `classify` | Redacted gitleaks scan with the repository config and ignores. Needs full Git history and fails if it scans no commits. | `.github/scripts/secret-scan.sh` with Docker and a full checkout. |
| `static` | Selected by `classify` | Frozen dependencies, lint and type checks, ratchets, PR contract compatibility, fixture and contract tests, coverage, contract export and evaluation replays. | `uv sync --frozen` and `just check`. Additional CI checks are listed below. |
| `database` | Selected by `classify`, successful `static` | Builds the project's PostgreSQL and Neo4j candidates. Checks roles, indexing and rollback, private state, logging, restore, session and HTTP/SSE behavior, operator jobs and evaluations. Combines database and static branch coverage and checks the combined floor. | See the [local database probes](#local-database-probes). |
| `container` | Selected by `classify`, successful `static` | Builds the application candidate, exercises a disposable SQLite fixture and checks image structure, security and reproducibility. | `docker build -f infra/docker/app/Dockerfile -t pequeverso-assistant-api:smoke .` and `scripts/smoke_container.sh pequeverso-assistant-api:smoke`. See image gates below. |
| `ci-gate` | All jobs above, runs even when they fail or skip | Requires `classify` and every selected job to succeed. Skips pass for unselected jobs. | `uv run pytest -q tests/test_ci_profile.py` exercises profile selection and gate outcomes. |
| `checks` | `ci-gate`, runs even when it fails or skips | Succeeds exactly when `ci-gate` succeeds. This is the current protected context. | The same CI profile tests pin the alias. |

The owner applies the ruleset that requires `ci-gate` before the temporary `checks` alias and its
test are removed (PVA-D11). Merges require green hosted checks for the reviewed revision.

### Static checks

| Area | Workflow behavior and local command |
| --- | --- |
| Lint and types | `just check` runs Ruff, import-linter, Vulture and strict Mypy along with the local ratchets and tests. CI also reports Pyrefly findings without failing the job: strict Mypy (0 errors) is the type gate, and Pyrefly 1.4.1 reports 82 errors on the same tree, mostly inference differences on untyped third-party returns (decision PVA-M4.10, revisited at M6). |
| Ratchets and prompt lock | `uv run python -m scripts.ruff_ratchet`, `uv run python -m scripts.prompt_lock` and `uv run python -m scripts.complexity_ratchet`. CI passes `--base=FETCH_HEAD` after fetching the event base and checks the current tree if the base is unavailable. |
| Contract and skills | `uv run python -m contracts.export --check` and `uv run python -m scripts.validate_skills`. On PRs, `scripts/contract_breaking.sh <base-ref> <oasdiff-path>` checks compatibility. The `contract-major` label permits breaking changes. |
| Analytics fixture | CI uses the fleet Node pin in `.nvmrc` to run `node --test tests/js/product-analytics-pointer.test.mts` (Node type stripping, no `package.json`) offline without a browser. The non-blocking `compat` workflow runs the same test on Node 26, and the static job's test selection on Python 3.15 (production stays on `.python-version`; ecosystem 8.1 adopts 3.15 around 3.15.3); the pin moves after two weeks of green runs there (OD-77, DR-10). |
| Branch coverage | `uv run pytest -q -n auto --cov --cov-report= -m "not schemathesis"`, then `uv run coverage json -q -o coverage-static.json` and `uv run python -m scripts.coverage_gate coverage-static.json --floor static_branch_floor --base <base-ref>`. CI also uploads the coverage data for `database`. Manual dispatch and new branch events without a base check the floor only. |
| Schemathesis | `uv run pytest -q -m schemathesis tests/test_schemathesis_contract.py` runs separately from branch coverage. |
| Fixture evaluations | `uv run python scripts/evaluate_retrieval.py`, `uv run python scripts/evaluate_conversations.py`, `uv run python -m evals.runner golden --replay` and `uv run python -m evals.runner red-team --replay`. Pytest includes the generated evaluation table check, also available as `uv run python -m scripts.docs_numbers --check`. |

### Local database probes

Run from the repository root with an isolated Docker environment and the frozen service-test
dependencies (`uv sync --frozen --no-build`). The workflow runs the last probe under coverage
and combines its data with the static job's artifact.

```sh
docker build --build-arg SERVICE_REVISION="$(git rev-parse HEAD)" -f infra/docker/postgres/Dockerfile -t pv-knowledge-pg:ci .
docker build -f infra/docker/neo4j/Dockerfile -t pv-knowledge-neo:ci .
pg_image=$(docker image inspect --format '{{.Id}}' pv-knowledge-pg:ci)
neo_image=$(docker image inspect --format '{{.Id}}' pv-knowledge-neo:ci)
probe_dir=$(mktemp -d)
scripts/smoke_knowledge_postgres.sh "$pg_image" "$probe_dir/knowledge-postgres"
uv run python -m scripts.smoke_knowledge_neo4j --image "$neo_image" \
  --receipt "$probe_dir/knowledge-neo4j" --private-dir "$probe_dir/knowledge-private"
uv run python -m scripts.smoke_graph_runtime --postgres-image "$pg_image" --neo4j-image "$neo_image" \
  --receipt-dir "$probe_dir/knowledge-http" --source-dir "$PWD" --with-index-jobs --with-evaluation-tests
```

## Test lanes and parallelism

| Local command | Lane |
| --- | --- |
| `uv run pytest -m unit -n auto` | Unit tests without external services. |
| `uv run pytest -n auto` | Full suite. Tests marked `services` skip without their explicitly isolated fixtures. |
| `uv run pytest --randomly-seed=<seed>` | Reproduce the seed printed by pytest-randomly. Static CI uses pytest-xdist and pytest-randomly. Database smoke scripts use fixed order via `-p no:randomly` for tests sharing a store. |

## Image gates

| Check | Workflow rule |
| --- | --- |
| Dockerfile and runtime | Hadolint fails on warnings using `.hadolint.yaml`. The smoke checks readiness, session/stream behavior, origin/auth enforcement, backup/restore, persistence and shutdown. |
| Image structure | `container-structure-test test --image pequeverso-assistant-api:smoke --config infra/docker/app/structure-test.yaml` checks user, workdir, labels, command, absence of pip, `/data` ownership and LICENSE. Docker inspect checks the healthcheck. |
| Dockle | WARN or FATAL fails. CIS-DI-0008 and DKL-DI-0005 are accepted for the pinned base image. Dockle and container-structure-test release downloads are SHA-256 verified. |
| SBOM and vulnerabilities | Syft emits the `sbom-app-cyclonedx` artifact. Grype uses `.grype.yaml` and fails on fixable High or Critical findings. The [vulnerability SLA](../decisions/ADR-0016-weekly-dependency-pr-and-vulnerability-sla.md) and `tests/test_container_layout.py` cover tracking and expiry of ignores. |
| Reproducibility | BuildKit uses the last commit's `SOURCE_DATE_EPOCH` and `rewrite-timestamp=true` for repeated OCI builds. `python3 -m scripts.compare_oci_images <first-archive> <second-archive>` compares manifest digests. |

## Other workflows

These workflows run separately from `ci-gate`. Scheduled runs use the workflow on the default
branch, `develop`. All local commands run from the repository root.

| Workflow and jobs | Triggers | What it checks or does | Local equivalent or closest check |
| --- | --- | --- | --- |
| [nightly](../../.github/workflows/nightly.yml) · `nightly`, `schemathesis` | Daily 04:00 Buenos Aires time, pushes to `develop`, PRs into `develop` touching the workflow or `scripts/scorecard.py`, and dispatch. | Branch coverage, nightly Hypothesis profile, golden replay and fixture SSE load feed the scorecard and its regression gates. A separate job runs the extended Schemathesis suite. | `HYPOTHESIS_PROFILE=nightly uv run pytest -q -n auto -p no:randomly tests/test_properties_*.py`. Run `uv run python -m tests.load.sse_load` and `uv run python -m scripts.scorecard` with the workflow's load settings and coverage, golden and load reports. Use the Schemathesis command above with the workflow's `SCHEMATHESIS_MAX_EXAMPLES`. |
| [mutation](../../.github/workflows/mutation.yml) · `classify`, `mutation-pr`, `mutation-shard`, `mutation-full` | PRs into `develop`, pushes to `develop` matching the workflow path filter, Sundays at 05:00 Buenos Aires time, and dispatch. | PRs normally gate changed scoped modules through mutmut and the mutation ratchet. Changes outside scope skip mutation. Edits requiring the full lane and non-PR events run the sharded scope and gate the merged metadata. | `uv run python -m scripts.mutation_ratchet --select --changed-file=<nul-separated-paths>` selects the changed scope. Pass those patterns to `uv run mutmut run`, then use `uv run python -m scripts.mutation_ratchet --mode pr --changed-file=<nul-separated-paths>`. For the full scope run `uv run mutmut run` and `uv run python -m scripts.mutation_ratchet --mode full`. |
| [deps-weekly-guard](../../.github/workflows/deps-weekly-guard.yml) · `guard` | Mondays at 10:30 Buenos Aires time, Dependabot PR opened/reopened/synchronized, and dispatch. | Closes older duplicate `weekly-all` PRs. Schedule and dispatch record the survivor's status in the tracker and update `needs-fix` based on `checks`. | `uv run pytest -q tests/test_dependabot_config.py` validates configuration. See the [weekly review procedure](../how-to/dependency-updates.md) for GitHub CLI inspection. |
| [vuln-daily](../../.github/workflows/vuln-daily.yml) · `vuln` | Daily 07:00 Buenos Aires time and dispatch with optional `force-summary`. | Recursive OSV scan and compromised-action watch update the pinned tracker. Findings are advisory. Missing or invalid OSV output fails the scan. Monday or a forced summary posts a comment. This caller supplies no deployed image digests. | `osv-scanner scan source --recursive .` reproduces the dependency scan. Tracker updates and the shared action watch run in GitHub. |
| [scorecard](../../.github/workflows/scorecard.yml) · `analysis` | Mondays at 09:00 UTC, pushes to `main`, and dispatch. | Runs OpenSSF Scorecard, publishes results and uploads SARIF to GitHub code scanning. | `scorecard --repo=github.com/gonzalomartinperez/pequeverso-assistant-api --format=sarif` runs the analysis. Publication and upload run in GitHub Actions. |
| [drift](../../.github/workflows/drift.yml) · `drift` | PRs, Mondays at 09:00 Buenos Aires time, and dispatch. | Checks standards-managed files against `standards.lock` and the locked engineering-standards revision. | `just drift <engineering-standards-checkout>` with the revision in `standards.lock`. |
| [release](../../.github/workflows/release.yml) · `release` | Pushes to `main`. | Publishes `vX.Y.Z` at the pushed SHA using the version in `pyproject.toml` and its dated CHANGELOG section. An existing release or tag is left alone. A fresh tag requires release notes. Promotion is owner-controlled under [ADR-0018](../decisions/ADR-0018-release-tagging-without-release-please.md). | `python3 -m scripts.release_notes --github-output /tmp/pva-release-output --notes /tmp/pva-release-notes.md` validates and extracts the local inputs. `uv run pytest -q tests/test_release.py` checks the workflow contract. |

## Trust and provenance

Actions and reusable workflows are pinned by SHA. Workflow-level token permissions default to
empty and individual jobs request their scopes. The weekly guard uses the GitHub API without
checking out or running PR code. Scorecard writes security events and requests an identity token.
The release job uses `contents: write` for tag and release creation. Vulnerability reporting
writes to the tracker. These workflows use no `pull_request_target` trigger.

`scripts/ci_identity.py` binds the checked-out revision to the run and records reviewed configuration
hashes and selected image IDs. It rejects a different revision or modified tracked inputs. CI
uses the fixture provider with paid AI and LangSmith tracing disabled. The uv cache is for
dependencies. Real-store and container probes own disposable services on their runners. The
database job receives static coverage data, and image gates upload an SBOM. Candidate images,
raw logs, conversation evidence and backups stay off the artifact handoff. The workflows have
no image publication or deployment step.
