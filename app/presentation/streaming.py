"""SSE encoding, keep-alive comments and guaranteed run cleanup."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from typing import Any

from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from app.application.chat import (
    AnswerCompleted,
    AnswerDelta,
    Run,
    RunCancelled,
    RunEvent,
    RunFailed,
    RunStarted,
)
from app.application.ports import Clock
from app.domain.errors import RETRYABLE, FailureCode
from app.presentation.events import (
    MessageCompletedEvent,
    MessageDeltaEvent,
    RunCancelledEvent,
    RunCompletedEvent,
    RunFailedEvent,
    RunStartedEvent,
)
from app.presentation.schemas import MessageOut

SSE_HEADERS = {
    'Cache-Control': 'no-cache, no-store, no-transform',
    'X-Accel-Buffering': 'no',
    'Connection': 'keep-alive',
}
STREAM_FAILURES = frozenset(
    {
        'budget_exhausted',
        'provider_unavailable',
        'generation_failed',
        'timeout',
        'catalog_unavailable',
        'busy',
    }
)


def encode(event: Any) -> bytes:
    return f'id: {event.sequence}\nevent: {event.type}\ndata: {event.model_dump_json()}\n\n'.encode()


def _wire(event: RunEvent, run_id: str, sequence: int, clock: Clock) -> list[Any]:
    base = {'run_id': run_id, 'timestamp': clock.now()}
    match event:
        case RunStarted(user_message=message):
            return [
                RunStartedEvent(
                    **base, sequence=sequence, user_message=MessageOut.of(message) if message else None
                )
            ]
        case AnswerDelta(text=text):
            return [MessageDeltaEvent(**base, sequence=sequence, text=text)]
        case AnswerCompleted(message=message):
            return [
                MessageCompletedEvent(**base, sequence=sequence, message=MessageOut.of(message)),
                RunCompletedEvent(**base, sequence=sequence + 1),
            ]
        case RunFailed(code=code):
            wire_code = code.value if code.value in STREAM_FAILURES else FailureCode.GENERATION_FAILED.value
            return [RunFailedEvent(**base, sequence=sequence, code=wire_code, retryable=code in RETRYABLE)]
        case RunCancelled():
            return [RunCancelledEvent(**base, sequence=sequence)]
    raise TypeError(type(event).__name__)


async def sse_body(run: Run, clock: Clock, heartbeat_seconds: float) -> AsyncGenerator[bytes]:
    sequence = 0
    terminal = False
    events = run.events()
    pending: asyncio.Future[RunEvent] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(anext(events))
            done, _ = await asyncio.wait({pending}, timeout=heartbeat_seconds)
            if not done:
                yield b': keep-alive\n\n'
                continue
            try:
                event = pending.result()
            except StopAsyncIteration:
                break
            finally:
                pending = None
            for wire in _wire(event, run.id, sequence, clock):
                sequence += 1
                terminal = terminal or wire.type in ('run.completed', 'run.failed', 'run.cancelled')
                yield encode(wire)
        if not terminal:
            failed = RunFailedEvent(
                run_id=run.id,
                sequence=sequence,
                timestamp=clock.now(),
                code='generation_failed',
                retryable=True,
            )
            yield encode(failed)
    finally:
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await _aclose(events)


async def _aclose(events: AsyncIterator[RunEvent]) -> None:
    close = getattr(events, 'aclose', None)
    if close is not None:
        await close()


class ResponseCleanups:
    """Application-owned finalizers: no cross-app or cross-event-loop global state."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Future[None]] = set()

    def track(self, task: asyncio.Future[None]) -> None:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        # Give cancelled response tasks a turn to register their finally blocks.
        await asyncio.sleep(0)
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks))


class ClosingStreamingResponse(StreamingResponse):
    """Runs `on_close` after the response ends for any reason, including a client disconnect
    or a send error, shielded from cancellation and bounded in time."""

    def __init__(
        self,
        content: AsyncGenerator[bytes],
        on_close: Callable[[], Awaitable[None]],
        cleanups: ResponseCleanups,
        **kwargs: Any,
    ) -> None:
        super().__init__(content, **kwargs)
        self._generator = content
        self._on_close = on_close
        self._cleanups = cleanups

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            # A strong reference keeps the cleanup alive even if this task is cancelled again.
            task = asyncio.ensure_future(self._cleanup())
            self._cleanups.track(task)
            async with asyncio.timeout(10):
                await asyncio.shield(task)

    async def _cleanup(self) -> None:
        try:
            await self._generator.aclose()
        finally:
            await self._on_close()
