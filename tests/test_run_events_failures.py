"""PVA-M4.3: the unexpected-failure step of `_ModelRun.events` keeps its log and public code."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.support import ScriptedProvider, ask, client, open_session

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    import pytest

    from app.ai.provider import ModelChunk, ModelRequest

SECRET = "synthetic-unexpected-detail"


class ExplodingProvider(ScriptedProvider):
    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelChunk]:
        self.calls.append(request)
        self.closed += 1
        raise RuntimeError(SECRET)
        yield  # pragma: no cover - makes this an async generator


def test_unexpected_composer_error_logs_traceback_and_fails_generation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with client(tmp_path, ExplodingProvider()) as c:
        status, events, _ = ask(c, open_session(c), "¿Qué incluye la guía?")
    assert status == 200
    assert events[-1]["type"] == "run.failed"
    assert events[-1]["code"] == "generation_failed"
    assert SECRET not in str(events)
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line]
    failures = [line for line in lines if line.get("outcome") == "unexpected_error"]
    # The traceback reaches the allowlist formatter, which reports only the exception class.
    assert failures == [
        {
            "ts": failures[0]["ts"],
            "level": "error",
            "logger": "app.application.chat",
            "operation": "run",
            "outcome": "unexpected_error",
            "exception": "RuntimeError",
        }
    ]
    assert SECRET not in json.dumps(lines)
