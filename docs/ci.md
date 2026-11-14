# CI profile

`Quality` validates PRs into develop/main (including target edits), pushes to both
branches, merge groups and manual runs. The paired API graph is:

| Job | Check name | Depends on | Required work |
| --- | --- | --- | --- |
| workflows | Workflow validation | — | actionlint and zizmor |
| secrets | Secret scan | — | Full-history redacted gitleaks |
| static | Static checks | — | Frozen install, Ruff, strict Mypy, pinned Node24.22.0 local fixture regression (10s, no browser/network), full pytest, contract drift, retrieval and fixture conversation evaluations |
| database | Database tests | static | Own exact PostgreSQL/Neo4j builds; scoped roles, indexing, private state, restore, actual HTTP/SSE and operator/evaluation probes |
| container | Container verification | static | Hadolint, own application build and disposable SQLite fixture (readiness, session/stream, origin/auth enforcement, backup/restore, persistence, shutdown), container-structure-test, dockle, CycloneDX SBOM artifact, Grype and a twice-built reproducibility check |
| checks | checks | all five above | Every prerequisite must be success |

The source baseline is `0422c74aa25644978122232bcaae08fdf8c32310`. Its reported
1143 offline passes and 40 service-dependent skips are historical inventory, not
acceptance of this increment. Static still runs the complete suite; service skips
are not service passes. The database job retains the real store and fixture HTTP/SSE
commands, including cold indexing/operator jobs and evaluation tests. No runtime,
Docker recipe, dependency lock or catalog changes accompanied that CI migration.

## Test lanes and parallelism

`tests/conftest.py` marks every test `unit` (no external service) or `services` (gated by
`skipif` on an explicitly isolated PostgreSQL or Neo4j fixture). The `static` job runs the whole
suite in parallel with `pytest-xdist` (`-n auto`) and in random order with `pytest-randomly`
(the seed is printed in the header; reproduce with `--randomly-seed=<seed>`, disable with
`-p no:randomly`). The `database` job keeps a fixed order: its three smoke scripts pass
`-p no:randomly` to pytest because their tests share one isolated store per run
(`tests/test_ci_profile.py` pins both settings).

```sh
uv run pytest -m unit -n auto      # fast local lane
uv run pytest -n auto              # full suite; service tests skip without fixtures
```

## Trust and provenance

All jobs use read-only or empty token permissions and SHA-pinned actions. The
`deps-weekly-guard.yml` workflow is a thin caller of the shared reusable workflow in
`engineering-standards`, pinned by SHA, with `permissions: {}` at the top. It uses the GitHub
API only: no PR code is checked out or executed, and no workflow uses `pull_request_target`
(`tests/test_dependabot_config.py` pins this). The owner merges the weekly PR manually.
Caches contain dependencies only; uv uses the runtime and lockfile inputs. No images, raw logs,
conversation evidence or backups are
uploaded. Database and container jobs own separate disposable services; neither
assumes another runner's database survives.

`scripts/ci_identity.py` logs only source/base/workflow SHA, run/attempt, platform,
reviewed configuration hashes and explicitly selected local image IDs. It rejects
another checked-out revision or modified tracked inputs. Images stay on their own
runner, with no registry publication, archive handoff or deployment. This is source
preparation, not acceptance or adoption of candidate images.

Reference: Portfolio API `923f5d32215203d6a09efd2ef1dec8e49225d4e5` and the private
Ops paired-profile contract at `19dcbee`. Product-specific probes remain owned here;
Portfolio runtime/harness code is not imported.

## Image gates

The `container` job lints `infra/docker/app/Dockerfile` (`.hadolint.yaml`, warnings fail), runs
the smoke, then checks the built image: `infra/docker/app/structure-test.yaml` (user, workdir,
labels, command, no pip, `/data` ownership, LICENSE), dockle CIS-DI (WARN or FATAL fail;
CIS-DI-0008 and DKL-DI-0005 are accepted because both come from the pinned base), a Syft CycloneDX SBOM
uploaded as `sbom-app-cyclonedx` (14 days) and Grype with `.grype.yaml` (only fixable High or
Critical fail; each ignore carries a tracking issue and an expiry enforced by a test). Reproducibility builds twice with `SOURCE_DATE_EPOCH` from the last
commit and BuildKit `rewrite-timestamp=true`, then compares the OCI manifest digests. dockle and
container-structure-test are SHA-256 verified release binaries; the other tools are SHA-pinned
actions. Nothing is published.

## Verification and protected context

Run the focused checks, then the normal repository quality commands:

```sh
uv run pytest -q tests/test_ci_profile.py tests/test_dependabot_config.py tests/test_container_layout.py
```

The CI profile tests exercise the actual aggregate shell with green,
failed, skipped, cancelled, pending, empty and missing results; they also protect
job identities, dependencies, events, trust boundaries and substantive commands.
Real database/container validation requires the hosted workflow or an explicitly
authorized isolated service lease. CPU-only tests do not prove those checks.

The protected context remains `checks`, now the display name of the real aggregate job
`checks`. Its five dependencies, `always()` condition and five exact-success assertions
are unchanged. The temporary seventh compatibility job has been removed with explicit
owner authorization. No manual status, ruleset change or bypass is involved: all five
substantive jobs still have to succeed before the protected context passes.

The shared profile has six job IDs and the same dependency graph as the paired API
standard. Portfolio's `Required checks` display name is a project compatibility difference;
Pequeverso retains `checks` to satisfy its existing protected context directly. Display-name
parity never authorizes protection changes. Exact-head hosted checks remain required before
an authorized merge; source validation does not authorize deployment or activation.
