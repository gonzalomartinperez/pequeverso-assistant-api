"""One visitor question → at most one bounded model call → one validated answer.

`ChatService.start` performs every check that can refuse a request (availability, input,
rate limits, idempotency, one active run per session, concurrency, budget) before a stream
opens, so refusals are ordinary HTTP errors. The returned `Run` streams events and must be
closed (`aclose`) by whoever opened it; closing is idempotent and releases every resource.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.application.answers import (
    PAYMENT_REFUSAL_ANSWER,
    FinalizedAnswer,
    answer_rules,
    finalize,
    replacement,
)
from app.application.ports import (
    AnswerComposer,
    CatalogView,
    Clock,
    DeltaEvent,
    DraftEvent,
    Ledger,
    MessageStore,
    PreparedTurn,
    RateLimiter,
    RunRecord,
    RunState,
    RunStore,
    Turn,
)
from app.application.runs import RunRegistry
from app.domain.budget import BudgetPolicy, Pricing, cost_micro, worst_case_micro
from app.domain.catalog import ActiveCatalog
from app.domain.conversation import AnswerDetails, Message, Notice, Role, Session
from app.domain.errors import FailureCode, RejectedError
from app.domain.redaction import contains_card_number, redact_contact_data

log = logging.getLogger(__name__)

PAYMENT_PLACEHOLDER = '[mensaje eliminado: contenía datos de pago]'
PAGES = frozenset({'home', 'product', 'support'})


@dataclass(frozen=True, slots=True)
class ChatLimits:
    enabled: bool
    max_message_chars: int
    history_messages: int
    messages_per_session_per_day: int
    messages_per_client_per_hour: int
    max_concurrent_runs: int
    run_timeout: timedelta
    max_input_tokens: int
    max_output_tokens: int
    extra_forbidden_terms: tuple[str, ...] = ()


# --- run events (presentation maps them to the SSE contract) ------------------------------------


@dataclass(frozen=True, slots=True)
class RunStarted:
    run_id: str
    user_message: Message | None


@dataclass(frozen=True, slots=True)
class AnswerDelta:
    text: str


@dataclass(frozen=True, slots=True)
class AnswerCompleted:
    message: Message


@dataclass(frozen=True, slots=True)
class RunFailed:
    code: FailureCode


@dataclass(frozen=True, slots=True)
class RunCancelled:
    pass


RunEvent = RunStarted | AnswerDelta | AnswerCompleted | RunFailed | RunCancelled


class Run(ABC):
    """An accepted run. Iterate `events()` once, then always `aclose()`."""

    def __init__(self, run_id: str) -> None:
        self.id = run_id

    @abstractmethod
    def events(self) -> AsyncIterator[RunEvent]: ...

    async def aclose(self) -> None:
        return None


class ReplayedRun(Run):
    """A retried request whose answer already exists (same Idempotency-Key and payload)."""

    def __init__(self, run_id: str, message: Message) -> None:
        super().__init__(run_id)
        self._message = message

    async def events(self) -> AsyncIterator[RunEvent]:
        yield RunStarted(self.id, None)
        yield AnswerCompleted(self._message)


class _ModelRun(Run):
    def __init__(
        self,
        service: ChatService,
        run_id: str,
        session: Session,
        active: ActiveCatalog,
        prepared: PreparedTurn,
        user_message: Message,
        slot: asyncio.Semaphore,
        cancel: asyncio.Event,
    ) -> None:
        super().__init__(run_id)
        self._service = service
        self._session = session
        self._active = active
        self._prepared = prepared
        self._user_message = user_message
        self._slot = slot
        self._cancel = cancel
        self._state: RunState | None = None
        self._closed = False
        self._started = time.monotonic()

    async def events(self) -> AsyncIterator[RunEvent]:
        yield RunStarted(self.id, self._user_message)
        service = self._service
        # An explicit deadline, checked at every step: each step may resume in a different task,
        # so a task-bound asyncio.timeout() held across yields would never fire.
        deadline = time.monotonic() + service.limits.run_timeout.total_seconds()
        stream = service.composer.compose(self._prepared)
        try:
            while True:
                event = await self._next_or_cancel(stream, deadline)
                if event is None:
                    break
                if isinstance(event, DeltaEvent):
                    if event.text:
                        yield AnswerDelta(event.text)
                    continue
                message = await self._complete(event)
                yield AnswerCompleted(message)
                return
            if self._cancel.is_set():
                await self._finish(RunState.CANCELLED)
                yield RunCancelled()
                return
            await self._finish(RunState.FAILED, FailureCode.GENERATION_FAILED)
            yield RunFailed(FailureCode.GENERATION_FAILED)
        except RejectedError as error:
            await self._finish(RunState.FAILED, error.code)
            yield RunFailed(error.code)
        except TimeoutError:
            await self._finish(RunState.FAILED, FailureCode.TIMEOUT)
            yield RunFailed(FailureCode.TIMEOUT)
        except Exception:
            log.exception('{"operation":"run","outcome":"unexpected_error"}')
            await self._finish(RunState.FAILED, FailureCode.GENERATION_FAILED)
            yield RunFailed(FailureCode.GENERATION_FAILED)
        finally:
            await stream.aclose()

    async def _next_or_cancel(
        self, stream: AsyncGenerator[DeltaEvent | DraftEvent], deadline: float
    ) -> DeltaEvent | DraftEvent | None:
        """Next composer event; None when the stream ended or the run was cancelled."""
        if self._cancel.is_set():
            return None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        step = asyncio.ensure_future(anext(stream))
        cancelled = asyncio.ensure_future(self._cancel.wait())
        try:
            done, _ = await asyncio.wait(
                {step, cancelled}, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            cancelled.cancel()
            if not step.done():
                step.cancel()
                await asyncio.gather(step, return_exceptions=True)
        if step not in done:
            if cancelled in done:
                return None
            raise TimeoutError
        try:
            return step.result()
        except StopAsyncIteration:
            return None

    async def _complete(self, event: DraftEvent) -> Message:
        service = self._service
        now = service.clock.now()
        price_status = self._active.price_status(now)
        rules = answer_rules(self._active.catalog, price_status, service.limits.extra_forbidden_terms)
        final: FinalizedAnswer = finalize(event.draft, self._active, price_status, rules)
        message = Message(_message_id(), Role.ASSISTANT, final.content, now, final.details)
        await service.messages.append(self._session.id, message)
        if event.usage is not None:
            actual = cost_micro(event.usage, service.pricing)
            await service.ledger.settle(self.id, actual, event.usage, service.composer.model)
        await self._finish(RunState.COMPLETED, assistant_message_id=message.id)
        log.info(
            json.dumps(
                {
                    'operation': 'run',
                    'outcome': 'completed',
                    'replaced': bool(final.violations),
                    'violations': [v.value for v in final.violations],
                    'dropped_references': final.dropped_references,
                    'input_tokens': event.usage.input_tokens if event.usage else None,
                    'output_tokens': event.usage.output_tokens if event.usage else None,
                    'latency_ms': round((time.monotonic() - self._started) * 1000),
                }
            )
        )
        return message

    async def _finish(
        self, state: RunState, code: FailureCode | None = None, assistant_message_id: str | None = None
    ) -> None:
        if self._state is not None:
            return
        self._state = state
        await self._service.runs.finish(self.id, state, assistant_message_id)
        if code is not None:
            log.info(json.dumps({'operation': 'run', 'outcome': state.value, 'code': code.value}))

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._state is None:
                # The stream never finished: the client went away or the response was never sent.
                await self._finish(RunState.CANCELLED)
        finally:
            self._slot.release()
            self._service.registry.remove(self.id)


class _StaticRun(Run):
    """A run answered without a model call (e.g. payment data refused)."""

    def __init__(self, run_id: str, user_message: Message, message: Message) -> None:
        super().__init__(run_id)
        self._user_message = user_message
        self._message = message

    async def events(self) -> AsyncIterator[RunEvent]:
        yield RunStarted(self.id, self._user_message)
        yield AnswerCompleted(self._message)


def _message_id() -> str:
    return f'msg_{secrets.token_urlsafe(12)}'


def _request_hash(content: str, page: str | None) -> str:
    return hashlib.sha256(json.dumps([content, page]).encode()).hexdigest()


class ChatService:
    def __init__(
        self,
        *,
        composer: AnswerComposer,
        catalog: CatalogView,
        messages: MessageStore,
        runs: RunStore,
        ledger: Ledger,
        rate_limiter: RateLimiter,
        registry: RunRegistry,
        clock: Clock,
        pricing: Pricing,
        budget: BudgetPolicy,
        limits: ChatLimits,
    ) -> None:
        self.composer = composer
        self.catalog = catalog
        self.messages = messages
        self.runs = runs
        self.ledger = ledger
        self.rate_limiter = rate_limiter
        self.registry = registry
        self.clock = clock
        self.pricing = pricing
        self.budget = budget
        self.limits = limits
        self._slot = asyncio.Semaphore(limits.max_concurrent_runs)

    async def availability(self) -> FailureCode | None:
        """Why a new question would be refused right now, or None when the assistant is available."""
        if not self.limits.enabled:
            return FailureCode.ASSISTANT_DISABLED
        if self.catalog.active is None:
            return FailureCode.CATALOG_UNAVAILABLE
        now = self.clock.now()
        month, day = _periods(now)
        month_spent, day_spent = await self.ledger.spent(month, day)
        if not self.budget.allows(
            month_spent=month_spent, day_spent=day_spent, reservation=self._worst_case()
        ):
            return FailureCode.BUDGET_EXHAUSTED
        return None

    def _worst_case(self) -> int:
        return worst_case_micro(self.limits.max_input_tokens, self.limits.max_output_tokens, self.pricing)

    async def start(
        self,
        session: Session,
        content: str,
        page: str | None,
        idempotency_key: str,
        client_key: str,
    ) -> Run:
        if not self.limits.enabled:
            raise RejectedError(FailureCode.ASSISTANT_DISABLED)
        active = self.catalog.active
        if active is None:
            raise RejectedError(FailureCode.CATALOG_UNAVAILABLE)
        question = content.strip()
        if not question or len(question) > self.limits.max_message_chars:
            raise RejectedError(FailureCode.INVALID_REQUEST)
        if page is not None and page not in PAGES:
            raise RejectedError(FailureCode.INVALID_REQUEST)

        now = self.clock.now()
        run_id = f'run_{secrets.token_urlsafe(12)}'
        record = await self.runs.claim(
            run_id, session.id, idempotency_key, _request_hash(question, page), now
        )
        if record.id != run_id:
            return await self._existing(record, session, question, page)

        try:
            await self._rate_limit(session, client_key, now)
            if contains_card_number(question):
                return await self._refuse_payment_data(run_id, session, now, active)
            redacted = redact_contact_data(question)
            history = await self.messages.history(session.id, self.limits.history_messages)
            turn = Turn(
                active=active,
                price_status=active.price_status(now),
                history=history,
                question=redacted.text,
                page=page,
                safety_identifier=hashlib.sha256(session.id.encode()).hexdigest()[:32],
            )
            prepared = self.composer.prepare(turn)
            if prepared.input_size_bytes > self.limits.max_input_tokens:
                raise RejectedError(FailureCode.INVALID_REQUEST)
            if self._slot.locked():
                raise RejectedError(FailureCode.BUSY)
            await self._slot.acquire()
        except BaseException:
            await self.runs.finish(run_id, RunState.FAILED, None)
            raise

        try:
            reservation = worst_case_micro(
                prepared.input_size_bytes, self.limits.max_output_tokens, self.pricing
            )
            month, day = _periods(now)
            if not await self.ledger.reserve(run_id, reservation, month, day, self.budget.allows):
                raise RejectedError(FailureCode.BUDGET_EXHAUSTED)
            notices = (Notice.CONTACT_DATA_REDACTED,) if redacted.redactions else ()
            user_message = Message(
                _message_id(), Role.USER, redacted.text, now, AnswerDetails(notices=notices)
            )
            await self.messages.append(session.id, user_message)
            cancel = self.registry.add(run_id, session.id)
        except BaseException:
            self._slot.release()
            await self.runs.finish(run_id, RunState.FAILED, None)
            raise
        return _ModelRun(self, run_id, session, active, prepared, user_message, self._slot, cancel)

    async def _existing(self, record: RunRecord, session: Session, question: str, page: str | None) -> Run:
        if record.request_hash != _request_hash(question, page):
            raise RejectedError(FailureCode.IDEMPOTENCY_CONFLICT)
        if record.state is RunState.ACTIVE:
            raise RejectedError(FailureCode.RUN_IN_PROGRESS)
        if record.state is RunState.COMPLETED and record.assistant_message_id:
            message = await self.runs.message(session.id, record.assistant_message_id)
            if message is not None:
                return ReplayedRun(record.id, message)
        raise RejectedError(FailureCode.IDEMPOTENCY_CONFLICT)

    async def _rate_limit(self, session: Session, client_key: str, now: datetime) -> None:
        per_session = await self.rate_limiter.hit(
            f'messages:session:{session.id}', 86400, self.limits.messages_per_session_per_day, now
        )
        per_client = await self.rate_limiter.hit(
            f'messages:client:{client_key}', 3600, self.limits.messages_per_client_per_hour, now
        )
        if not (per_session and per_client):
            raise RejectedError(FailureCode.RATE_LIMITED)

    async def _refuse_payment_data(
        self, run_id: str, session: Session, now: datetime, active: ActiveCatalog
    ) -> Run:
        user_message = Message(
            _message_id(),
            Role.USER,
            PAYMENT_PLACEHOLDER,
            now,
            AnswerDetails(notices=(Notice.PAYMENT_DATA_REFUSED,)),
        )
        await self.messages.append(session.id, user_message)
        answer = Message(
            _message_id(),
            Role.ASSISTANT,
            PAYMENT_REFUSAL_ANSWER,
            now,
            replacement(active.catalog, Notice.PAYMENT_DATA_REFUSED),
        )
        await self.messages.append(session.id, answer)
        await self.runs.finish(run_id, RunState.COMPLETED, answer.id)
        return _StaticRun(run_id, user_message, answer)

    def cancel(self, session: Session, run_id: str) -> None:
        if not self.registry.cancel(run_id, session.id):
            raise RejectedError(FailureCode.RUN_NOT_FOUND)


def _periods(now: datetime) -> tuple[str, str]:
    return now.strftime('%Y-%m'), now.strftime('%Y-%m-%d')
