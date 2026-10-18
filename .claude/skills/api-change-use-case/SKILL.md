---
name: api-change-use-case
description: Change prompts, answer rules, evidence or evaluations of the Pequeverso assistant safely. Not for live paid evaluations without the owner's authorization.
---

# Change assistant behavior

1. Decide the layer. Tone and format go in `app/ai/prompt.py` (bump `PROMPT_VERSION`). A
   guarantee (links, prices, claims, ids) goes in `app/domain/answer_policy.py` or
   `app/application/answers.py`, with a guard case in `evals/guards.json`.
2. Add or adjust a scenario in `evals/conversations.json` (safety runs everywhere; quality is
   meaningful only live) and unit tests next to the changed code.
3. Run `uv run pytest` and `uv run python scripts/evaluate_conversations.py`. Safety and guard
   failures must be zero.
4. Live evaluation only with explicit owner authorization and a separate Pequeverso key:
   follow `docs/evaluation.md`. Otherwise state in the PR that live quality is unverified.
5. Never weaken a rule to make an evaluation pass, and never put ideal answers in application
   code.

## Limits

- No live or paid evaluation without the owner's explicit, current authorization and the
  separate Pequeverso key. Never move a guarantee from code into the prompt only.
- Evidence: `uv run pytest`, the fixture evaluations and, if authorized, the live report.


## Optional official public-source changes

Follow ADR-0008 and docs/official-web-evidence.md: exact three source ids, read-only/default-off,
no visitor data in requests, fixture network off, no model tools or extra attempts. Regressions
belong in tests/test_official_help.py. Source changes do not authorize paid calls or refresh
merchant price/policy facts; preserve prior evaluation artifacts and reconcile its shared cap.
