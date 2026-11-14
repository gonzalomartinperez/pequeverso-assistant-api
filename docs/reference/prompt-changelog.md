# Prompt changelog

One row per `PROMPT_VERSION` (`app/ai/prompt.py`), newest first. The pins live in
`app/ai/prompt.lock.json` (append-only); `tests/test_prompt_contract.py` fails when the instructions or
the output schema change without a new version, a lock entry and a row here. Decision: ADR-0017.

How to change the prompt:

1. Edit `INSTRUCTIONS` or `OUTPUT_SCHEMA` and set `PROMPT_VERSION` to `YYYY-MM-DD.N`.
2. Append the new pins: `uv run python -m scripts.prompt_lock --append`.
3. Add a row below (reason, golden and full-set deltas, cassette re-record commit).
4. Re-record the affected cassettes (owner-authorized live run) and keep the golden set at 100%.

| Version | prompt_sha256 (first 12) | Reason | Golden / full-set delta | Cassettes |
|---|---|---|---|---|
| 2026-10-18.4 | `c42c7095007c` | Baseline pinned by PVA-M2.13; the version predates the lock (history: `git log app/ai/prompt.py`) | golden set not yet built (PVA-M2.4) | none recorded yet (PVA-M2.5) |
