"""Pure ASGI middleware (streaming-safe): request context and safe logging, body limits and the
origin policy for state-changing requests.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import time
from collections.abc import Iterable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.domain.errors import RETRYABLE, FailureCode

log = logging.getLogger('app.request')

_REQUEST_ID = re.compile(r'^[A-Za-z0-9-]{8,64}$')
UNSAFE_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})
_MESSAGES = {
    FailureCode.INVALID_REQUEST: 'The request is invalid.',
    FailureCode.ORIGIN_DENIED: 'Origin not allowed.',
    FailureCode.CSRF_FAILED: 'Missing or invalid CSRF token.',
    FailureCode.SESSION_EXPIRED: 'No active session; open a new one.',
    FailureCode.RATE_LIMITED: 'Too many requests; try again later.',
    FailureCode.BUSY: 'The assistant is busy; retry shortly.',
    FailureCode.RUN_IN_PROGRESS: 'Another answer is still being generated for this session.',
    FailureCode.IDEMPOTENCY_CONFLICT: 'This Idempotency-Key was already used for a different or failed request.',
    FailureCode.RUN_NOT_FOUND: 'No active run with this id in this session.',
    FailureCode.BUDGET_EXHAUSTED: 'The assistant reached its usage budget for now.',
    FailureCode.ASSISTANT_DISABLED: 'The assistant is disabled.',
    FailureCode.CATALOG_UNAVAILABLE: 'Catalog data is unavailable.',
    FailureCode.PROVIDER_UNAVAILABLE: 'The answer service is unavailable.',
    FailureCode.GENERATION_FAILED: 'The answer could not be generated.',
    FailureCode.TIMEOUT: 'The answer took too long.',
    FailureCode.DEPENDENCY_UNAVAILABLE: 'A dependency is unavailable.',
}
STATUS = {
    FailureCode.INVALID_REQUEST: 422,
    FailureCode.ORIGIN_DENIED: 403,
    FailureCode.CSRF_FAILED: 403,
    FailureCode.SESSION_EXPIRED: 401,
    FailureCode.RATE_LIMITED: 429,
    FailureCode.BUSY: 503,
    FailureCode.RUN_IN_PROGRESS: 409,
    FailureCode.IDEMPOTENCY_CONFLICT: 409,
    FailureCode.RUN_NOT_FOUND: 404,
    FailureCode.BUDGET_EXHAUSTED: 503,
    FailureCode.ASSISTANT_DISABLED: 503,
    FailureCode.CATALOG_UNAVAILABLE: 503,
    FailureCode.PROVIDER_UNAVAILABLE: 503,
    FailureCode.GENERATION_FAILED: 502,
    FailureCode.TIMEOUT: 504,
    FailureCode.DEPENDENCY_UNAVAILABLE: 503,
}
RETRY_AFTER = {FailureCode.BUSY: '5', FailureCode.RATE_LIMITED: '600', FailureCode.BUDGET_EXHAUSTED: '3600'}


def error_payload(code: FailureCode, request_id: str) -> dict[str, object]:
    return {
        'error': {
            'code': code.value,
            'message': _MESSAGES[code],
            'retryable': code in RETRYABLE,
            'request_id': request_id,
        }
    }


def request_id_of(scope: Scope) -> str:
    return str(scope.get('state', {}).get('request_id', 'unknown'))


async def send_error(scope: Scope, send: Send, code: FailureCode) -> None:
    body = json.dumps(error_payload(code, request_id_of(scope))).encode()
    headers = [(b'content-type', b'application/json'), (b'content-length', str(len(body)).encode())]
    if code in RETRY_AFTER:
        headers.append((b'retry-after', RETRY_AFTER[code].encode()))
    await send({'type': 'http.response.start', 'status': STATUS[code], 'headers': headers})
    await send({'type': 'http.response.body', 'body': body})


class RequestContextMiddleware:
    """Request id, baseline security headers and one log line per request (route template,
    status and duration only: no path parameters, query, body, cookies or client address)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        incoming = dict(scope['headers']).get(b'x-request-id', b'').decode('latin-1')
        request_id = incoming if _REQUEST_ID.match(incoming) else secrets.token_hex(8)
        scope.setdefault('state', {})['request_id'] = request_id
        started = time.monotonic()
        status = 500

        async def send_with_headers(message: Message) -> None:
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
                headers = list(message.get('headers', []))
                names = {name.lower() for name, _ in headers}
                headers.append((b'x-request-id', request_id.encode()))
                headers.append((b'x-content-type-options', b'nosniff'))
                headers.append((b'referrer-policy', b'no-referrer'))
                headers.append((b'cross-origin-resource-policy', b'same-site'))
                if b'cache-control' not in names:
                    headers.append((b'cache-control', b'no-store'))
                message['headers'] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            route = scope.get('route')
            log.info(
                json.dumps(
                    {
                        'operation': 'request',
                        'method': scope['method'],
                        'route': getattr(route, 'path', 'unmatched'),
                        'status': status,
                        'duration_ms': round((time.monotonic() - started) * 1000),
                        'request_id': request_id,
                    }
                )
            )


class BodyLimitMiddleware:
    """Buffers request bodies up to `max_bytes`, whatever Content-Length claims."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http' or scope['method'] not in UNSAFE_METHODS:
            await self.app(scope, receive, send)
            return
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            chunk = message.get('body', b'')
            size += len(chunk)
            if size > self.max_bytes:
                await send_error(scope, send, FailureCode.INVALID_REQUEST)
                return
            chunks.append(chunk)
            if not message.get('more_body', False):
                break
        body = b''.join(chunks)
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return await receive()

        await self.app(scope, replay, send)


class OriginMiddleware:
    """State-changing API requests must come from an allowlisted browser origin. This complements
    (never replaces) the session CSRF token."""

    def __init__(self, app: ASGIApp, allowed_origins: Iterable[str], prefix: str = '/api/') -> None:
        self.app = app
        self.allowed = frozenset(allowed_origins)
        self.prefix = prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope['type'] == 'http'
            and scope['method'] in UNSAFE_METHODS
            and scope['path'].startswith(self.prefix)
        ):
            origin = dict(scope['headers']).get(b'origin', b'').decode('latin-1')
            if origin not in self.allowed:
                await send_error(scope, send, FailureCode.ORIGIN_DENIED)
                return
        await self.app(scope, receive, send)
