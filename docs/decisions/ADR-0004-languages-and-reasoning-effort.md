# ADR-0004: Spanish and English answers; medium reasoning effort

Status: accepted (2026-10-05)

## Context

The owner asked for answers in Spanish and English, detected from the visitor's message and
conversation, with the interface language as a preference only, and a short notice for other
languages. The owner also moved `gpt-6-luna` from `low` to `medium` reasoning effort.
OpenAI's model page (read 2026-10-05) lists `none, low, medium (default), high, xhigh, max` for
`gpt-6-luna` with the Responses API and streaming; prices USD 0.10 input, 0.01 cached input,
0.125 cache write, 0.50 output per 1M tokens (2x/1.5x above 272K input tokens). The reasoning
guide states that reasoning tokens are billed as output, count toward `max_output_tokens`, and
that a too-low cap ends a response as `incomplete` before visible text, still billed.

## Decision

- Language is decided **in code** (`app/domain/language.py`), not by the model and not by an
  extra model call: first recognize unquoted, non-negated output-language requests. The last
  supported request in textual order wins; any explicit unsupported target produces the local
  bilingual notice, never a supported-language model fallback. Otherwise use a word-list
  scorer over the visitor's own words (quotes, code, URLs and product names removed), then
  the last answer language, then the UI locale, then Spanish. The
  composer passes `reply_language`; replacements and refusals have Spanish and English copies.
  Other languages get a fixed bilingual note without a model call or spend. This controls
  requested language, not semantic verification that every provider-generated sentence uses it.
- Effort `medium` by default (`OPENAI_REASONING_EFFORT`); `max_output_tokens` raised from 1200
  to 4000 and the run deadline from 45 s to 60 s. Usage is settled also from incomplete or
  failed responses that report it, and `reasoning_tokens` is recorded.

## Consequences

- Worst-case reservation per turn rises to about USD 0.005 (24k input bytes at the cache-write
  rate + 4000 output tokens). With USD 10/month and a 10 % margin that is at least ~1,800
  worst-case turns; real turns cost less (cached input, shorter output). No conversation count
  is promised until the authorized live evaluation measures real usage.
- The detector is heuristic: very short or mixed messages fall back to the conversation and
  locale. It is covered by unit tests and by the language family of the evaluation corpus.
- The catalog stays in Spanish; English answers keep product names in Spanish. Translating the
  store is out of scope.

## Verification update (2026-10-10)

[The official model page](https://developers.openai.com/api/docs/models/gpt-6-luna) was
re-read: medium and the Standard rates above remain supported. Access in the owner's project
was not probed and the private provider key was not read. Paid calls remain unauthorized for
this increment; all new probes use fixtures and cannot certify live-model quality or cost.
