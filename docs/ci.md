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
| checks | checks | all five above | Every prerequisite must be success |

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

## Verification and protected context

Run the focused checks, then the normal repository quality commands:

```sh
uv run pytest -q tests/test_ci_profile.py tests/test_dependabot_policy.py tests/test_container_layout.py
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
