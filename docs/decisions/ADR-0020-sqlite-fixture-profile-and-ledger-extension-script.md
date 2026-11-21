# ADR-0020: Keep the SQLite fixture profile; retire the ledger-extension script on owner confirmation

Status: accepted (2026-11-21). Master-plan task PVA-M4.9, decision PVA-D12 (resolved by delegation,
`docs/master-plan/README.md`). The plan named this ADR-0019; ADR-0018 and ADR-0019 went to release
tagging (PVA-M1.10) and the health aliases (PVA-M3.3).

## Context and problem statement

ADR-0009 moved production storage to PostgreSQL with GraphRAG, and `Settings.fail_closed` refuses an
answering production deployment on anything else (`_check_production_answer_storage`). The SQLite
profile (`app/adapters/sqlite/`, five modules) remains the default for local runs and tests: no
credentials, no service and no container.

PVA-D12 was resolved as follows: keep SQLite until the `database` CI job proves a PostgreSQL-only
local profile, then retire it. It also retires `scripts/extend_evaluation_envelope.py` once the
2026-10 private evaluation ledgers are closed.

Two facts decide the question in M4:

- The static and unit lanes run about 2,300 tests on SQLite with `tmp_path` databases in parallel
  (`pytest -n auto`). About two dozen test modules use PostgreSQL or Neo4j fixtures, and those tests need an
  explicitly isolated service lease (`services` lane). The `database` job proves that the PostgreSQL adapters
  pass on a real server. It does not prove that a credential-free local profile can replace SQLite:
  every PostgreSQL run needs a provisioned server and a DSN secret.
- The extension script performs fixed, audited transitions on private ledgers that live outside git
  (`docs/reference/evaluation.md`). Whether those ledgers are closed is private operator state, so
  no agent can verify it from the repository.

## Considered options

1. Retire SQLite now and move every test and the local default to PostgreSQL. This would make every
   contributor and CI lane depend on a database service. It would also rewrite most of the suite and
   remove the credential-free default that AGENTS.md promises.
2. Keep SQLite as the fixture and test profile only. Production stays PostgreSQL, enforced in code.
   The retirement trigger is written down.
3. Keep both profiles as production options. This was rejected by ADR-0009.

## Decision outcome

Option 2.

- SQLite stays the credential-free fixture and test profile. It is never an answering production
  store, and `fail_closed` keeps that guarantee in code rather than in documentation.
- New behaviour lands in both storage adapters behind the same ports (`tests/test_adapter_compatibility.py`).
- Retirement trigger, re-evaluated at M6: an ephemeral PostgreSQL started by the test run itself (no
  shared service, no secret) runs the unit lane inside its budget (p50 ≤ 90 s, PVA-M1.5). When that
  holds, a new ADR supersedes this one and removes `app/adapters/sqlite/`.
- `scripts/extend_evaluation_envelope.py` stays, unchanged and offline, until the owner confirms that
  the 2026-10 private ledgers are closed. Its retirement is then one PR. It removes the script, its
  three action groups in `scripts/real_eval_budget.py`, the three envelope tests and the procedure
  in `docs/reference/evaluation.md`. The open question is listed in the M4 report as an owner input.

### Consequences

- Good: local runs and the fast lanes stay free of services and credentials. The production
  guarantee is unchanged and tested.
- Bad: two storage adapters must be kept equivalent. The compatibility tests and the `database` job
  are the guard.
- Neutral: the one-shot script stays in the tree, documented as historical and offline.

## Confirmation

- `tests/test_config_rules.py` (rule `production-answer-storage`) and `tests/test_env_schema.py`
  prove that production refuses answering on SQLite.
- `tests/test_adapter_compatibility.py` keeps the two adapters equivalent behind the ports.
- `tests/test_evaluation_envelope_extension.py`, `tests/test_evaluation_followup_envelope.py` and
  `tests/test_evaluation_final_format_envelope.py` keep the script's fixed transitions exact while it
  exists.
- `tests/test_sqlite_profile_decision.py` fails if the SQLite adapter or the script disappears
  without a superseding ADR, so the retirement cannot happen silently.
