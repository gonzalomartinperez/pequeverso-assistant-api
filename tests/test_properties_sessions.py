"""Session lifecycle and cancellation isolation with the real SQLite stores."""

import asyncio
from dataclasses import dataclass, field, replace
from datetime import timedelta

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from app.adapters.sqlite.database import Database
from app.adapters.sqlite.ledger import SqliteRateLimiter
from app.adapters.sqlite.stores import SqliteMessageStore, SqliteRunStore, SqliteSessionStore
from app.application.runs import RunRegistry
from app.application.sessions import SessionLimits, SessionService
from app.domain.conversation import Message, Role, Session
from app.domain.errors import RejectedError
from tests.support import FixedClock


@dataclass
class ModelSession:
    session: Session
    secret: str
    history: list[Message] = field(default_factory=list)
    deleted: bool = False
    run_id: str | None = None
    cancelled: asyncio.Event | None = None


class SessionMachine(RuleBasedStateMachine):
    """Row 10: session lifecycle transitions preserve ownership and validity."""

    def __init__(self, retention=60):
        super().__init__()
        self.loop = asyncio.Runner()
        self.db = Database(":memory:")
        self.loop.run(self.db.open())
        self.clock = FixedClock()
        self.retention = timedelta(seconds=retention)
        self.messages = SqliteMessageStore(self.db)
        self.runs = SqliteRunStore(self.db)
        self.service = SessionService(
            SqliteSessionStore(self.db),
            self.messages,
            SqliteRateLimiter(self.db),
            self.clock,
            SessionLimits(self.retention, 1000, 1000),
        )
        self.registry = RunRegistry()
        self.models = []
        self.serial = 0

    @initialize(retention=st.integers(1, 60))
    def bootstrap(self, retention):
        self.retention = timedelta(seconds=retention)
        self.service = SessionService(
            SqliteSessionStore(self.db),
            self.messages,
            SqliteRateLimiter(self.db),
            self.clock,
            SessionLimits(self.retention, 1000, 1000),
        )
        self.create()
        self.create()

    @rule()
    def create(self):
        if len(self.models) >= 5:
            return
        opened = self.loop.run(self.service.open(None, "synthetic-client"))
        assert opened.secret
        assert opened.history == []
        assert all(
            opened.session.id != m.session.id and opened.secret != m.secret for m in self.models
        )
        self.models.append(ModelSession(opened.session, opened.secret))

    def selected(self, index):
        return self.models[index % len(self.models)] if self.models else None

    @rule(index=st.integers(0, 20), text=st.text(alphabet="abc áñ!?", max_size=25))
    def message_touch(self, index, text):
        model = self.selected(index)
        if model is None or model.deleted:
            return
        opened = self.loop.run(self.service.open(model.secret, "synthetic-client"))
        assert opened.session.id == model.session.id
        assert opened.history == model.history
        model.session = opened.session
        self.serial += 1
        message = Message(f"msg-{self.serial}", Role.USER, text, self.clock.now())
        self.loop.run(self.messages.append(model.session.id, message))
        model.history.append(message)
        self.loop.run(self.service.touch(model.session))
        model.session = replace(
            model.session,
            last_active_at=self.clock.now(),
            expires_at=self.clock.now() + self.retention,
        )
        if model.run_id is None:
            model.run_id = f"run-{self.serial}"
            model.cancelled = self.registry.add(model.run_id, model.session.id)

    @rule(index=st.integers(0, 20), foreign=st.booleans())
    def cancel(self, index, foreign):
        model = self.selected(index)
        if model is None or model.run_id is None:
            return
        other_owner = next((m.session.id for m in self.models if m is not model), "unknown-session")
        owner = other_owner if foreign else model.session.id
        assert self.registry.cancel(model.run_id, owner) == (not foreign)
        assert model.cancelled.is_set() == (not foreign)
        if not foreign:
            self.registry.remove(model.run_id)
            model.run_id = None
            model.cancelled = None

    def forget(self, model):
        model.deleted = True
        model.history.clear()
        if model.run_id is not None:
            assert self.registry.cancel(model.run_id, model.session.id)
            assert model.cancelled.is_set()
            self.registry.remove(model.run_id)
            model.run_id = None
            model.cancelled = None

    @rule(index=st.integers(0, 20))
    def delete(self, index):
        model = self.selected(index)
        if model is not None:
            self.loop.run(self.service.delete(model.session))
            self.forget(model)

    @rule(seconds=st.integers(0, 120))
    def expire(self, seconds):
        self.clock.advance(seconds=seconds)
        expired = [
            m for m in self.models if not m.deleted and m.session.expires_at <= self.clock.now()
        ]
        assert self.loop.run(self.service.purge_expired()) == len(expired)
        for model in expired:
            self.forget(model)

    @invariant()
    def sessions_are_valid_and_isolated(self):
        for model in self.models:
            if model.cancelled is not None:
                assert not model.cancelled.is_set()
            resolved = self.loop.run(self.service.resolve(model.secret))
            history = self.loop.run(self.messages.history(model.session.id, 1000))
            if model.deleted:
                assert resolved is None
                assert history == []
                with pytest.raises(RejectedError):
                    self.loop.run(self.service.require(model.secret, model.session.csrf_token))
            else:
                assert resolved == model.session
                assert resolved.created_at <= resolved.last_active_at < resolved.expires_at
                assert resolved.expires_at > self.clock.now()
                assert history == model.history
                assert (
                    self.loop.run(self.service.require(model.secret, model.session.csrf_token))
                    == resolved
                )
                with pytest.raises(RejectedError):
                    self.loop.run(self.service.require(model.secret, "invalid-csrf"))
            for other in self.models:
                if other is not model:
                    for message in history:
                        assert (
                            self.loop.run(self.runs.message(other.session.id, message.id)) is None
                        )
        assert len(self.registry) == sum(m.run_id is not None for m in self.models)

    def teardown(self):
        self.registry.close()
        self.loop.run(self.db.close())
        self.loop.close()


TestSessionLifecycle = SessionMachine.TestCase
TestSessionLifecycle.settings = settings(stateful_step_count=20)


@given(retention=st.integers(1, 60))
@settings(max_examples=10)
@example(retention=1)
def test_session_lifecycle_regression(retention):
    """Row 10: foreign cancellation, expiry boundary and deletion regression."""
    machine = SessionMachine(retention)
    try:
        machine.create()
        machine.create()
        machine.message_touch(0, "primera")
        machine.message_touch(1, "segunda")
        machine.cancel(0, True)
        machine.sessions_are_valid_and_isolated()
        machine.cancel(0, False)
        machine.expire(retention)
        machine.sessions_are_valid_and_isolated()
        machine.create()
        machine.message_touch(2, "nueva")
        machine.delete(2)
        machine.sessions_are_valid_and_isolated()
    finally:
        machine.teardown()
