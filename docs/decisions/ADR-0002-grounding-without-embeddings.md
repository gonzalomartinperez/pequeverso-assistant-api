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
