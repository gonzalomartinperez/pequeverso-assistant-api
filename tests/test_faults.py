"""Dependency faults at existing ports, including visitor output and conservative accounting."""

import json
import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

import pytest

from app.adapters.graph.composer import GraphAnswerComposer
from app.adapters.sqlite.catalog_repository import SqliteCatalogRepository
from app.ai.provider import TextChunk
from app.domain.errors import FailureCode, RejectedError
from tests.support import FixedClock, ScriptedProvider, ask, client, open_session
from tests.test_hybrid_knowledge import setup
from tests.test_public_corpus import NOW

if TYPE_CHECKING:
    from pathlib import Path

PRIVATE = "synthetic-private-dependency-detail"


class BrokenProvider(ScriptedProvider):
    async def stream(self, request):
        self.calls.append(request)
        try:
            yield TextChunk('{"answer":"Una respuesta parcial. ')
            raise RuntimeError(PRIVATE)
        finally:
            self.closed += 1


def assert_safe(payload):
    text = json.dumps(payload)
    for forbidden in (PRIVATE, "Traceback", "RuntimeError", "sqlite3", "neo4j://", "postgresql://"):
        assert forbidden not in text


@pytest.mark.parametrize("fault", ["timeout", "unavailable", "midstream"])
def test_provider_fault_closes_stream_and_accounts_unknown_spend(
    tmp_path: Path, fault: str
) -> None:
    provider = {
        "timeout": ScriptedProvider(hang=True, usage=None),
        "unavailable": ScriptedProvider(fail_with=FailureCode.PROVIDER_UNAVAILABLE),
        "midstream": BrokenProvider(),
    }[fault]
    code = {
        "timeout": "timeout",
        "unavailable": "provider_unavailable",
        "midstream": "generation_failed",
    }[fault]
    # Only the timeout case needs a short deadline; the others get headroom for slow hosts.
    deadline = 1.0 if fault == "timeout" else 30.0
    with client(tmp_path, provider, run_timeout_seconds=deadline) as c:
        csrf = open_session(c)
        status, events, error = ask(c, csrf, "Hola")
        if fault == "timeout" and status == 504:
            # A deadline reached before the stream starts is the documented HTTP 504 envelope.
            assert error is not None
            envelope = error.get("error", error)
            assert envelope["code"] == "timeout"
            assert_safe(error)
        else:
            assert status == 200 and error is None
            assert events[-1]["type"] == "run.failed"
            assert events[-1]["code"] == code and events[-1]["retryable"] is True
            assert_safe(events)
        assert provider.closed == 1 and len(provider.calls) == 1
        with closing(sqlite3.connect(tmp_path / "test.sqlite3")) as db:
            assert db.execute("SELECT state FROM runs").fetchone() == ("failed",)
            status, actual, reserved = db.execute(
                "SELECT status,actual_micro,reserved_micro FROM spend_ledger"
            ).fetchone()
            assert status == "unreported" and actual is None and reserved > 0
        assert len(c.app.state.services.chat.registry) == 0
        provider.fail_with, provider.hang = None, False
        if fault != "midstream":
            assert ask(c, csrf, "Hola otra vez")[1][-1]["type"] == "run.completed"


@pytest.mark.parametrize("fault", ["budget", "rate"])
def test_admission_faults_never_dispatch_generation(tmp_path: Path, fault: str) -> None:
    overrides = (
        {"daily_budget_usd": "0.000001"}
        if fault == "budget"
        else {"messages_per_session_per_day": 1}
    )
    provider = ScriptedProvider()
    with client(tmp_path, provider, **overrides) as c:
        csrf = open_session(c)
        if fault == "rate":
            assert ask(c, csrf, "Hola")[0] == 200
        calls = len(provider.calls)
        status, events, error = ask(c, csrf, "Otra pregunta")
        assert status == (503 if fault == "budget" else 429) and events == []
        assert error["error"]["code"] == (
            "budget_exhausted" if fault == "budget" else "rate_limited"
        )
        assert error["error"]["retryable"] is False
        assert_safe(error)
        assert len(provider.calls) == calls
        with closing(sqlite3.connect(tmp_path / "test.sqlite3")) as db:
            assert db.execute(
                "SELECT count(*) FROM spend_ledger WHERE status='pending'"
            ).fetchone() == (0,)
            assert db.execute("SELECT count(*) FROM spend_ledger").fetchone() == (calls,)


def test_catalog_store_activation_failure_refuses_questions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail_activate(*args, **kwargs):
        raise OSError(PRIVATE)

    monkeypatch.setattr(SqliteCatalogRepository, "activate", fail_activate)
    provider = ScriptedProvider()
    with client(tmp_path, provider) as c:
        csrf = open_session(c)
        status, events, error = ask(c, csrf, "Hola")
        assert status == 503 and events == []
        assert error["error"]["code"] == "catalog_unavailable"
        assert error["error"]["retryable"] is True
        assert_safe(error)
        ready = c.get("/health/ready")
        assert ready.status_code == 503
        assert_safe(ready.json())
        assert provider.calls == []


@pytest.mark.parametrize("fault", ["graph_preflight", "graph_midturn", "store"])
def test_knowledge_port_faults_surface_safe_failure_or_verified_fallback(
    tmp_path: Path, fault: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0009: only a graph failure after valid preflight permits PG-only evidence."""
    retrieval, store, graph, _, active = setup()
    store.lexical = (store.hit("product:grafismo-fonetico"),)
    failure = RejectedError(FailureCode.DEPENDENCY_UNAVAILABLE)
    failure.add_note(PRIVATE)
    if fault == "graph_preflight":
        graph.error = failure
    elif fault == "graph_midturn":
        graph.candidate_error = failure
    else:

        async def failed_revision():
            raise failure

        monkeypatch.setattr(store, "active_revision", failed_revision)
    seen = []
    original = retrieval.retrieve

    async def capture(*args, **kwargs):
        result = await original(*args, **kwargs)
        seen.append(result)
        return result

    monkeypatch.setattr(retrieval, "retrieve", capture)
    provider = ScriptedProvider()
    with client(tmp_path, provider, clock=FixedClock(NOW)) as c:
        services = c.app.state.services
        monkeypatch.setattr(services.catalog, "_active", active)
        monkeypatch.setattr(services.chat, "knowledge", retrieval)
        monkeypatch.setattr(
            services.chat,
            "composer",
            GraphAnswerComposer(services.chat.composer, retrieval, 100000),
        )
        csrf = open_session(c)
        status, events, error = ask(c, csrf, "¿Qué incluye grafismo fonético?")
        assert_safe(events or error)
        if fault == "graph_midturn":
            assert status == 200 and events[-1]["type"] == "run.completed"
            assert len(seen) == 1 and seen[0].graph_degraded
            assert seen[0].chunks and all(chunk in store.corpus.chunks for chunk in seen[0].chunks)
            assert len(provider.calls) == 1
        else:
            assert status == 503 and events == []
            assert error["error"]["code"] == "dependency_unavailable"
            assert error["error"]["retryable"] is True
            assert provider.calls == []
