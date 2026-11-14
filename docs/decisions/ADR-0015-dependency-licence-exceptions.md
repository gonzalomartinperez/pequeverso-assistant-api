# ADR-0015: Licence exceptions for psycopg (LGPL-3.0) and hypothesis (MPL-2.0)

Status: accepted (2026-11-14). Master-plan task PVA-M1.11, decision PVA-D15 (resolved by delegation, 2026-11-09).

## Context and problem statement

The ecosystem dependency policy allows permissive licences (MIT, BSD, Apache-2.0, ISC, PSF and
similar) by default; any copyleft licence needs a recorded exception. Two dependencies need one:

- `psycopg` (with the `binary` and `pool` extras), `psycopg-binary` and `psycopg-pool`
  (LGPL-3.0): the PostgreSQL 18 driver and pool used by `app/adapters/postgres` at runtime
  (ADR-0009). `psycopg-binary` bundles `libpq` and its dependencies, which carry their own
  permissive licences (PostgreSQL licence, OpenSSL and others).
- `hypothesis` (MPL-2.0): property-based testing planned for the development group
  (master plan `testing.md`; planned for M2, not yet in `uv.lock`), never installed in the
  runtime image.

## Considered options

1. Accept both as recorded exceptions.
2. Replace psycopg with asyncpg (Apache-2.0) and skip property-based tests.

## Decision outcome

Option 1.

- psycopg is used unmodified, as a dynamically imported library, from the public PyPI wheels,
  and a user of the image can replace it. Our reading is that this use is compatible with
  LGPL-3.0 provided the licence texts travel with the library; this is an engineering
  assessment, not legal advice (a lawyer review before M7 is already recommended, DR-07).
  Switching to asyncpg (Apache-2.0) would rewrite the six adapter modules built on psycopg's
  `AsyncConnectionPool` and `sql` composition for no product gain.
- hypothesis is a development-only tool. MPL-2.0 is file-level copyleft; we never modify its
  files and never distribute it (it is not in the image). Hand-written examples
  cannot cover the input spaces the property tests target.

### Consequences

- Good: no driver rewrite; property-based testing becomes available in M2.
- Bad: two non-permissive licences in the dependency tree need a check on every update.
- Any modification of psycopg or hypothesis sources, static linking, or a move of hypothesis into
  the runtime group voids this exception and needs a new ADR.

## Confirmation

- Planned, not yet enforced: the licence check of the `deps-weekly` CI profile (master plan
  `ci-cd.md`, profile table) allows exactly these package names with these licences and fails on
  any other copyleft licence.
- The built image keeps the psycopg distribution licence files: the container structure test
  (PVA-M1.7) or the SBOM review of the weekly PR confirms them under `/opt/venv`.
- `pyproject.toml` keeps `hypothesis` (when added) in the `dev` dependency group only, and the
  runtime image is built with `--no-dev`.
