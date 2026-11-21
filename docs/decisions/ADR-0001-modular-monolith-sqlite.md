# ADR-0001: Modular monolith on SQLite, single process

Status: accepted (2026-09-27); partly superseded by ADR-0009 (production storage)

**Context.** One product, low traffic, a USD 10/month model budget, and deployment on a shared VPS
managed by vps-ops/Coolify. We need sessions (24 h), messages, idempotent runs, an atomic budget
ledger and rate counters.

**Decision.** FastAPI modular monolith with hexagonal layers. State lives in one SQLite file (WAL)
on a volume, accessed from one dedicated thread. Writes use `BEGIN IMMEDIATE`. Migrations are
numbered SQL applied at startup. The service runs as a single uvicorn worker, with the active-run
registry and concurrency slot in memory.

**Consequences.** Nothing to provision beyond a volume, backup is one online `.backup`, and
budget races are serialized even across processes (tested). There is no horizontal scaling:
replicas would need a shared store and a cross-process cancel channel, which is a new ADR. The
reference project's Postgres, Neo4j and LangGraph stack was not needed.

## Confirmation

The layer and SQL boundaries are enforced by `tests/test_architecture.py`
(`test_layers_depend_inwards_only`, `test_sql_stays_in_storage_adapters`) and by the
`.importlinter` contracts `layers` and `stdlib`, run by `uv run lint-imports` in the CI `static`
job. `tests/test_budget_concurrency.py` covers the serialized budget ledger
(`test_reservations_are_atomic_across_processes`,
`test_persistent_ledger_uses_full_wal_sync_and_survives_reopen`). The image starts one uvicorn
worker (`--workers 1` in `infra/docker/app/Dockerfile`), checked by the CI `container` job smoke
(`scripts/smoke_container.sh`). The single dedicated SQLite thread and `BEGIN IMMEDIATE` writes
(`app/adapters/sqlite/database.py`) have no dedicated test; they are covered indirectly by the
concurrency tests above and by review. Since ADR-0009, the production storage part of this decision
is confirmed by the PostgreSQL checks listed there; this ADR now describes the SQLite fixture
profile and the historical baseline.
