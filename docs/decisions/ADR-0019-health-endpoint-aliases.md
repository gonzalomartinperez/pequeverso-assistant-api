# ADR-0019: Health endpoint aliases and the published env schema

Status: accepted (2026-11-21). Master-plan task PVA-M3.3 (the plan named this ADR-0018; that number
went to release tagging in PVA-M1.10), ecosystem deploy contract section 8.5.

## Context and problem statement

The ecosystem deploy contract asks every service for `GET /healthz` (liveness, `{status, version}`)
and `GET /readyz` (readiness with `version` and `schema_version`), plus a published environment
schema that `vps-ops` validates before a deploy. This service has served `/health/live` and
`/health/ready` since v1, and the image `HEALTHCHECK` called `/health/ready`, so a slow database
marked the container unhealthy even though the process was fine.

## Considered options

1. Rename the paths (a breaking change for every probe that exists today).
2. Serve the new paths as aliases next to the old ones (expand now; `vps-ops` moves when ready).

## Decision outcome

Option 2.

- `/healthz` checks nothing and returns `{status: "ok", version}`; `version` is `SERVICE_REVISION`
  (the git SHA baked in at build) or `unknown`.
- `/readyz` runs the same checks as `/health/ready` and returns its body plus `version` and
  `schema_version`. `schema_version` is the highest migration this build needs for its
  configuration: `sqlite-NNN` (SQLite applies its migrations at startup), or `postgres-NNN`, where
  the optional product-analytics migrations count only when analytics is enabled. It is the level
  the build expects. Readiness verifies only part of it: it fails when the database is unreachable
  and, with analytics on, when the analytics markers or checksums are missing. Core PostgreSQL
  migrations (001 to 004) are not re-checked at runtime; they run as the explicit pre-deploy job,
  and `vps-ops` compares this value with the job it ran.
- The image `HEALTHCHECK` moves to `/healthz`: liveness must not depend on the database.
- Neither alias is in the public OpenAPI; all health paths stay internal (the proxy routes only
  `/api/*`). The old paths stay served; removing them is a contract-major change and is not planned.
- `contracts/env.schema.json` is generated from `Settings` by `contracts.export`: name, `secret`
  and `required_in_production`, never a value or a default. The production requirements are the
  ones `Settings.fail_closed` enforces for an answering deployment (assistant enabled, OpenAI
  answers). A `jobs` list names the secrets read only by the explicit migration and import jobs.

### Consequences

- Good: probes follow the ecosystem contract without breaking existing ones; a new setting cannot
  ship without appearing in the published schema.
- Bad: two path families to keep in step (they share one implementation).
- `vps-ops` reads the new paths and the env schema (handoff `docs/handoffs/vps-ops.md`).

## Confirmation

`tests/test_health_aliases.py` checks both path families, the version and schema level, and that the
aliases stay out of OpenAPI. `tests/test_env_schema.py` checks the schema against `Settings` and
`.env.example`, and proves each production requirement by removing it from a valid production
environment. `tests/test_container_layout.py` and the CI `container` job assert the `/healthz`
`HEALTHCHECK`; `scripts/smoke_container.sh` calls all four paths on the built image.
