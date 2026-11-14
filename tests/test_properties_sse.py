"""SSE framing and the discriminated wire event set."""

from datetime import UTC, datetime

import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from pydantic import BaseModel, TypeAdapter, ValidationError

from app.presentation.events import StreamEvent
from app.presentation.streaming import encode
from tests.support import parse_sse

EVENTS = (
    "run.started",
    "message.delta",
    "message.completed",
    "run.completed",
    "run.failed",
    "run.cancelled",
)
ADAPTER = TypeAdapter(StreamEvent)
NOW = datetime(2026, 9, 28, tzinfo=UTC)


def payload(kind, text, sequence):
    data = {"type": kind, "run_id": "run_property", "sequence": sequence, "timestamp": NOW}
    message = {"id": "msg_property", "role": "assistant", "content": text, "created_at": NOW}
    if kind == "run.started":
        data["user_message"] = None
    elif kind == "message.delta":
        data["text"] = text
    elif kind == "message.completed":
        data["message"] = message
    elif kind == "run.failed":
        data.update(code="timeout", retryable=True)
    return data


@given(
    kind=st.sampled_from(EVENTS),
    text=st.text(alphabet='abcXYZ012 áñü🙂\n\r\t\x00"\\', max_size=150),
    sequence=st.integers(0, 10000),
)
@example(kind="message.delta", text='á\n\nevent: run.failed\r\n"\\', sequence=0)
def test_sse_payload_round_trip_and_closed_schema(kind, text, sequence):
    """Row 6: every supported wire event round-trips without frame injection."""
    event = ADAPTER.validate_python(payload(kind, text, sequence))
    rendered = encode(event).decode()
    assert rendered.endswith("\n\n")
    assert parse_sse(rendered) == [event.model_dump(mode="json")]
    assert ADAPTER.validate_python(parse_sse(rendered)[0]) == event
    with pytest.raises(ValidationError):
        ADAPTER.validate_python(payload("unknown." + kind, text, sequence))


class UnknownEvent(BaseModel):
    type: str
    sequence: int


@pytest.mark.xfail(
    strict=True,
    reason="streaming.encode renders arbitrary model event types outside StreamEvent's closed set",
)
@given(kind=st.text(alphabet="abc", min_size=1, max_size=20))
@example(kind="unknown")
def test_sse_renderer_rejects_unknown_events(kind):
    """Row 6: the renderer should reject events outside the closed wire set."""
    with pytest.raises((TypeError, ValueError)):
        encode(UnknownEvent(type=kind, sequence=0))
