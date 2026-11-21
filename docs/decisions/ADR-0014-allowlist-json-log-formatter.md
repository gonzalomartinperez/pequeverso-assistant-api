# ADR-0014: Keep the allowlist JSON log formatter; no structlog

Status: accepted (2026-11-21). Master-plan task PVA-M3.4.

## Context and problem statement

Logs must never carry visitor messages, prompts, session or client identifiers, IP addresses,
credentials or provider text. `app/bootstrap/logging.py` provides `SafeJsonFormatter`. Each owned
logger and event is declared in `_EVENTS` with the exact fields it may emit, and values must also
pass a per-field allowlist. Records from any other logger are not evaluated (`getMessage` can run
arbitrary `__str__`): at WARNING and above they are written as a content-free line with logger
`external`, level and, for exceptions, a name from a fixed set; below WARNING they are only counted
into one `external_events` line (PVA-M3.2). The question is whether to replace it with `structlog`.

## Considered options

- `structlog` with a processor chain: rejected. Its default model is "log what the caller passes,
  then redact"; a forgotten field or processor still logs. It also does not control third-party
  stdlib records unless they are routed through it, and it adds a dependency to the image, the
  lockfile and the licence review.
- Standard library `logging` with an allowlist formatter: chosen.

## Decision outcome

Keep the formatter. The guarantee is "nothing outside an allowlist can be logged", and it holds by
construction: an unknown logger, operation, field or value is dropped, not redacted. One dependency
fewer. New log events need an entry in `_EVENTS` and, where a value is free-form, a value
allowlist; the entry is reviewed like any other contract change.

### Consequences

- Good: the property is simple to test and cannot be bypassed by a new call site.
- Good: runtime tracing and third-party loggers cannot leak through ambient configuration.
- Bad: adding an event is more work than a structlog `bind`, by design.
- Bad: the formatter is project code that we maintain (JSON shape, level names, timestamps).

## Confirmation

`tests/test_security.py` pins the behavior:
`test_structured_external_logs_never_cross_the_application_allowlist`,
`test_owned_json_logs_accept_only_safe_event_fields_and_values`,
`test_owned_log_fields_cannot_smuggle_arbitrary_strings`,
`test_owned_unknown_operation_is_reduced_to_safe_metadata`,
`test_provider_details_are_untrusted_even_with_an_owned_logger`,
`test_external_log_messages_are_not_evaluated`,
`test_deep_json_does_not_escape_the_formatter_or_dump_private_content`,
`test_json_parser_recursion_failure_has_no_raw_logging_fallback`,
`test_logs_never_contain_conversation_content_or_ips` and
`test_uvicorn_error_handler_uses_safe_formatter_without_raw_exception`. It runs in the CI `static`
job with the rest of the suite. `tests/test_logging_streams.py` covers the stream split, the
`external_events` counter and that only a server-generated request id is logged. The structlog
rejection is a design choice with no automated check.
