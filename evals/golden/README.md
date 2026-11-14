# Golden set v1

`golden.jsonl` is the assistant's release gate: 60 items (66 visitor turns) that must all pass. The
plan is `docs/master-plan/assistant-quality.md` sections 2 to 5, and the schema is
`evals/schema.py` (version 2).

## Composition

| Stratum | Items |
|---|---:|
| Answerable core (9 source families) | 21 |
| Comparison, kit versus affiliate scope, ambiguity | 9 |
| Abstain, out of scope, false premise (stale price, price bait, unknown policy) | 15 |
| Adversarial invariants | 9 |
| Multi-turn (scripted) | 6 |

Locales: 55 `es` (8 with typos or missing accents, 6 regional: es-AR, es-MX, es-CO, es-ES), 3 `en`
and 2 `mixed`. The assistant is Spanish-only (ADR-0006, OD-32): the English items check only that
the reply is in Spanish, or that the local "Spanish only" notice appears when someone asks for
another language. Splits use the corpus rule (group-preserving, sha256 order), which gives 42 `dev`
and 18 `holdout`.

## Rules

- Items are written natively; nothing is machine-translated. Every item pins the catalog snapshot
  (`catalog_sha256`); a catalog change fails validation until each item is re-verified.
- Grading is deterministic only (`evals/graders.py`), and judges never gate. Every item runs the
  safety invariants: policy, price grounding and unverified prices, page, checkout and policy claims,
  forbidden behaviours, references, reply language, notices, prompt leakage, neutral "tú" and
  guarantee days. On top of that, each item runs its own assertions: required facts and gold
  grounding for answers, and the abstention shape for `clarify`, `no_info` and `decline`.
- The holdout is procedural, not secret (the repository is public). Prompt authors do not read
  holdout failures, and 20% of the items rotate each quarter, keeping the same strata.
- 60 of 60 bounds the failure rate at about 5% (rule of three, 95%); it does not prove perfection.
  Reports print that bound per stratum.
- Status changes: a `quarantined` item needs an owner and a deadline; a `retired` item needs a reason.
  An incident reported by the owner becomes an item within 48 hours. Items are never built from stored
  transcripts.

## Review

The items were drafted by an agent on 2026-11-14 (`reviewer` field). The owner's one-time review
for Spanish naturalness (about 1.5 hours, owner input listed in `docs/master-plan/progress.md`) is
still pending. Until it is done, wording changes are expected; strata and expectations are not.

## Validate

```bash
uv run pytest -q tests/test_eval_schema.py tests/test_eval_graders.py
```

The replay gate (cassettes at the provider port) is PVA-M2.5: `uv run python -m evals.runner golden --replay`.
