"""Regression tests for content-free logs, CLI stdout and injected wall clocks."""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.ai.prompt import PROMPT_VERSION
from app.bootstrap import logging as app_logging
from tests.support import ScriptedProvider, answer_json, ask, client, open_session

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
WALL_CLOCK_CALLS = {
    "datetime.now",
    "datetime.utcnow",
    "datetime.datetime.now",
    "datetime.datetime.utcnow",
    "date.today",
    "datetime.date.today",
    "time.time",
}


def _wall_clock_calls(source: str) -> list[tuple[int, str]]:
    return sorted(
        (node.lineno, call)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and (call := ast.unparse(node.func)) in WALL_CLOCK_CALLS
    )


def test_wall_clock_calls_are_confined_to_bootstrap() -> None:
    violations = [
        f"{path.relative_to(ROOT)}:{line}: {call}()"
        for path in sorted(APP.rglob("*.py"))
        if not path.is_relative_to(APP / "bootstrap")
        for line, call in _wall_clock_calls(path.read_text(encoding="utf-8"))
    ]
    assert not violations, "\n".join(violations)


def test_wall_clock_checker_flags_direct_calls() -> None:
    source = "datetime.now()\ndatetime.datetime.utcnow()\ndate.today()\ntime.time()"
    assert _wall_clock_calls(source) == [
        (1, "datetime.now"),
        (2, "datetime.datetime.utcnow"),
        (3, "date.today"),
        (4, "time.time"),
    ]


def test_corpus_pipeline_stdout_is_a_single_json_report_and_logs_go_to_stderr() -> None:
    env = {name: os.environ[name] for name in os.environ if name.upper() != "OPENAI_API_KEY"}
    env["ENVIRONMENT"] = "test"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.evaluate_corpus",
            "--family",
            "injection",
            "--split",
            "dev",
            "--json",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    for line in result.stdout.splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            assert {"operation", "level"}.isdisjoint(entry), line

    report = json.loads(result.stdout)
    assert report["mode"] == "fixture"
    assert report["cases"] > 0
    assert "pipeline" in report
    # The pipeline runs the app lifespan, which configures logging: its lines must be on stderr.
    stderr_logs = [json.loads(line) for line in result.stderr.splitlines() if line.startswith("{")]
    assert any(entry.get("logger") == "app.request" for entry in stderr_logs)


@pytest.fixture
def isolated_logging(monkeypatch):
    monkeypatch.setattr(app_logging, "_use_stderr", False)
    monkeypatch.setattr(app_logging, "_external", None)
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", root.handlers[:])
    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        monkeypatch.setattr(logger, "handlers", logger.handlers[:])
        monkeypatch.setattr(logger, "propagate", logger.propagate)
    loggers = [
        logging.getLogger(name) for name in ("", "uvicorn.access", "httpx", "httpcore", "openai")
    ]
    previous_levels = [(logger, logger.level) for logger in loggers]
    try:
        yield
    finally:
        for logger, level in previous_levels:
            logger.setLevel(level)


@pytest.mark.parametrize(
    ("stream_kwargs", "force_stderr", "target"),
    [
        pytest.param({}, False, "stdout", id="default"),
        pytest.param({"stream": "stderr"}, False, "stderr", id="explicit-stderr"),
        pytest.param({"stream": "stdout"}, True, "stderr", id="cli-override"),
    ],
)
def test_configure_logging_routes_to_the_expected_stream(
    isolated_logging, stream_kwargs: dict[str, str], force_stderr: bool, target: str
) -> None:
    if force_stderr:
        app_logging.use_stderr()
    app_logging.configure_logging(**stream_kwargs)

    (handler,) = logging.getLogger().handlers
    assert isinstance(handler, logging.StreamHandler)
    assert handler.stream is getattr(sys, target)


def test_configure_logging_sets_noisy_loggers_to_warning(isolated_logging) -> None:
    loggers = [logging.getLogger(name) for name in ("httpx", "httpcore", "openai")]
    for logger in loggers:
        logger.setLevel(logging.DEBUG)

    app_logging.configure_logging()

    assert all(logger.level == logging.WARNING for logger in loggers)


class _RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_external_event_counter_suppresses_records_and_flushes_only_nonzero_counts() -> None:
    handler = _RecordingHandler()
    counter = app_logging.ExternalEventCounter(handler, window=float("inf"))
    handler.addFilter(counter)
    external = logging.LogRecord("httpx", logging.WARNING, "", 0, "suppressed", (), None)
    request = logging.LogRecord(
        "app.request", logging.INFO, "", 0, '{"operation":"request"}', (), None
    )

    counter.flush()
    assert handler.records == []
    handler.handle(external)
    handler.handle(external)
    assert handler.records == []
    handler.handle(request)
    assert handler.records == [request]

    counter.flush()
    assert [json.loads(record.getMessage()) for record in handler.records[1:]] == [
        {"operation": "external_events", "count": 2}
    ]
    counter.flush()
    assert len(handler.records) == 2


@pytest.mark.parametrize(
    ("incoming_id", "valid"),
    [
        pytest.param("Cli-1234", True, id="valid"),
        pytest.param("invalid_request_id", False, id="invalid"),
        pytest.param(None, False, id="missing"),
    ],
)
def test_request_id_is_echoed_and_only_a_server_id_is_logged(
    tmp_path: Path, isolated_logging, capsys, incoming_id: str | None, valid: bool
) -> None:
    headers = {} if incoming_id is None else {"x-request-id": incoming_id}
    with client(tmp_path, log_stream="stdout") as c:
        response = c.get("/health/live", headers=headers)

    assert response.status_code == 200
    request_id = response.headers["x-request-id"]
    if valid:
        assert request_id == incoming_id
    else:
        assert request_id != incoming_id
        assert re.fullmatch(r"[0-9a-f]{16}", request_id)
    logs = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    (request,) = [entry for entry in logs if entry["logger"] == "app.request"]
    assert request["operation"] == "request"
    if valid:
        # A client-supplied id could carry a session id or key: echoed, never logged.
        assert "request_id" not in request
    else:
        assert request["request_id"] == request_id


def test_completed_run_log_carries_the_prompt_version(
    tmp_path: Path, isolated_logging, capsys
) -> None:
    provider = ScriptedProvider(output=answer_json("El kit incluye nueve PDF."))
    with client(tmp_path, provider=provider, log_stream="stdout") as c:
        csrf = open_session(c)
        status, _, _ = ask(c, csrf, "¿Qué incluye el kit?")

    assert status == 200
    logs = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    (run,) = [entry for entry in logs if entry["operation"] == "run"]
    assert run["outcome"] == "completed"
    assert run["prompt_version"] == PROMPT_VERSION
