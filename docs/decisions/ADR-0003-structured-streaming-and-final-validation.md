# ADR-0003: Structured streaming with authoritative final validation

Status: accepted (2026-09-27)

**Context.** Answers must stream, but references, links, prices and commercial claims must be
validated in code before a visitor can rely on them.

**Decision.** One Responses API call per turn with a strict JSON schema
`{answer, references[{kind,id}], sources[], follow_ups[]}`, `answer` first. The server decodes
the `answer` string incrementally and streams it as provisional `message.delta`. On completion
it parses the whole object, resolves every id against the catalog (dropping unknown ones) and
applies the answer rules. A violating answer is replaced whole. The server then emits
`message.completed`, which clients must treat as authoritative, replacing the draft.

**Consequences.** Visitors may briefly see streamed text that is later replaced. This is rare,
signalled by the `answer_replaced` notice, and the replaced text is never stored or re-sent
to the model. There are no tools and no multi-step agent loop, so each turn is bounded to one
call. Product cards carry only server data.
