"""Structured logs validate event ownership and each field at the formatter boundary."""

import json
import logging

import pytest

from app.bootstrap.logging import SafeJsonFormatter


def formatted(name, message, *, args=(), exc_info=None):
    record = logging.LogRecord(name, logging.WARNING, "fixture.py", 1, message, args, exc_info)
    record.created = 0
    return json.loads(SafeJsonFormatter().format(record))


@pytest.mark.parametrize(
    ("logger", "operation", "field", "accepted", "rejected"),
    [
        ("app.request", "request", "duration_ms", [None, 0, 10**12], [-1, True, 1.5, 10**12 + 1]),
        ("app.request", "request", "status", [100, 599], [99, 600, True, "200"]),
        ("app.request", "request", "method", ["GET"], ["get", 2]),
        ("app.request", "request", "route", ["/api/v1/messages"], ["/api/v1/messages/private"]),
        (
            "app.request",
            "request",
            "request_id",
            ["a" * 8, "a" * 64],
            ["a" * 7, "a" * 65, "key@host"],
        ),
        ("app.application.chat", "run", "replaced", [True, False], [0, "true"]),
        (
            "app.application.chat",
            "run",
            "violations",
            [[], ["unlisted_url"]],
            [["invalid"], [1], "unlisted_url", ["unlisted_url"] * 20],
        ),
        ("app.application.chat", "run", "language", ["es", "en"], ["pt", None]),
        ("app.application.chat", "run", "code", ["timeout"], ["driver timeout"]),
        ("app.application.chat", "run", "prompt_version", ["2026-11-22.12"], ["2026-11-22.1234"]),
        (
            "app.application.catalog",
            "catalog_refresh",
            "sha256",
            ["0123456789ab"],
            ["0123456789AB", "a" * 64],
        ),
        (
            "app.application.catalog",
            "catalog_refresh",
            "reason",
            ["ValueError"],
            ["synthetic driver value"],
        ),
        (
            "app.adapters.official_help",
            "official_help",
            "topic",
            ["digital_delivery"],
            ["private account"],
        ),
    ],
)
def test_allowlisted_log_fields_require_valid_types_and_values(
    logger, operation, field, accepted, rejected
):
    for value in accepted:
        log = formatted(logger, json.dumps({"operation": operation, field: value}))
        assert log[field] == value
    for value in rejected:
        log = formatted(logger, json.dumps({"operation": operation, field: value}))
        assert field not in log
        assert log["operation"] == operation


@pytest.mark.parametrize("message", ["not json", "[]", '{"operation":12}', '{"operation":"run"}'])
def test_unstructured_request_events_drop_the_entire_payload(message):
    assert formatted("app.request", message) == {
        "ts": "1970-01-01T00:00:00.000+00:00",
        "level": "warning",
        "logger": "app.request",
        "operation": "unstructured_event",
    }


def test_log_drops_unknown_payload_fields_and_normalizes_exception_names():
    class PrivateFailureError(Exception):
        pass

    log = formatted(
        "app.request",
        '{"operation":"request","status":503,"session_id":"synthetic private id"}',
        exc_info=(PrivateFailureError, PrivateFailureError("private driver values"), None),
    )
    assert log == {
        "ts": "1970-01-01T00:00:00.000+00:00",
        "level": "warning",
        "logger": "app.request",
        "operation": "request",
        "status": 503,
        "exception": "Exception",
    }


def test_external_message_is_never_evaluated_and_known_exception_type_is_safe():
    class Payload:
        def __str__(self):
            pytest.fail("external message was evaluated")

    log = formatted(
        "external.library",
        "%s",
        args=(Payload(),),
        exc_info=(ValueError, ValueError("synthetic private value"), None),
    )
    assert log == {
        "ts": "1970-01-01T00:00:00.000+00:00",
        "level": "warning",
        "logger": "external",
        "operation": "unstructured_event",
        "exception": "ValueError",
    }
