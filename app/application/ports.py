"""Define the adapter interfaces used by application services."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from app.domain.errors import FailureCode, RejectedError
from app.domain.language import Language

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Sequence
    from datetime import datetime

    from app.domain.budget import Usage
    from app.domain.catalog import ActiveCatalog, Catalog, PriceStatus
    from app.domain.conversation import Message, Session
    from app.domain.visitor_context import VisitorContext
    from app.domain.web_evidence import HelpTopic, WebEvidence


class Clock(Protocol):
    """Provide the current time to application services."""

    def now(self) -> datetime:
        """Return the current time."""
        ...


class SessionStore(Protocol):
    """Persist and look up anonymous sessions."""

    async def create(self, session: Session, secret_digest: bytes) -> None:
        """Store a new session with its ownership digest."""
        ...

    async def find(self, secret_digest: bytes, now: datetime) -> Session | None:
        """Return the unexpired session for the digest, if one exists."""
        ...

    async def touch(self, session_id: str, now: datetime, expires_at: datetime) -> None:
        """Update the session's activity and expiry timestamps."""
        ...

    async def delete(self, session_id: str) -> None:
        """Delete the session and its conversation."""
        ...

    async def purge_expired(self, now: datetime) -> int:
        """Delete expired sessions and return the number removed."""
        ...


class MessageStore(Protocol):
    """Store conversation messages by session."""

    async def append(self, session_id: str, message: Message) -> None:
        """Append a message to the session's conversation."""
        ...

    async def history(self, session_id: str, limit: int) -> list[Message]:
        """Return up to the requested number of recent messages, oldest first."""
        ...


class RunState(StrEnum):
    """Identify the persisted lifecycle state of a run."""

    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class RunRecord:
    """Record a run's identity, request fingerprint, state, and optional answer ID."""

    id: str
    session_id: str
    request_hash: str
    state: RunState
    assistant_message_id: str | None


class RunStore(Protocol):
    """Persist run claims and results for idempotent requests."""

    async def claim(
        self, run_id: str, session_id: str, idempotency_key: str, request_hash: str, now: datetime
    ) -> RunRecord:
        """Insert a new active run, or return the run already recorded for this key."""
        ...

    async def finish(self, run_id: str, state: RunState, assistant_message_id: str | None) -> None:
        """Record the run's final state and optional assistant message ID."""
        ...

    async def message(self, session_id: str, message_id: str) -> Message | None:
        """Look up a message by ID within the given session."""
        ...

    async def abandon_active(self) -> int:
        """Mark runs left active by a previous process as failed (startup recovery)."""
        ...


class Ledger(Protocol):
    """Track run spend in micro-dollars.

    A row is pending while the run is active and settled once the provider reports usage. If the
    run ends without a usage report, mark it unreported and retain the worst-case estimate.
    """

    async def reserve(
        self, run_id: str, reservation_micro: int, month: str, day: str, allows: BudgetCheck
    ) -> bool:
        """Reserve spend only if the budget check allows it."""
        ...

    async def settle(self, run_id: str, actual_micro: int, usage: Usage, model: str) -> None:
        """Settle the reservation to the reported cost and record usage and model."""
        ...

    async def mark_unreported(self, run_id: str) -> None:
        """Close a still-pending reservation without usage (no-op when already closed)."""
        ...

    async def abandon_pending(self) -> int:
        """Startup recovery: pending rows of a previous process become unreported."""
        ...

    async def spent(self, month: str, day: str) -> tuple[int, int]:
        """Return counted spend for the given month and day, in that order."""
        ...


class RunOutcome(StrEnum):
    """Classify run outcomes for operations reporting."""

    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    """The client went away (or the process stopped) before a terminal event was sent."""
    REFUSED = "refused"
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
    """Persist content-free run metrics."""

    async def record(self, metric: RunMetric) -> None:
        """Record the metrics for a run."""
        ...


class BudgetCheck(Protocol):
    """Decide whether a reservation fits within the spend limits."""

    def __call__(self, *, month_spent: int, day_spent: int, reservation: int) -> bool:
        """Check the proposed reservation against the current monthly and daily spend."""
        ...


class RateLimiter(Protocol):
    """Enforce event limits for keyed time windows."""

    async def hit(self, key: str, window_seconds: int, limit: int, now: datetime) -> bool:
        """Count one event; False when the window already holds `limit` events."""
        ...


class CatalogView(Protocol):
    """Expose the active catalog and its synchronization state."""

    @property
    def active(self) -> ActiveCatalog | None:
        """Return the active catalog, if one is available."""
        ...

    @property
    def synchronized(self) -> bool:
        """Report whether the latest fetch was validated and bound to an active snapshot."""
        ...


class OfficialHelp(Protocol):
    """Supply approved help evidence for requested topics."""

    async def read(self, topics: tuple[HelpTopic, ...]) -> tuple[WebEvidence, ...]:
        """Read official help evidence for the requested topics."""
        ...


class CatalogSource(Protocol):
    """Supply catalog documents and identify their freshness semantics."""

    @property
    def live(self) -> bool:
        """Indicate whether a successful fetch can confirm current facts.

        A published storefront document confirms facts at fetch time. A bundled snapshot reflects
        the facts at its export time.
        """
        ...

    async def fetch(self) -> bytes:
        """Fetch the catalog document as bytes."""
        ...


class CatalogParser(Protocol):
    """Convert raw catalog documents into domain catalogs."""

    def __call__(self, body: bytes) -> Catalog:
        """Parse the document bytes into a catalog."""
        ...


@dataclass(frozen=True, slots=True)
class StoredSnapshot:
    """Hold the active snapshot's content, digest, and verification time."""

    sha256: str
    body: bytes
    verified_at: datetime


class CatalogRepository(Protocol):
    """Persist catalog snapshots and synchronization results."""

    async def active(self) -> StoredSnapshot | None:
        """Return the stored active snapshot, if one exists."""
        ...

    async def activate(
        self,
        sha256: str,
        body: bytes,
        catalog: Catalog,
        verified_at: datetime,
        attempted_at: datetime,
    ) -> None:
        """Store and activate the supplied snapshot with its verification and attempt times."""
        ...

    async def mark_verified(
        self, sha256: str, verified_at: datetime, attempted_at: datetime
    ) -> None:
        """Refresh verification and attempt times for the unchanged snapshot."""
        ...

    async def record_failure(self, reason: str, now: datetime) -> None:
        """Record a failed synchronization attempt with its time and reason."""
        ...


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
    web_evidence: tuple[WebEvidence, ...] = ()
    input_size_limit: int | None = None


@dataclass(frozen=True, slots=True)
class DraftReference:
    """Identify an unvalidated reference by kind and ID."""

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
    """Carry a provisional fragment of answer text."""

    text: str


@dataclass(frozen=True, slots=True)
class DraftEvent:
    """Carry the completed draft and any reported usage."""

    draft: Draft
    usage: Usage | None


ComposerEvent = DeltaEvent | DraftEvent


class GenerationError(RejectedError):
    """A provider failure after the call was made; carries the usage it reported, if any."""

    def __init__(self, code: FailureCode, usage: Usage | None) -> None:
        """Initialize the rejection with its failure code and any reported usage."""
        super().__init__(code)
        self.usage = usage


class PreparedTurn(Protocol):
    """Expose the evidence and input size for a turn prepared for composition."""

    @property
    def web_evidence(self) -> tuple[WebEvidence, ...]:
        """Return the official help evidence included in the prepared turn."""
        ...

    @property
    def catalog_source_ids(self) -> frozenset[str]:
        """Return the IDs of catalog sources included in the prepared turn."""
        ...

    @property
    def input_size_bytes(self) -> int:
        """Return the generation input size in bytes used to size the reservation."""
        ...


@runtime_checkable
class DispatchAwarePreparedTurn(PreparedTurn, Protocol):
    """An explicit signal distinguishes retrieval work from a generation attempt."""

    @property
    def generation_started(self) -> bool:
        """Report whether the generation attempt has started."""
        ...


class AnswerComposer(Protocol):
    """Prepare inputs and stream the result of answer composition."""

    @property
    def model(self) -> str:
        """Return the model identifier used for answer composition."""
        ...

    def prepare(self, turn: Turn) -> PreparedTurn:
        """Prepare the turn's inputs for generation."""
        ...

    def compose(self, prepared: PreparedTurn) -> AsyncGenerator[ComposerEvent]:
        """Stream deltas, then exactly one DraftEvent. Closing the iterator cancels upstream work."""
        ...
