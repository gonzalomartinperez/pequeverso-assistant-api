# ADR-0001: Modular monolith on SQLite, single process

Status: accepted (2026-09-27)

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
