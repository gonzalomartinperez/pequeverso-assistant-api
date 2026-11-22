# ADR-0021: Visitor memory port and runtime feature flags

Status: accepted (2026-11-22). Master-plan task PVA-M4-X, `docs/master-plan/assistant-experience.md`
sections 6 and 7.5. Memory ships disabled until the DR-07 legal review.

## Context and problem statement

Assistant v2 plans optional visitor memory (a few enumerated preferences after an explicit opt-in)
and several runtime flags (`memory`, `blocks_v2`, `progress_events`, `early_blocks`, `web_access`,
`semantic_cache`, `model_router`). PVA-M2-X wrote red isolation tests against a stub port.

M4 needs the real port and an adapter, so that those tests turn green and later slices (graph
nodes, a PostgreSQL adapter, the backoffice) build on a stable contract. Nothing may become
visible to visitors yet.

## Considered options

1. A synchronous port with an in-memory adapter only.
2. An async port shaped for a PostgreSQL adapter (retention job, forget audit), with an in-memory
   adapter now. Flags as an immutable snapshot supplied by a `Flags` port.
3. Defer the port to the wiring slice.

## Decision outcome

Option 2.

- `MemoryStore` (`app/application/memory_ports.py`) is async, like every other I/O port. Its methods
  are `write`, `read`, `forget`, `purge_expired(now)` (the retention job, tested with the `Clock`
  port) and `rows_for`. `rows_for` is a required forget-completeness audit hook: every row keyed
  by the visitor must count.
- The fact schema is closed. Enumerated keys take enumerated values (`verbosity`, `audience_role`,
  `child_age_band`), and anything else is refused. No free text, names, contact data or precise ages
  are stored. Memory never changes a commercial fact or the answer-rule allowlists.
- Expiry is fixed at 60 days per fact, from that fact's own last write. Reads never extend it, and a
  later write of another key does not extend an older fact. The PostgreSQL adapter must use the
  same rule.
- `VisitorKey` marks the server-issued key from the opt-in cookie. It never comes from a request
  body or model output. Persisting adapters key rows by an HMAC of it.
- `FeatureFlags` is the immutable per-run snapshot, with every flag off by default. The `Flags` port
  returns it (`current()`), so one run sees one consistent set even when a later DB-backed adapter
  changes flags without a redeploy. `StaticFlags` returns the all-off default.
  `web_official_help` stays the existing `OFFICIAL_HELP_ENABLED` setting (ADR-0008).
- Nothing is wired into the running service in M4: no route, setting or contract changes.

### Consequences

- Good: the M2-X isolation properties run against a real adapter, and the PostgreSQL adapter and the
  graph wiring inherit an async contract. Flag reads are consistent within a run.
- Open (before memory can be enabled): where the consent record lives (timestamp, policy version,
  withdrawal). Forget must delete it too, so it needs its own port or an extension of this one.
  The DR-07 review and the consent copy approval are owner gates.

## Confirmation

- `tests/test_memory_isolation_contract.py` runs every property against `InMemoryMemoryStore`:
  - cross-visitor isolation, consent off, forget completeness and counts;
  - forget for one visitor leaving others untouched;
  - fixed TTL, per-fact expiry, the retention job, closed schema, empty-key refusal.
  It also proves each property fails against the non-isolating stub.
- `tests/test_feature_flags.py` pins the flag set, the all-off default and the snapshot port.
- The `adapters` independence contract in `.importlinter` lists `app.adapters.memory`.
