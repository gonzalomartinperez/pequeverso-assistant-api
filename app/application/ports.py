"""Ports the use cases depend on. Adapters implement them; nothing here knows FastAPI, SQLite or
a model SDK.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from app.domain.budget import Usage
from app.domain.catalog import ActiveCatalog, Catalog, PriceStatus
from app.domain.conversation import Message, Session
from app.domain.errors import FailureCode, RejectedError
from app.domain.language import Language
from app.domain.visitor_context import VisitorContext


class Clock(Protocol):
    def now(self) -> datetime: ...


class SessionStore(Protocol):
    async def create(self, session: Session, secret_digest: bytes) -> None: ...
    async def find(self, secret_digest: bytes, now: datetime) -> Session | None: ...
    async def touch(self, session_id: str, now: datetime, expires_at: datetime) -> None: ...
    async def delete(self, session_id: str) -> None: ...
    async def purge_expired(self, now: datetime) -> int: ...


class MessageStore(Protocol):
    async def append(self, session_id: str, message: Message) -> None: ...
    async def history(self, session_id: str, limit: int) -> list[Message]: ...


class RunState(StrEnum):
    ACTIVE = 'active'
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'


@dataclass(frozen=True, slots=True)
class RunRecord:
    id: str
    session_id: str
    request_hash: str
    state: RunState
    assistant_message_id: str | None


class RunStore(Protocol):
    async def claim(
        self, run_id: str, session_id: str, idempotency_key: str, request_hash: str, now: datetime
    ) -> RunRecord:
        """Insert a new active run, or return the run already recorded for this key."""
        ...

    async def finish(self, run_id: str, state: RunState, assistant_message_id: str | None) -> None: ...
    async def message(self, session_id: str, message_id: str) -> Message | None: ...
    async def abandon_active(self) -> int:
        """Mark runs left active by a previous process as failed (startup recovery)."""
        ...


class Ledger(Protocol):
    """Spend in micro-dollars. A row is *pending* while its run is active, *settled* to the
    provider-reported usage, or *unreported* when the run ended without a usage report (the
    worst-case reservation then stays counted as an estimate; absence never implies a refund)."""

    async def reserve(
        self, run_id: str, reservation_micro: int, month: str, day: str, allows: BudgetCheck
    ) -> bool: ...
    async def settle(self, run_id: str, actual_micro: int, usage: Usage, model: str) -> None: ...
    async def mark_unreported(self, run_id: str) -> None:
        """Close a still-pending reservation without usage (no-op when already closed)."""
        ...

    async def abandon_pending(self) -> int:
        """Startup recovery: pending rows of a previous process become unreported."""
        ...

    async def spent(self, month: str, day: str) -> tuple[int, int]: ...


class RunOutcome(StrEnum):
    COMPLETED = 'completed'
    FAILED = 'failed'
    CANCELLED = 'cancelled'
    INTERRUPTED = 'interrupted'
    """The client went away (or the process stopped) before a terminal event was sent."""
    REFUSED = 'refused'
    """Refused before any stream opened (rate limit, busy, budget, invalid input)."""


@dataclass(frozen=True, slots=True)
class RunMetric:
    """Content-free record of one accepted run, kept for operations (no session id, no text)."""

    run_id: str
    started_at: datetime
    ended_at: datetime
    outcome: RunOutcome
    code: FailureCode | None
    model_call: bool
    replaced: bool
    language: Language | None
    first_delta_ms: int | None
    total_ms: int


class RunMetrics(Protocol):
    async def record(self, metric: RunMetric) -> None: ...


class BudgetCheck(Protocol):
    def __call__(self, *, month_spent: int, day_spent: int, reservation: int) -> bool: ...


class RateLimiter(Protocol):
    async def hit(self, key: str, window_seconds: int, limit: int, now: datetime) -> bool:
        """Count one event; False when the window already holds `limit` events."""
        ...


class CatalogView(Protocol):
    @property
    def active(self) -> ActiveCatalog | None: ...


class CatalogSource(Protocol):
    @property
    def live(self) -> bool:
        """True when a successful fetch confirms the facts are current right now (a published
        storefront document); False for a bundled snapshot, whose facts date from its export."""
        ...

    async def fetch(self) -> bytes: ...


class CatalogParser(Protocol):
    def __call__(self, body: bytes) -> Catalog: ...


@dataclass(frozen=True, slots=True)
class StoredSnapshot:
    sha256: str
    body: bytes
    verified_at: datetime


class CatalogRepository(Protocol):
    async def active(self) -> StoredSnapshot | None: ...
    async def activate(
        self, sha256: str, body: bytes, catalog: Catalog, verified_at: datetime, attempted_at: datetime
    ) -> None: ...
    async def mark_verified(self, sha256: str, verified_at: datetime, attempted_at: datetime) -> None: ...
    async def record_failure(self, reason: str, now: datetime) -> None: ...


# --- answer composition -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Turn:
    """Everything the composer may use for one answer. `question` is already redacted."""

    active: ActiveCatalog
    price_status: PriceStatus
    history: Sequence[Message]
    question: str
    page: str | None
    safety_identifier: str
    language: Language = Language.ES
    context: VisitorContext | None = None


@dataclass(frozen=True, slots=True)
class DraftReference:
    kind: str
    id: str


@dataclass(frozen=True, slots=True)
class Draft:
    """A model answer before validation: every id is still a claim to check against the catalog."""

    answer: str
    references: tuple[DraftReference, ...]
    sources: tuple[str, ...]
    follow_ups: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DeltaEvent:
    text: str


@dataclass(frozen=True, slots=True)
class DraftEvent:
    draft: Draft
    usage: Usage | None


ComposerEvent = DeltaEvent | DraftEvent


class GenerationError(RejectedError):
    """A provider failure after the call was made; carries the usage it reported, if any."""

    def __init__(self, code: FailureCode, usage: Usage | None) -> None:
        super().__init__(code)
        self.usage = usage


class PreparedTurn(Protocol):
    @property
    def input_size_bytes(self) -> int: ...


class AnswerComposer(Protocol):
    @property
    def model(self) -> str: ...

    def prepare(self, turn: Turn) -> PreparedTurn: ...

    def compose(self, prepared: PreparedTurn) -> AsyncGenerator[ComposerEvent]:
        """Stream deltas, then exactly one DraftEvent. Closing the iterator cancels upstream work."""
        ...
