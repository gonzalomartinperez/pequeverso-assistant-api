# CI profile

`Quality` validates PRs into develop/main (including target edits), pushes to both
branches, merge groups and manual runs. The paired API graph is:

| Job | Check name | Depends on | Required work |
| --- | --- | --- | --- |
| workflows | Workflow validation | — | actionlint and zizmor |
| secrets | Secret scan | — | Full-history redacted gitleaks |
| static | Static checks | — | Frozen install, Ruff, strict Mypy, full pytest, contract drift, retrieval and fixture conversation evaluations |
| database | Database tests | static | Own exact PostgreSQL/Neo4j builds; scoped roles, indexing, private state, restore, actual HTTP/SSE and operator/evaluation probes |
| container | Container verification | static | Own application build and disposable SQLite fixture; readiness, session/stream, origin/auth enforcement, backup/restore, persistence and shutdown |
| checks | Required checks | all five above | Every prerequisite must be success |

The source baseline is `0422c74aa25644978122232bcaae08fdf8c32310`. Its reported
1143 offline passes and 40 service-dependent skips are historical inventory, not
acceptance of this increment. Static still runs the complete suite; service skips
are not service passes. The database job retains the real store and fixture HTTP/SSE
commands, including cold indexing/operator jobs and evaluation tests. No runtime,
Docker recipe, dependency lock or catalog changes accompany this CI migration.

## Trust and provenance

All jobs use read-only or empty token permissions and SHA-pinned actions. The
renamed `dependency-policy.yml` / `Dependency policy` continues its trusted-base,
read-only assessment: manual review/merge remains required. It never executes PR
code with write privileges. Caches contain dependencies only; uv uses the runtime
and lockfile inputs. No images, raw logs, conversation evidence or backups are
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

## Verification and protection transition

Run the focused checks, then the normal repository quality commands:

```sh
uv run pytest -q tests/test_ci_profile.py tests/test_dependabot_policy.py tests/test_container_layout.py
```

The CI profile tests exercise the actual aggregate shell with green,
failed, skipped, cancelled, pending, empty and missing results; they also protect
job identities, dependencies, events, trust boundaries and substantive commands.
Real database/container validation requires the hosted workflow or an explicitly
authorized isolated service lease. CPU-only tests do not prove those checks.

The owner must first observe the exact new `Required checks` context from GitHub
Actions on a green candidate, add it alongside existing required `checks`, verify
enforcement, and only then remove the old context. No settings change, bypass,
merge or production action is performed by this source increment. Paired parity
and release acceptance remain pending exact-head remote runs and that transition.
