# ADR-0002: Grounding with the whole catalog; no embeddings

Status: accepted (2026-09-27)

**Context.** The catalog is one kit with nine resources, eleven FAQ entries and a dozen policy and
support notes: about 17 KB of JSON (~5k tokens). Cached input on `gpt-6-luna` costs USD 0.01/M.

**Decision.** Send the whole compact catalog as evidence on every turn, in stable order so the
prompt prefix is cacheable (`prompt_cache_key` per catalog sha). A small BM25-style lexical ranker
decides which documents stay only if the catalog outgrows `MAX_EVIDENCE_CHARS` (40k). The same
ranker feeds the fixture provider and the retrieval evaluation.

**Evidence.** `evals/retrieval.json` (20 cases): recall@3 = 0.95, MRR = 0.908. The only miss is a
synonym gap that the model resolves anyway, since it sees the whole catalog.

**Revisit when** the catalog passes about 40k characters, or a live evaluation shows grounding
misses. Then add hybrid retrieval with provenance, a versioned index and atomic swaps, and
evaluate before and after.

## Confirmation

The CI `static` job runs `uv run python scripts/evaluate_retrieval.py` (the 20-case
`evals/retrieval.json` figures above) and `uv run python -m scripts.retrieval_ratchet` through
`tests/test_retrieval_ratchet.py`, which fails when recall@3, recall@5, nDCG@5 or MRR drop below
`ratchets/retrieval.json`. `tests/test_request_packing.py` covers the packed evidence, including
`test_old_context_compacts_but_latest_exchange_and_structured_catalog_survive` and
`test_valid_but_unsent_catalog_document_cannot_become_final_citation`. The cache-friendly stable
order of the catalog has no dedicated test; it is checked by review and by the golden-set replay
(`uv run python -m evals.runner golden --replay`), whose cassettes are keyed on the request.
