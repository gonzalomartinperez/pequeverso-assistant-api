# Engineering standards

These standards apply to this API and its coordination with the storefront and backoffice.
Repository-specific `AGENTS.md`, contracts and approval rules remain authoritative. Skills
provide procedures, never additional authorization.

## Review and scope

Ship a finite improvement with evidence. Separate security/correctness findings from optional
polish; review the actual changed code, tests and failure paths. This adapts Google's
[code-review standard](https://google.github.io/eng-practices/review/reviewer/standard.html),
which prioritizes improving code health, and Microsoft's
[engineering checklist](https://microsoft.github.io/code-with-engineering-playbook/engineering-fundamentals-checklist/)
and [reviewer guidance](https://microsoft.github.io/code-with-engineering-playbook/code-reviews/process-guidance/reviewer-guidance/).
Those references inform our process; they are not claims of certification or a substitute for
this repository's rules.

An independent reviewer checks behavior and architectural boundaries before a relevant merge.
State whether that review was by an agent or a person. Tests and citations are evidence with
limits: a fixture completion does not establish real-model correctness, usefulness or conversion.
Preserve original failed runs and label revalidation after changes. Do not remove assertions,
raise budgets/deadlines, bypass protections or conceal retries to get a green result.

## Four-session ownership

For coordinated work across the three applications, declare ownership before editing:

| Session role | Owns | Coordinates |
| --- | --- | --- |
| Coordinator | Integration plan, acceptance evidence and authorized release decisions | Contract freezes, reviews, shared locks and service leases |
| Storefront engineer | Own branch/worktree, interface, public copy and consumer contract pin | Producer schema revision and production-disabled build |
| API engineer | Own branch/worktree, producer contract, domain/application and adapters | Compatible exports, catalog provenance and backend evidence |
| Backoffice engineer | Own branch/worktree, auth/dashboard and its database artifacts | Private operations contract and telemetry semantics |

Each path and lockfile has one owner at a time. Use separate worktrees under the designated
workspace; announce a frozen commit before another session tests or pins it. State who owns
ports, containers and generated outputs. Do not reset, stash, prune, stop or overwrite another
session's work, services or browser caches. Resolve shared contract changes explicitly; consumers
copy artifacts from committed producer revisions rather than a mutable working tree.

## Architecture and typing

Keep dependency direction inward. Domain and application use standard-library data and ports;
HTTP/SDK/database objects stay outside. [Architecture](architecture.md) records the actual
boundaries and lifecycle. Use the existing strict mypy and Ruff configuration. Do not introduce
`Any`, casts, ignores or new framework layers merely to hide a dependency error.

External Pydantic schemas legitimately reject malformed catalog input before mapping it to domain
values. File and HTTP sources share that parser. Keep those acceptance rules intact; introducing a
second parser would require parity tests and a deliberate decision about shared domain invariants.
No mass movement of models or new abstraction framework is required by these standards.

## Reproducibility, support and CI

- `uv sync --frozen` installs the reviewed dependency graph. `uv.lock`, pinned tool versions and
  Dockerfile image digests are authoritative; do not silently refresh locks during verification.
- Prefer an officially supported LTS line where that project publishes one. Python is a maintained
  stable release without an LTS label; PostgreSQL has a major-version support policy. Do not label
  every tool, library, container or Grafana release LTS. See [runtime baseline](runtime-baseline.md)
  and [dependency updates](dependency-updates.md) for selected versions, exceptions and reviews.
- A container tag is not an immutable artifact. Pin the reviewed digest, rebuild the exact source
  SHA, record its image identity and smoke health/readiness, non-root/read-only behavior,
  persistence and shutdown. Keep vulnerability findings visible; no local scan or build alone
  establishes production readiness.
- Every relevant PR must pass the required current-head checks: Ruff lint/format, strict typing,
  full pytest, contract checks, secret/workflow checks and the configured container smoke. Add
  deterministic regressions for real defects; use fakes or isolated services for external failures.
- Treat browser inventory, skips, retries and flaky outcomes separately from the workflow's green
  badge. Inspect requested screenshots. Publish only reviewed evidence without secrets or private
  conversations. Report measured timings and distinguish fixtures from the real provider.

Feature PRs target `develop` and use squash in this API. An authorized `develop` → `main` release
uses a protected merge commit and green required checks. Never push directly to protected branches,
use `--admin`, alter rulesets or infer deployment/activation permission from a passing CI run.
The backoffice's merge policy remains governed by its own repository.

## Secrets, operations and handoff

Provider credentials stay exclusively in the backend's private configuration. No real key,
provider request, paid evaluation or budget increase is authorized by these standards. Tests use
fixtures and fake SDK clients; production activation and VPS deployment require their separate
owner-controlled gates.

Application owners supply immutable images, health/readiness, bounded shutdown, persistent-path
and secret requirements. vps-ops owns deployment, the reverse proxy, Coolify and shared monitoring.
A rollback must preserve newer conversations and accounting; do not restore an old database over
newer ledger writes. See [deployment contract](deployment-contract.md) for the catalog/history
compatibility gate and the operations handoff. Unknown usage or availability must remain unknown,
not be rendered as a fabricated zero or success.
