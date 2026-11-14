"""SSE wire/lifecycle conformance using only in-process HTTP and ASGI disconnects."""

import json
from typing import TYPE_CHECKING

import pytest
from pydantic import TypeAdapter

from app.presentation.events import TERMINAL_TYPES, StreamEvent
from tests.support import ScriptedProvider, client, mutation_headers, open_session, parse_sse

if TYPE_CHECKING:
    from pathlib import Path

EVENTS = TypeAdapter(StreamEvent)
CLOSED_TYPES = frozenset(EVENTS.json_schema()["discriminator"]["mapping"])


def assert_frames(body: str):
    assert body.endswith("\n\n")
    for block in body.split("\n\n")[:-1]:
        if block.startswith(":"):
            assert block == ": keep-alive"
            continue
        lines = block.splitlines()
        assert len(lines) == 3
        assert lines[0].startswith("id: ")
        assert lines[1].startswith("event: ")
        assert lines[2].startswith("data: ")
        event = json.loads(lines[2].removeprefix("data: "))
        assert event["type"] in CLOSED_TYPES
        EVENTS.validate_python(event)
    events = parse_sse(body)
    assert events[0]["type"] == "run.started"
    assert [event["sequence"] for event in events] == list(range(len(events)))
    assert len({event["run_id"] for event in events}) == 1
    assert [event["type"] for event in events if event["type"] in TERMINAL_TYPES] == [
        events[-1]["type"]
    ]
    return events


@pytest.mark.parametrize("idle", [False, True])
def test_wire_frames_closed_schemas_terminal_and_idle_heartbeat(tmp_path: Path, idle: bool) -> None:
    provider = ScriptedProvider(delay=0.15 if idle else 0, chunk=10000)
    with client(tmp_path, provider, heartbeat_seconds=0.02) as c:
        csrf = open_session(c)
        response = c.post(
            "/api/v1/messages", headers=mutation_headers(csrf), json={"content": "Hola"}
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"
        events = assert_frames(response.text)
        assert events[-1]["type"] == "run.completed"
        if idle:
            # A whole provider chunk is delayed, so the comments precede the first delta.
            first_delta = response.text.index("event: message.delta")
            assert ": keep-alive\n\n" in response.text[:first_delta]


def test_failed_stream_obeys_the_same_framing_and_terminal_rules(tmp_path: Path) -> None:
    with client(
        tmp_path, ScriptedProvider(hang=True), run_timeout_seconds=0.1, heartbeat_seconds=0.02
    ) as c:
        csrf = open_session(c)
        response = c.post(
            "/api/v1/messages", headers=mutation_headers(csrf), json={"content": "Hola"}
        )
        assert response.status_code == 200
        events = assert_frames(response.text)
        assert events[-1]["type"] == "run.failed" and events[-1]["code"] == "timeout"


@pytest.mark.parametrize("last_event_id", ["1", "999999"])
def test_last_event_id_is_ignored_and_idempotency_replays_from_zero(
    tmp_path: Path, last_event_id: str
) -> None:
    """Pin today's ignored Last-Event-ID behaviour; resume is NOT part of the v1 contract."""
    provider = ScriptedProvider()
    with client(tmp_path, provider) as c:
        csrf = open_session(c)
        headers = mutation_headers(csrf, "sse-resume-key-001")
        first = c.post("/api/v1/messages", headers=headers, json={"content": "Hola"})
        original = assert_frames(first.text)
        replay = c.post(
            "/api/v1/messages",
            headers={**headers, "Last-Event-ID": last_event_id},
            json={"content": "Hola"},
        )
        assert first.status_code == replay.status_code == 200
        events = assert_frames(replay.text)
        assert events[0]["sequence"] == 0 and events[0]["user_message"] is None
        assert events[0]["run_id"] == original[0]["run_id"]
        assert events[-2]["message"] == original[-2]["message"]
        assert events[-1]["type"] == "run.completed"
        assert len(provider.calls) == 1


# Client disconnect cancelling the run and releasing the reservation is covered by the real-server
# tests in tests/test_streaming.py and tests/test_runtime_shutdown.py (not duplicated here).
