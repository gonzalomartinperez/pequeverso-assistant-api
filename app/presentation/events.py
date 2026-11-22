"""SSE events of `POST /api/v1/messages` (schema_version "1").

Wire format per event: `id: <sequence>`, `event: <type>`, `data: <json>`, blank line. Comment
lines (`: keep-alive`) may appear at any time and carry no sequence. Every stream ends with
exactly one terminal event: run.completed, run.failed or run.cancelled.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.presentation.schemas import MessageOut


class _Event(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1"] = "1"
    run_id: str
    sequence: int = Field(ge=0, description="0-based, strictly increasing within a run.")
    timestamp: datetime


class RunStartedEvent(_Event):
    """Announce the start of a run and include the stored question when available."""

    type: Literal["run.started"] = "run.started"
    user_message: MessageOut | None = Field(
        description="The stored question (redacted if it contained contact data); null on an idempotent replay."
    )


class MessageDeltaEvent(_Event):
    """Deliver a provisional fragment of the streamed answer."""

    type: Literal["message.delta"] = "message.delta"
    text: str = Field(
        description="Append to the draft answer. Provisional until message.completed."
    )


class MessageCompletedEvent(_Event):
    """Deliver the final answer that replaces the streamed draft."""

    type: Literal["message.completed"] = "message.completed"
    message: MessageOut = Field(
        description="Authoritative final answer: replace the streamed draft with message.content."
    )


class RunCompletedEvent(_Event):
    """Mark the successful end of a run."""

    type: Literal["run.completed"] = "run.completed"


FailureCodeOut = Literal[
    "budget_exhausted",
    "provider_unavailable",
    "generation_failed",
    "timeout",
    "catalog_unavailable",
    "busy",
]


class RunFailedEvent(_Event):
    """End a run with a failure code and retry guidance."""

    type: Literal["run.failed"] = "run.failed"
    code: FailureCodeOut
    retryable: bool


class RunCancelledEvent(_Event):
    """Mark the end of a cancelled run."""

    type: Literal["run.cancelled"] = "run.cancelled"


StreamEvent = Annotated[
    RunStartedEvent
    | MessageDeltaEvent
    | MessageCompletedEvent
    | RunCompletedEvent
    | RunFailedEvent
    | RunCancelledEvent,
    Field(discriminator="type"),
]
TERMINAL_TYPES = frozenset({"run.completed", "run.failed", "run.cancelled"})
