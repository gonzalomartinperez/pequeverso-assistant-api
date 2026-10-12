# ADR-0006: Native Spanish policy without breaking v1 clients

Status: accepted (2026-10-12)

## Context

The owner now requests a Spanish-only storefront assistant, without a language selector,
named “Asistente de Pequeverso”. Existing v1 clients and stored English messages still exist.
Changing the shared language enum or silently rewriting those messages would break consumers.

## Decision

- Add optional `MessageIn.response_language: "es" | null` in v1 revision1.4. Native requests
  always use `locale: "es"` and `response_language: "es"`; the native client refuses a backend
  below revision1.4 before generating. Omitted/null retains the legacy ES/EN behavior.
- Decide the native reply language in code before evidence preparation or provider dispatch.
  Recognized explicit requests for a foreign reply language get a Spanish-only local notice
  without provider usage. Ordinary questions written in English can receive Spanish answers.
- Preserve historical message language, conversation and drafts. Include an explicitly present
  native policy in the idempotency fingerprint; do not replay an old English answer under a new
  Spanish policy. Omitted/null retains the exact legacy fingerprint.
- Quotes, code, negated requests and references to a material's language are not output-language
  commands. Keep deterministic positive and negative regressions.
- Use a natural customer-facing title and a sparkles launcher. Be truthful about being an AI
  assistant when asked; the visible title does not authorize pretending to be a person.

## Consequences and verification

This additive policy does not globally remove English from v1. Its bounded recognizer and
response metadata cannot prove that every future generated sentence is Spanish; actual prose
and suggested questions require evaluation. The whole catalog remains authoritative data,
and language/context hints never override evidence or security instructions.

Unit, HTTP/SSE and replay tests cover legacy compatibility, policy conflicts and local notices.
The [dated real-model evidence](../verification/real-model-2026-10-12.md) records the53-query
Spanish revalidation separately from the original bilingual baseline. Agent review is not
human review, and the storefront remains disabled until separate activation after VPS checks.
