# ADR-0017: Prompt lock, changelog and pins

Status: accepted (2026-11-14). Master-plan task PVA-M2.13, decision PVA-D18 (git is the prompt
registry), `docs/master-plan/assistant-quality.md` section 9.

## Context and problem statement

`app/ai/prompt.py` carries `PROMPT_VERSION`, bumped by hand, and `docs/evaluation.md` asks authors to
bump it. Nothing enforced the bump: a change to `INSTRUCTIONS` or `OUTPUT_SCHEMA` could ship under an
old version, so evaluation reports, cassettes and the composer cache key (`pequeverso-assistant:
<version>:...`) would name a prompt that no longer exists. The golden cassette lane (PVA-M2.5) also
needs a stable pin to key recorded outputs.

## Considered options

1. Keep the manual convention.
2. A prompt hub or registry service.
3. Git as the registry, with a content-hash lock checked by a unit test.

## Decision outcome

Option 3.

- `prompt_fingerprint()` in `app/ai/prompt.py` returns sha256 pins of `INSTRUCTIONS`, of the
  canonical JSON of `OUTPUT_SCHEMA`, and of both together (`prompt_sha256`).
- `app/ai/prompt.lock.json` is append-only: one entry per `PROMPT_VERSION` (`YYYY-MM-DD.N`), in
  increasing order, no reused version and no shared hash.
- `docs/reference/prompt-changelog.md` has one row per version: the version, the first 12 characters
  of `prompt_sha256`, the reason, the golden and full-set deltas and the cassette re-record commit.
- `scripts/prompt_lock.py` checks the lock, and `--append` records a new version (it never edits a
  version).
- Evaluation reports, cassettes and the `run` event carry `prompt_version` and `prompt_sha256`
  (cassettes in PVA-M2.5, the run event in PVA-M3.2).
- A prompt change triggers the `assistant-quality` CI profile (`app/ai/**`), needs re-recorded
  cassettes and a 100% golden set before merge. Rollback is a revert, because cassettes are versioned
  with the prompt.

### Consequences

- Good: a silent prompt change fails CI; every artefact names the exact prompt it used.
- Bad: two files (lock and changelog) must be edited per bump. An in-place edit of a locked entry
  passes the unit test alone; the CI static job closes that gap by checking the lock against the base
  revision (`python -m scripts.prompt_lock --base=<base>`).

## Confirmation

`tests/test_prompt_contract.py` fails when the instructions or the output schema change without a
new version, when the last lock entry is not `PROMPT_VERSION`, when versions are reordered or
reused, and when the changelog lacks a row for a locked version. In CI, `scripts/prompt_lock.py
--base` fails when a version locked at the PR base revision was edited or removed.
