"""JSON logs with an allowlist: application log calls pass JSON strings built from safe fields;
anything else (e.g. third-party messages or exception text) is reduced to its logger and level
so conversation content, secrets and exception details never reach the log stream."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime


class SafeJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            'ts': datetime.fromtimestamp(record.created, UTC).isoformat(timespec='milliseconds'),
            'level': record.levelname.lower(),
            'logger': record.name,
        }
        try:
            payload = json.loads(record.getMessage())
        except (TypeError, ValueError):
            payload = None
        if isinstance(payload, dict):
            entry.update(payload)
        else:
            entry['operation'] = 'unstructured_event'
        if record.exc_info and record.exc_info[0] is not None:
            entry['exception'] = record.exc_info[0].__name__
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
