# ADR-0003: Structured streaming with authoritative final validation

Status: accepted (2026-09-27); presentation boundary updated 2026-10-13

**Context.** The original pipeline checked complete answers but forwarded raw decoded answer
fragments first. A deterministic HTTP/SSE reproduction showed a false $999 price reaching a
delta before final replacement. Completion alone does not establish commercial correctness.

**Decision.** One Responses API call per turn with a strict JSON schema
`{answer, references[{kind,id}], sources[], follow_ups[]}`, `answer` first. Decoded text enters a
buffer bounded by the existing 2000-character answer limit. Only cumulative complete sentence
or paragraph prefixes passing the same normalization and business checks as final answers
may produce `message.delta`. Decimal/URL dots without whitespace are not boundaries. Rejected,
oversized or ambiguous-markup prefixes halt provisional output; generation is not retried.

The remainder may be emitted only after the complete draft produces an accepted canonical
`FinalizedAnswer`; that identical answer is then persisted. A replaced answer is terminal-only
when no valid earlier prefix was emitted. Known usage is settled before the new terminal-tail
yield; missing usage remains conservative. Cancellation and the existing deadline are checked
before and after that yield. Disconnect/cancel/timeout never persist a partial assistant answer.

**Consequences.** Streaming is coarser and a short answer may wait until full validation. An
earlier checked prefix can remain visible until `message.completed` replaces the draft if a
later sentence invalidates the full answer. Deterministic recognizers do not prove general
semantic truth, all claims or citation entailment. Clients must always render the authoritative
final message. Public schemas and v1 revision1.4 are unchanged. Server-owned public-source
retrieval (ADR-0008) is separate from model tools; each turn still has one generation.
