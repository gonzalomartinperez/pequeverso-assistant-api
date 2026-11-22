# ADR-0011: Layer enforcement with import-linter plus the AST guard

Status: accepted 2026-11-14; enforce mode since 2026-11-22, PVA-M4.7.
`docs/master-plan/standards.md` section 1, `docs/master-plan/testing.md`
section 1 ("Static" row).

## Context and problem statement

`tests/test_architecture.py` originally enforced the layers with a hand-written AST walker: domain and
application import only the standard library, SQL stays in the storage adapters, Cypher and the
Neo4j driver stay in `adapters/neo4j`, LangGraph, LangChain and LangSmith stay in `adapters/graph`, and
the application import graph is acyclic. The walker is strong and has negative fixtures. But it is
custom code, its rules are spread across test functions, and the ecosystem standard asks for
declarative import contracts that report a broken contract by name.

## Considered options

1. Keep only the AST guard.
2. Replace the AST guard with import-linter.
3. Add import-linter contracts beside the AST guard. The guard keeps what import-linter cannot
   express (banned calls, SQL and Cypher text location, relative-import resolution edge cases); the
   layer and SDK-confinement rules move to contracts over time.

## Decision outcome

Option 3. The layer names are kept (`domain`, `application`, `ai`, `adapters`, `presentation`,
`bootstrap`).

- PVA-M2.2 added 10 contracts to `.importlinter`: inward layers; presentation independent of
  concrete adapters and `app.ai`; domain, application and `app.ai` do not import a named list of
  web, database, model and telemetry SDKs. The standard-library allowlist stays in the AST test. SDK
  confinement for PostgreSQL, Neo4j, the graph stack, the OpenAI provider, telemetry and SQLite
  (keeping the reviewed exceptions); and independence between seven adapter capabilities. The
  independence contract is stricter than the AST guard (which lets adapters import each other); it
  holds today, and a future legitimate cross-adapter import needs an explicit contract change.
- In parallel ("warn") mode, `lint-imports` ran as a required check in `just check` and the CI
  static job alongside the existing AST guard.
- In the same task, `ratchets/complexity.json` records the 19 functions above McCabe 10.
  `scripts/complexity_ratchet.py` fails when a function is new above 10, when a value rises, or when
  a value drops without the file being tightened (also checked against the base revision in CI).
  `vulture` (`[tool.vulture]`, minimum confidence 80, `ratchets/vulture-whitelist.py`) runs with a
  whitelist of verified false positives. At that confidence it mostly reports unused arguments and
  imports (unused functions score 60), so it is a narrow net next to ruff's `ARG` and `F401`; the
  threshold is lowered when the whitelist is curated further.

### Enforce mode (PVA-M4.7)

Deliberate deviation from the roadmap wording ("AST test reduced to banned calls and SQL and
Cypher location"): the per-layer third-party allowlist also stays in the AST test. Import-linter only
expresses denylists, so a domain module importing an unlisted package (for example `yaml`) passes every
contract; removing the allowlist would loosen a guard (architecture review, 2026-11-22).

- Import-linter is authoritative for layer direction and SDK confinement with an empty baseline.
  The sqlite contract now treats its allowed importers as exact modules (`as_packages = False`):
  `app.adapters.sqlite` and its descendants, plus the single module
  `app.adapters.postgres.import_sqlite`; a descendant of `import_sqlite` is no longer allowed. The
  eleventh contract checks sibling cycles throughout `app`, including `app.application`.
- The AST guard keeps the per-layer third-party allowlists, SQL and Cypher text placement, and
  module classification. Banned calls (the wall clock outside bootstrap) stay in
  `tests/test_logging_streams.py`. It also covers imports of root modules outside the declared layers, cycles
  through package initializers, and SDK path checks where a module file and a package initializer
  can share an import name.

### Consequences

- Good: a broken layer rule is reported by contract name, and new adapters inherit the rules
  declaratively.
- Cost: the AST guard is still needed to inspect SQL and Cypher strings and the import edge cases
  listed above.

## Confirmation

`tests/test_import_contracts.py` checks that all 11 contracts pass on the real tree and that the
baseline is empty. Isolated negative fixtures break each contract by name. A graph coverage check
ensures every Python source file under `app` is visible to Grimp.
`tests/test_architecture.py` and `tests/test_architecture_coverage.py` exercise the remaining AST
checks. `tests/test_complexity_ratchet.py` covers the ratchet.
