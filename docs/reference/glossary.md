# Glossary

Terms used across the code, ADRs and the master plan. Code names are in backticks. When a term
and the code disagree, the code wins: fix this page.

| Term | Meaning | Where |
|---|---|---|
| Active catalog | The validated catalog snapshot currently used for answers, with its price status. | `app/domain/catalog.py` (`ActiveCatalog`) |
| Admission | Everything a message passes before any model call: assistant enabled, catalog loaded, input valid, runtime ownership, idempotent claim, dependency and rate checks. | `ChatService.start`, `_admit`, `_valid_question` |
| Answer rules | The server-side boundary every answer and prefix is checked against: known prices, allowed URLs and emails, forbidden terms. | `app/domain/answer_policy.py` (`AnswerRules`, `check_answer`) |
| Block builder | Server-side construction of the draft v1.7 response blocks from a finalized answer and the catalog; off until `blocks_v2`. | `app/application/blocks.py` |
| Cassette | A recorded provider response replayed at the provider port, so evaluations run with no network. | `evals/`, ADR-0010 |
| Composition root | The only place that builds concrete adapters and wires them into use cases. | `app/bootstrap/container.py` |
| Fail closed | A startup rule that refuses an unsafe configuration instead of running with it. | `Settings.fail_closed`, `_FAIL_CLOSED_RULES` |
| Feature flags | The per-run snapshot of assistant v2 switches, all off by default, supplied by the `Flags` port. | `app/application/flags.py`, ADR-0021 |
| Finalize | Turning a model draft into the stored answer: scope the rules, check content, resolve references and sources, filter follow-ups, append disclosures, or replace the whole answer. | `app/application/answers.py` |
| Fixture profile | The default local and test configuration: fixture provider, SQLite storage, no credentials. Never an answering production store. | ADR-0020 |
| Full set | The about 320-item evaluation set, reported by family, without a 100% gate. | `evals/full/`, OD-30 |
| Golden set | The 60-item evaluation set with a 100% release gate. | `evals/golden/`, OD-30 |
| Grounding | The guarantee that prices, policies and claims come only from the catalog, enforced in code rather than in the prompt. | AGENTS.md, ADR-0003 |
| Lifespan | Application start and stop: cleanup registration, ordered acquisition, background loops, bounded drain. | `app/bootstrap/lifespan.py` |
| Local answer | A deterministic reply built from the catalog without a model call (catalog scope, provenance, reference clarification, price comparison). | `ChatService._local_answer` |
| Memory store | Optional, opt-in visitor preferences with a closed schema and a fixed per-fact TTL; ships disabled. | `app/application/memory_ports.py`, ADR-0021 |
| Ratchet | A committed baseline that may only tighten: ruff, complexity, coverage, mutation, retrieval, golden. | `ratchets/` |
| Replacement | The safe answer emitted when a draft breaks an answer rule. | `replacement_text`, `Notice.ANSWER_REPLACED` |
| Reservation | The worst-case spend reserved on the ledger before a model call, settled with the real usage afterwards. | `ChatService._dispatch`, `_ModelRun._settle` |
| Rule table | An ordered tuple of named checks, evaluated in order; the first failure wins. | `_FAIL_CLOSED_RULES` |
| Validated prefix | The part of a streamed answer already shown to the visitor, checked against the answer rules as it grows. | `ValidatedStreamPrefix` |
| Wiring | The frozen graph of services that `create_app` builds once; the lifespan and HTTP assembly read from it. | `app/bootstrap/wiring.py` |
