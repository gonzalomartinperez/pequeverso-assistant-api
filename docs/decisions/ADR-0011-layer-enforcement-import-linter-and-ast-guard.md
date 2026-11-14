# ADR-0011: Layer enforcement with import-linter plus the AST guard

Status: accepted (2026-11-14). Master-plan task PVA-M2.2 (warn mode); enforce mode with an empty
baseline is PVA-M4.7. `docs/master-plan/standards.md` section 1, `docs/master-plan/testing.md`
section 1 ("Static" row).

## Context and problem statement

`tests/test_architecture.py` enforces the layers with a hand-written AST walker: domain and
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

- `.importlinter` holds 10 contracts: inward layers; presentation independent of concrete adapters
  and `app.ai`; domain, application and `app.ai` do not import a named list of web, database, model
  and telemetry SDKs (a denylist: the "standard library only" allowlist stays in the AST test); SDK
  confinement for PostgreSQL, Neo4j, the graph stack, the OpenAI provider, telemetry and SQLite
  (keeping the reviewed exceptions); and independence between seven adapter capabilities. The
  independence contract is stricter than the AST guard (which lets adapters import each other); it
  holds today, and a future legitimate cross-adapter import needs an explicit contract change.
- Parallel ("warn") mode until PVA-M4.7: `lint-imports` runs in `just check` and in the CI static
  job and must pass, but it is not yet the authority; `tests/test_architecture.py` stays the
  authoritative guard and no existing guard test was removed. PVA-M4.7 moves the layer and
  confinement rules to the contracts and reduces the AST test to what contracts cannot express.
- In the same task, `ratchets/complexity.json` records the 19 functions above McCabe 10.
  `scripts/complexity_ratchet.py` fails when a function is new above 10, when a value rises, or when
  a value drops without the file being tightened (also checked against the base revision in CI).
  `vulture` (`[tool.vulture]`, minimum confidence 80, `ratchets/vulture-whitelist.py`) runs with a
  whitelist of verified false positives. At that confidence it mostly reports unused arguments and
  imports (unused functions score 60), so it is a narrow net next to ruff's `ARG` and `F401`; the
  threshold is lowered when the whitelist is curated further.

### Consequences

- Good: a broken layer rule is reported by contract name, and new adapters inherit the rules
  declaratively.
- Bad: two mechanisms overlap until PVA-M4.7, and import-linter cannot see SQL or Cypher strings, so
  the AST guard keeps those rules for good.

## Confirmation

`tests/test_import_contracts.py` runs `lint-imports` on the real tree (0 broken contracts) and builds
throwaway packages that break five named contracts, each of which must fail. `tests/test_architecture.py`
keeps its negative fixtures. `tests/test_complexity_ratchet.py` covers the ratchet.
