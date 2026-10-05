"""HTTP routes of the v1 API. Paths include the public `/api` prefix, so the proxy forwards
`/api/*` unchanged (no prefix stripping). Health endpoints are unprefixed and internal.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.application.catalog import CatalogService
from app.application.chat import ChatService
from app.application.ports import Clock
from app.application.sessions import SessionService
from app.application.starters import starters
from app.domain.conversation import Session
from app.domain.errors import FailureCode, RejectedError
from app.domain.language import Language
from app.presentation.middleware import RETRY_AFTER, STATUS, error_payload, request_id_of
from app.presentation.schemas import (
    AvailabilityOut,
    ErrorOut,
    LimitsOut,
    MessageIn,
    MessageOut,
    SessionIn,
    SessionOut,
)
from app.presentation.streaming import SSE_HEADERS, ClosingStreamingResponse, sse_body

_IDEMPOTENCY_KEY = re.compile(r'^[A-Za-z0-9_-]{8,128}$')
_UNAVAILABLE = {FailureCode.ASSISTANT_DISABLED, FailureCode.CATALOG_UNAVAILABLE, FailureCode.BUDGET_EXHAUSTED}


@dataclass(frozen=True, slots=True)
class CookiePolicy:
    name: str
    secure: bool
    samesite: Literal['lax', 'strict']
    max_age_seconds: int


@dataclass(frozen=True, slots=True)
class HttpSettings:
    cookie: CookiePolicy
    trusted_proxies: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]
    client_hash_key: bytes
    heartbeat_seconds: float
    max_message_chars: int
    messages_per_day: int


@dataclass(frozen=True, slots=True)
class Services:
    sessions: SessionService
    chat: ChatService
    catalog: CatalogService
    clock: Clock
    settings: HttpSettings
    ready: Callable[[], Awaitable[bool]]


def services(request: Request) -> Services:
    value: Services = request.app.state.services
    return value


ServicesDep = Annotated[Services, Depends(services)]


def client_ip(request: Request, trusted: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]) -> str:
    """Peer address, or the right-most untrusted X-Forwarded-For hop when the peer is a trusted proxy."""
    peer = request.client.host if request.client else ''
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return peer or 'unknown'
    if not any(address in network for network in trusted):
        return str(address)
    header = request.headers.get('x-forwarded-for', '')
    hops = [hop.strip() for hop in header.split(',') if hop.strip()]
    if not hops or len(hops) > 5:
        return str(address)
    for hop in reversed(hops):
        try:
            candidate = ipaddress.ip_address(hop)
        except ValueError:
            return str(address)
        if not any(candidate in network for network in trusted):
            return str(candidate)
    return str(address)


def client_key(request: Request, settings: HttpSettings) -> str:
    ip = client_ip(request, settings.trusted_proxies)
    return hmac.new(settings.client_hash_key, ip.encode(), hashlib.sha256).hexdigest()[:24]


def _set_cookie(response: Response, policy: CookiePolicy, secret: str) -> None:
    response.set_cookie(
        policy.name,
        secret,
        max_age=policy.max_age_seconds,
        httponly=True,
        secure=policy.secure,
        samesite=policy.samesite,
        path='/',
    )


def _require_json(request: Request) -> None:
    if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
        raise RejectedError(FailureCode.INVALID_REQUEST)


async def _availability(chat: ChatService) -> AvailabilityOut:
    code = await chat.availability()
    if code is None:
        return AvailabilityOut(status='available')
    reason = code.value if code in _UNAVAILABLE else 'catalog_unavailable'
    return AvailabilityOut(status='unavailable', reason=reason)


ERRORS: dict[int | str, dict[str, object]] = {
    status: {'model': ErrorOut} for status in (401, 403, 409, 422, 429, 503)
}
router = APIRouter(prefix='/api/v1', responses=ERRORS)


@router.get('/availability', response_model=AvailabilityOut, summary='Whether new questions are accepted')
async def availability(s: ServicesDep) -> AvailabilityOut:
    return await _availability(s.chat)


@router.post(
    '/session',
    response_model=SessionOut,
    summary='Open (restore or create) the caller-owned session',
    responses={201: {'model': SessionOut, 'description': 'A new session was created.'}},
)
async def open_session(
    request: Request, response: Response, s: ServicesDep, body: SessionIn | None = None
) -> SessionOut:
    _require_json(request)
    locale = Language(body.locale) if body and body.locale else Language.ES
    active = s.catalog.active
    policy = s.settings.cookie
    opened = await s.sessions.open(request.cookies.get(policy.name), client_key(request, s.settings))
    created = opened.secret is not None and opened.secret != request.cookies.get(policy.name)
    if opened.secret:
        _set_cookie(response, policy, opened.secret)
    response.status_code = 201 if created else 200
    return SessionOut(
        csrf_token=opened.session.csrf_token,
        expires_at=opened.session.expires_at,
        created=created,
        messages=[MessageOut.of(m) for m in opened.history],
        availability=await _availability(s.chat),
        limits=LimitsOut(
            max_message_chars=s.settings.max_message_chars, messages_per_day=s.settings.messages_per_day
        ),
        starters=list(starters(active.catalog, locale)) if active else [],
    )


async def mutation_session(
    request: Request,
    s: ServicesDep,
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> Session:
    return await s.sessions.require(request.cookies.get(s.settings.cookie.name), x_csrf_token)


SessionDep = Annotated[Session, Depends(mutation_session)]


@router.delete('/session', status_code=204, summary='Delete the session and its whole conversation')
async def delete_session(session: SessionDep, s: ServicesDep) -> Response:
    await s.sessions.delete(session)
    response = Response(status_code=204)
    response.delete_cookie(
        s.settings.cookie.name,
        path='/',
        secure=s.settings.cookie.secure,
        httponly=True,
        samesite=s.settings.cookie.samesite,
    )
    return response


@router.post(
    '/messages',
    summary='Ask a question; the answer streams as Server-Sent Events',
    response_class=ClosingStreamingResponse,
    status_code=200,
    responses={200: {'content': {'text/event-stream': {}}, 'description': 'See contracts/sse.schema.json.'}},
)
async def post_message(
    request: Request,
    body: MessageIn,
    session: SessionDep,
    s: ServicesDep,
    idempotency_key: Annotated[str, Header()],
) -> ClosingStreamingResponse:
    _require_json(request)
    if not _IDEMPOTENCY_KEY.match(idempotency_key):
        raise RejectedError(FailureCode.INVALID_REQUEST)
    run = await s.chat.start(
        session, body.content, body.page, idempotency_key, client_key(request, s.settings), body.locale
    )
    await s.sessions.touch(session)
    response = ClosingStreamingResponse(
        sse_body(run, s.clock, s.settings.heartbeat_seconds),
        on_close=run.aclose,
        media_type='text/event-stream',
        headers={**SSE_HEADERS, 'X-Run-ID': run.id},
    )
    _set_cookie(response, s.settings.cookie, request.cookies[s.settings.cookie.name])
    return response


@router.post('/runs/{run_id}/cancel', status_code=202, summary="Cancel the caller's active run")
async def cancel_run(run_id: str, session: SessionDep, s: ServicesDep) -> Response:
    s.chat.cancel(session, run_id)
    return Response(status_code=202)


health = APIRouter(prefix='/health', include_in_schema=False)


@health.get('/live')
async def live() -> dict[str, str]:
    return {'status': 'ok'}


@health.get('/ready')
async def ready(s: ServicesDep) -> JSONResponse:
    ok = await s.ready()
    active = s.catalog.active
    body: dict[str, object] = {'status': 'ready' if ok else 'not_ready'}
    if active is not None:
        body['catalog'] = {
            'revision': active.catalog.source_revision[:12],
            'price_status': active.price_status(s.clock.now()).value,
        }
    return JSONResponse(body, status_code=200 if ok else 503)


def install_error_handlers(app: FastAPI) -> None:
    def respond(request: Request, code: FailureCode) -> JSONResponse:
        headers = {'Retry-After': RETRY_AFTER[code]} if code in RETRY_AFTER else None
        return JSONResponse(
            error_payload(code, request_id_of(request.scope)), status_code=STATUS[code], headers=headers
        )

    @app.exception_handler(RejectedError)
    async def rejected(request: Request, error: RejectedError) -> JSONResponse:
        return respond(request, error.code)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, _: RequestValidationError) -> JSONResponse:
        return respond(request, FailureCode.INVALID_REQUEST)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        payload = {
            'error': {
                'code': 'not_found' if error.status_code == 404 else 'invalid_request',
                'message': 'Not found.' if error.status_code == 404 else 'Request not supported.',
                'retryable': False,
                'request_id': request_id_of(request.scope),
            }
        }
        return JSONResponse(payload, status_code=error.status_code)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, _: Exception) -> JSONResponse:
        return respond(request, FailureCode.DEPENDENCY_UNAVAILABLE)
