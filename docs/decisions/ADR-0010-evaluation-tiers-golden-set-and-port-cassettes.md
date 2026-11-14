# ADR-0010: Two evaluation tiers, the golden set, and cassettes at the provider port

Status: accepted (2026-11-14). Master-plan tasks PVA-M2.4 and PVA-M2.5, decisions PVA-D1 (English
block), PVA-D5 (record at the port) and PVA-D13 (spend caps). `docs/master-plan/assistant-quality.md`
sections 2 to 5.

## Context and problem statement

The corpus (288 cases) runs in fixture mode, and that proves only the pipeline: the fixture provider
answers with the best lexical match, so its behaviour flags say nothing about a model. Real-model
runs cost money and need the owner's authorization each time. We need a gate that every PR can run
with no network and no secrets, and that still exercises the real server path and the answer rules.

## Considered options

1. Gate on the fixture-mode corpus only.
2. HTTP-level cassettes (vcrpy) around the OpenAI SDK.
3. Two tiers: a 60-item golden set gated at 100%, plus a full set tracked with ratchets, both
   replayed through cassettes recorded at the provider port (`ModelProvider`).

## Decision outcome

Option 3.

- Tier 1, `evals/golden/golden.jsonl`: 60 items (schema v2, `evals/schema.py`) across five strata.
  Every PR in the `assistant-quality` path set must pass all of them in replay. Before a release,
  a live pass^3 run is made under the spend cap, owner-authorized.
- Tier 2, `evals/full/` (PVA-M2.6): about 318 items that are not gated; they are compared with a
  committed baseline.
- Graders are deterministic (`evals/graders.py`) and reuse the server's own rules. Judges never gate.
- Cassettes (`evals/cassette.py`) are keyed by the sha256 of the instructions, inputs, output schema
  and token cap. The per-session safety identifier and the cache key are left out. Each cassette pins
  `prompt_version`, `prompt_sha256` (ADR-0017) and `catalog_sha256`. There are two kinds:
  - `recorded`: a real run made by an authorized session through a recording wrapper;
  - `scripted`: hand-authored output, including deliberately misbehaving outputs that prove the guards
    neutralize them.

  Replay never falls back to the fixture provider. A missing, stale or draft cassette fails the item
  with a re-record message.
- The runner (`evals/runner.py`) drives the real HTTP/SSE application: session, CSRF, SSE, evidence
  packing, `finalize` and persistence. It uses a deterministic clock (catalog export time plus the
  item's offset), so requests never change with the calendar.
- Until the owner authorizes a live recording, every golden cassette is `scripted`. The gate then
  proves server-side enforcement against fixed outputs, not model quality; the assistant-quality axis
  keeps its floor of 90 (`scorecard.md`).

### Consequences

- Good: a change to the prompt, catalog, packing, answer rules or streaming that alters a request or an
  answer fails without network or secrets, and fork PRs run the same lane.
- Good: the scripted adversaries already found one real gap (an outcome promise that passed the rules,
  fixed in PR #133).
- Bad: any prompt or catalog change re-keys cassettes. A scripted cassette is re-keyed with
  `--author --rekey` and reviewed in the PR; a recorded one needs an authorized live run (about USD 0.05
  for the touched items).
- Bad: scripted outputs reflect the author's idea of a good answer, so they cannot show model drift.

## Confirmation

The `static` CI job runs `uv run python -m evals.runner golden --replay` and fails on any failing item or
unused cassette. `tests/test_eval_schema.py`, `tests/test_eval_graders.py` and `tests/test_eval_cassette.py`
cover the loader, the graders and the replay errors.
