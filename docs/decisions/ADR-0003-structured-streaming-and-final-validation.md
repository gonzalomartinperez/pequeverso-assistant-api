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

## Confirmation

`tests/test_validated_stream.py` pins the decision: per-character splits of rejected claims never
reach SSE, history or replay (`test_rejected_claims_split_per_character_never_reach_sse_history_or_replay`),
decimals stay whole (`test_published_decimal_split_per_character_remains_complete_and_exact`), a
held bad sentence is replaced at the end (`test_safe_prefix_then_bad_sentence_is_held_and_final_replaced`),
and cancel, disconnect or deadline never persist a partial answer
(`test_cancel_and_timeout_after_safe_prefix_never_persist_partial_history`). `tests/test_streaming.py`
(`test_failures_and_timeouts_end_with_one_terminal_event`,
`test_client_disconnect_cancels_upstream_and_stores_nothing_partial`) and `tests/test_sse_conformance.py`
cover the stream lifecycle. `tests/test_properties_sse.py` adds property tests, and the CI `static`
job replays the golden set and the red-team pack (`uv run python -m evals.runner golden --replay`,
`uv run python -m evals.runner red-team --replay`). The residual limit stated above (recognizers
do not prove semantic truth) has no automated check; real-model evidence is manual and dated.
