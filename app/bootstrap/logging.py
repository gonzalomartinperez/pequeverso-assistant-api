"""JSON logs with an allowlist: application log calls pass JSON strings built from safe fields;
anything else (e.g. third-party messages or exception text) is reduced to its logger and level
so conversation content, secrets and exception details never reach the log stream."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime

from app.domain.answer_policy import Violation
from app.domain.errors import FailureCode
from app.domain.language import Language
from app.domain.web_evidence import HelpTopic

# Logger ownership and event schemas are explicit; being JSON is never a trust signal.
_EVENTS: dict[str, dict[str, frozenset[str]]] = {
    'app.request': {'request': frozenset({'method', 'route', 'status', 'duration_ms'})},
    'app.application.chat': {
        'run': frozenset(
            {
                'outcome',
                'code',
                'replaced',
                'violations',
                'dropped_references',
                'input_tokens',
                'output_tokens',
                'reasoning_tokens',
                'language',
                'first_delta_ms',
                'latency_ms',
            }
        ),
        'run_metric': frozenset({'outcome'}),
    },
    'app.application.catalog': {
        'catalog_restore': frozenset({'outcome'}),
        'catalog_refresh': frozenset({'outcome', 'reason', 'sha256'}),
    },
    'app.adapters.openai_provider': {
        'provider_usage': frozenset({'outcome'}),
        'provider_open': frozenset({'outcome', 'error'}),
        'provider_stream': frozenset({'outcome', 'reason'}),
    },
    'app.adapters.official_help': {'official_help': frozenset({'outcome', 'topic'})},
    'app.adapters.observability': {
        'telemetry_export': frozenset({'outcome'}),
        'telemetry_shutdown': frozenset({'outcome'}),
        'telemetry_run_window': frozenset({'outcome'}),
    },
    'app.bootstrap.container': {
        'retention': frozenset({'sessions_deleted', 'outcome'}),
        'startup': frozenset({'abandoned_runs'}),
        'shutdown': frozenset({'outcome'}),
    },
}
_OUTCOMES = frozenset(
    {
        'completed',
        'failed',
        'cancelled',
        'interrupted',
        'refused',
        'unexpected_error',
        'invalid_stored_snapshot',
        'activated',
        'malformed',
        'rejected',
        'response.failed',
        'response.incomplete',
        'error',
        'timeout',
        'cache_hit',
        'unavailable',
        'verified',
        'drain_failed',
    }
)
_ERROR_NAMES = frozenset(
    {
        'Exception',
        'RuntimeError',
        'ValueError',
        'TypeError',
        'TimeoutError',
        'OSError',
        'ConnectionError',
        'OperationalError',
        'DatabaseError',
        'IntegrityError',
        'ValidationError',
        'HTTPError',
        'HTTPStatusError',
        'RequestError',
        'ConnectError',
        'ReadTimeout',
        'ConnectTimeout',
        'APIError',
        'APIConnectionError',
        'APITimeoutError',
        'APIStatusError',
        'RateLimitError',
        'InternalServerError',
        'AuthenticationError',
        'PermissionDeniedError',
        'BadRequestError',
        'NotFoundError',
        'ConflictError',
        'UnprocessableEntityError',
        'APIResponseValidationError',
    }
)
_ROUTES = frozenset(
    {
        'unmatched',
        '/health/live',
        '/health/ready',
        '/api/v1/availability',
        '/api/v1/session',
        '/api/v1/messages',
        '/api/v1/openapi.json',
        '/api/v1/runs/{run_id}/cancel',
        '/internal/v1/ops/summary',
        '/internal/v1/ops/telemetry',
        '/internal/v1/ops/metrics',
    }
)
_NUMBERS = frozenset(
    {
        'duration_ms',
        'first_delta_ms',
        'latency_ms',
        'dropped_references',
        'input_tokens',
        'output_tokens',
        'reasoning_tokens',
        'sessions_deleted',
        'abandoned_runs',
    }
)


def _safe_field(name: str, value: object) -> bool:
    if name in _NUMBERS:
        return value is None or (type(value) is int and 0 <= value <= 10**12)
    if name == 'status':
        return type(value) is int and 100 <= value <= 599
    if name == 'replaced':
        return type(value) is bool
    if name == 'violations':
        return (
            isinstance(value, list)
            and len(value) <= len(Violation)
            and all(isinstance(item, str) and item in {v.value for v in Violation} for item in value)
        )
    if not isinstance(value, str):
        return False
    allowed = {
        'outcome': _OUTCOMES,
        'method': frozenset({'GET', 'POST', 'DELETE', 'OPTIONS', 'HEAD', 'PUT', 'PATCH'}),
        'route': _ROUTES,
        'code': frozenset(v.value for v in FailureCode),
        'language': frozenset(v.value for v in Language),
        'topic': frozenset(v.value for v in HelpTopic),
        'error': _ERROR_NAMES,
        'reason': _ERROR_NAMES | {'max_output_tokens', 'content_filter', 'none'},
    }
    if name == 'sha256':
        return re.fullmatch('[0-9a-f]{12}', value) is not None
    return value in allowed.get(name, frozenset())


class SafeJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            'ts': datetime.fromtimestamp(record.created, UTC).isoformat(timespec='milliseconds'),
            'level': logging.getLevelName(record.levelno).lower(),
            'logger': record.name if record.name in _EVENTS or record.name == 'uvicorn.error' else 'external',
        }
        payload = None
        # External records are not evaluated at all: even getMessage may execute a custom
        # __str__, and parser failures must never reach logging's raw-message fallback.
        if record.name in _EVENTS:
            try:
                payload = json.loads(record.getMessage())
            except (TypeError, ValueError, RecursionError):
                payload = None
        entry['operation'] = 'unstructured_event'
        if isinstance(payload, dict) and isinstance(operation := payload.get('operation'), str):
            fields = _EVENTS.get(record.name, {}).get(operation)
            if fields is not None:
                entry['operation'] = operation
                entry.update(
                    {
                        name: value
                        for name, value in payload.items()
                        if name in fields and _safe_field(name, value)
                    }
                )
        if record.exc_info and record.exc_info[0] is not None:
            kind = record.exc_info[0].__name__
            entry['exception'] = kind if kind in _ERROR_NAMES else 'Exception'
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(level: str = 'INFO') -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(SafeJsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Uvicorn installs its own stderr handler before lifespan startup; it would
    # otherwise render raw ASGI exception text/tracebacks outside this allowlist.
    for name in ('uvicorn', 'uvicorn.error'):
        server_logger = logging.getLogger(name)
        server_logger.handlers.clear()
        server_logger.propagate = True
    for noisy in ('uvicorn.access', 'httpx', 'openai'):
        logging.getLogger(noisy).setLevel(logging.WARNING)
