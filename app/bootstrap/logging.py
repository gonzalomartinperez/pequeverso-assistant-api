"""JSON logs with an allowlist: application log calls pass JSON strings built from safe fields;
anything else (e.g. third-party messages or exception text) is reduced to its logger and level
so conversation content, secrets and exception details never reach the log stream.
"""

from __future__ import annotations

import atexit
import json
import logging
import re
import sys
import threading
import time
from datetime import UTC, datetime

from app.domain.answer_policy import Violation
from app.domain.errors import FailureCode
from app.domain.language import Language
from app.domain.web_evidence import HelpTopic

# Logger ownership and event schemas are explicit; being JSON is never a trust signal.
_EVENTS: dict[str, dict[str, frozenset[str]]] = {
    "app.request": {
        "request": frozenset({"method", "route", "status", "duration_ms", "request_id"})
    },
    "app.bootstrap.logging": {"external_events": frozenset({"count"})},
    "app.application.chat": {
        "run": frozenset(
            {
                "outcome",
                "code",
                "replaced",
                "violations",
                "dropped_references",
                "input_tokens",
                "output_tokens",
                "reasoning_tokens",
                "language",
                "prompt_version",
                "first_delta_ms",
                "latency_ms",
            }
        ),
        "run_metric": frozenset({"outcome"}),
    },
    "app.application.catalog": {
        "catalog_restore": frozenset({"outcome"}),
        "catalog_refresh": frozenset({"outcome", "reason", "sha256"}),
    },
    "app.adapters.providers.openai_provider": {
        "provider_usage": frozenset({"outcome"}),
        "provider_open": frozenset({"outcome", "error"}),
        "provider_stream": frozenset({"outcome", "reason"}),
    },
    "app.adapters.official_help": {"official_help": frozenset({"outcome", "topic"})},
    "app.adapters.observability.telemetry": {
        "telemetry_export": frozenset({"outcome"}),
        "telemetry_shutdown": frozenset({"outcome"}),
        "telemetry_run_window": frozenset({"outcome"}),
    },
    "app.bootstrap.container": {
        "retention": frozenset({"sessions_deleted", "outcome"}),
        "startup": frozenset({"abandoned_runs"}),
        "shutdown": frozenset({"outcome"}),
    },
}
_OUTCOMES = frozenset(
    {
        "completed",
        "failed",
        "cancelled",
        "interrupted",
        "refused",
        "unexpected_error",
        "invalid_stored_snapshot",
        "activated",
        "malformed",
        "rejected",
        "response.failed",
        "response.incomplete",
        "error",
        "timeout",
        "cache_hit",
        "unavailable",
        "verified",
        "drain_failed",
    }
)
_ERROR_NAMES = frozenset(
    {
        "Exception",
        "RuntimeError",
        "ValueError",
        "TypeError",
        "TimeoutError",
        "OSError",
        "ConnectionError",
        "OperationalError",
        "DatabaseError",
        "IntegrityError",
        "ValidationError",
        "HTTPError",
        "HTTPStatusError",
        "RequestError",
        "ConnectError",
        "ReadTimeout",
        "ConnectTimeout",
        "APIError",
        "APIConnectionError",
        "APITimeoutError",
        "APIStatusError",
        "RateLimitError",
        "InternalServerError",
        "AuthenticationError",
        "PermissionDeniedError",
        "BadRequestError",
        "NotFoundError",
        "ConflictError",
        "UnprocessableEntityError",
        "APIResponseValidationError",
    }
)
_ROUTES = frozenset(
    {
        "unmatched",
        "/health/live",
        "/health/ready",
        "/api/v1/availability",
        "/api/v1/analytics/events",
        "/api/v1/session",
        "/api/v1/messages",
        "/api/v1/openapi.json",
        "/api/v1/runs/{run_id}/cancel",
        "/internal/v1/ops/summary",
        "/internal/v1/ops/product-analytics",
        "/internal/v1/ops/telemetry",
        "/internal/v1/ops/metrics",
    }
)
_NUMBERS = frozenset(
    {
        "duration_ms",
        "first_delta_ms",
        "latency_ms",
        "dropped_references",
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "sessions_deleted",
        "abandoned_runs",
        "count",
    }
)
_REQUEST_ID = re.compile(r"[A-Za-z0-9-]{8,64}")
_PROMPT_VERSION = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\.[0-9]{1,3}")


def _safe_field(name: str, value: object) -> bool:
    if name in _NUMBERS:
        return value is None or (type(value) is int and 0 <= value <= 10**12)
    if name == "status":
        return type(value) is int and 100 <= value <= 599
    if name == "replaced":
        return type(value) is bool
    if name == "violations":
        return (
            isinstance(value, list)
            and len(value) <= len(Violation)
            and all(
                isinstance(item, str) and item in {v.value for v in Violation} for item in value
            )
        )
    if not isinstance(value, str):
        return False
    allowed = {
        "outcome": _OUTCOMES,
        "method": frozenset({"GET", "POST", "DELETE", "OPTIONS", "HEAD", "PUT", "PATCH"}),
        "route": _ROUTES,
        "code": frozenset(v.value for v in FailureCode),
        "language": frozenset(v.value for v in Language),
        "topic": frozenset(v.value for v in HelpTopic),
        "error": _ERROR_NAMES,
        "reason": _ERROR_NAMES | {"max_output_tokens", "content_filter", "none"},
    }
    patterns = {
        "sha256": re.compile("[0-9a-f]{12}"),
        "request_id": _REQUEST_ID,
        "prompt_version": _PROMPT_VERSION,
    }
    if name in patterns:
        return patterns[name].fullmatch(value) is not None
    return value in allowed.get(name, frozenset())


class SafeJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": logging.getLevelName(record.levelno).lower(),
            "logger": record.name
            if record.name in _EVENTS or record.name == "uvicorn.error"
            else "external",
        }
        payload = None
        # External records are not evaluated at all: even getMessage may execute a custom
        # __str__, and parser failures must never reach logging's raw-message fallback.
        if record.name in _EVENTS:
            try:
                payload = json.loads(record.getMessage())
            except TypeError, ValueError, RecursionError:
                payload = None
        entry["operation"] = "unstructured_event"
        if isinstance(payload, dict) and isinstance(operation := payload.get("operation"), str):
            fields = _EVENTS.get(record.name, {}).get(operation)
            if fields is not None:
                entry["operation"] = operation
                entry.update(
                    {
                        name: value
                        for name, value in payload.items()
                        if name in fields and _safe_field(name, value)
                    }
                )
        if record.exc_info and record.exc_info[0] is not None:
            kind = record.exc_info[0].__name__
            entry["exception"] = kind if kind in _ERROR_NAMES else "Exception"
        return json.dumps(entry, ensure_ascii=False)


EXTERNAL_FLUSH_SECONDS = 60.0
_use_stderr = False
_external: ExternalEventCounter | None = None


class ExternalEventCounter(logging.Filter):
    """Third-party records below WARNING carry no allowlisted content, so they are only counted.

    The count is flushed as one `external_events` line when a window elapsed (checked on the
    next external record) and at shutdown. It is content-free: a number only.
    """

    def __init__(self, handler: logging.Handler, window: float = EXTERNAL_FLUSH_SECONDS) -> None:
        super().__init__()
        self._handler = handler
        self._window = window
        self._count = 0
        self._since = time.monotonic()
        self._lock = threading.Lock()

    def filter(self, record: logging.LogRecord) -> bool:
        if (
            record.name in _EVENTS
            or record.name == "uvicorn.error"
            or record.levelno >= logging.WARNING
        ):
            return True  # warnings and errors keep their content-free `external` line
        with self._lock:
            self._count += 1
            due = time.monotonic() - self._since >= self._window
            count = self._detach() if due else 0
        self._emit(count)
        return False

    def _detach(self) -> int:
        count, self._count = self._count, 0
        self._since = time.monotonic()
        return count

    def flush(self) -> None:
        with self._lock:
            count = self._detach()
        self._emit(count)

    def _emit(self, count: int) -> None:
        if count:
            line = json.dumps({"operation": "external_events", "count": count})
            self._handler.handle(
                logging.LogRecord("app.bootstrap.logging", logging.INFO, "", 0, line, None, None)
            )


def use_stderr() -> None:
    """CLIs and evaluations print machine output on stdout: logs must never share it.

    Process-wide on purpose: an app lifespan started later by the same CLI keeps stderr.
    """
    global _use_stderr
    _use_stderr = True


def flush_external_events() -> None:
    if _external is not None:
        _external.flush()


atexit.register(flush_external_events)  # short CLI jobs still report their counted records


def configure_logging(level: str = "INFO", stream: str = "stdout") -> None:
    global _external
    flush_external_events()  # a reconfiguration never drops counts of the previous handler
    target = sys.stderr if _use_stderr or stream == "stderr" else sys.stdout
    handler = logging.StreamHandler(target)
    handler.setFormatter(SafeJsonFormatter())
    _external = ExternalEventCounter(handler)
    handler.addFilter(_external)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Uvicorn installs its own stderr handler before lifespan startup; it would
    # otherwise render raw ASGI exception text/tracebacks outside this allowlist.
    for name in ("uvicorn", "uvicorn.error"):
        server_logger = logging.getLogger(name)
        server_logger.handlers.clear()
        server_logger.propagate = True
    for noisy in ("uvicorn.access", "httpx", "httpcore", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
