"""Evaluation artifact failures must never strand an owned server or refund spend."""

import json
from types import SimpleNamespace

import pytest

from scripts import evaluate_end_to_end as evaluator
from scripts.real_eval_budget import ATTEMPT_MICRO, Envelope


class FixtureRunError(RuntimeError):
    pass


def harness(monkeypatch, *, startup='ready', join_error=False):
    events = []
    server = SimpleNamespace(started=startup == 'ready', should_exit=False, run=lambda **kwargs: None)

    class Reservation:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            events.append('socket_closed')

        def bind(self, address):
            pass

        def getsockname(self):
            return '127.0.0.1', 12345

        def listen(self, backlog):
            pass

    class Thread:
        def start(self):
            events.append('started')
            if startup == 'start_error':
                raise OSError('synthetic_thread_start_failure')

        def is_alive(self):
            return startup != 'dead' and 'joined' not in events

        def join(self, timeout):
            assert server.should_exit is True
            assert timeout == 20
            events.append('joined')
            if join_error:
                raise RuntimeError('synthetic_join_failure')

    class Client:
        def __enter__(self):
            raise FixtureRunError('synthetic_run_failure')

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(evaluator.socket, 'socket', lambda: Reservation())
    monkeypatch.setattr(evaluator.uvicorn, 'Config', lambda *args, **kwargs: object())
    monkeypatch.setattr(evaluator.uvicorn, 'Server', lambda *args: server)
    monkeypatch.setattr(evaluator.threading, 'Thread', lambda *args, **kwargs: Thread())
    monkeypatch.setattr(evaluator, 'create_app', lambda *args, **kwargs: object())
    monkeypatch.setattr(evaluator.httpx, 'Client', lambda *args, **kwargs: Client())
    clock = iter((0, 11))
    monkeypatch.setattr(evaluator.time, 'monotonic', lambda: next(clock))
    monkeypatch.setattr(evaluator.time, 'sleep', lambda seconds: None)
    return server, events


def causes(error):
    values = []
    while error is not None:
        values.append(str(error))
        error = error.__cause__ or error.__context__
    return values


def pending_budget(tmp_path):
    envelope = Envelope(tmp_path / 'synthetic-budget.sqlite3')
    envelope.reserve()
    before = envelope.snapshot()
    return envelope, before


def assert_pending_unchanged(envelope, before):
    after = envelope.snapshot()
    assert after['attempts'] == before['attempts'] == 1
    assert after['reserved_micro_usd'] == before['reserved_micro_usd'] == ATTEMPT_MICRO
    with envelope.connect() as db:
        assert db.execute('SELECT reserved,settled FROM attempts').fetchall() == [(ATTEMPT_MICRO, 0)]


@pytest.mark.parametrize(('stop_error', 'join_error'), [(False, False), (True, False), (True, True)])
def test_checkpoint_failure_still_stops_server_and_preserves_last_good_artifact_and_pending_cost(
    tmp_path, monkeypatch, stop_error, join_error, caplog, capsys
):
    server, events = harness(monkeypatch, join_error=join_error)
    envelope, before = pending_budget(tmp_path)
    bounded = SimpleNamespace(envelope=envelope, _key='synthetic-unit-only-never-dispatched')
    original_fsync = evaluator.os.fsync
    calls = 0

    def fsync(descriptor):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError('synthetic_checkpoint_fsync_failure')
        return original_fsync(descriptor)

    monkeypatch.setattr(evaluator.os, 'fsync', fsync)
    if stop_error:

        def stop(reason):
            raise OSError('synthetic_budget_stop_failure')

        monkeypatch.setattr(envelope, 'stop', stop)
    manifest = {'cases': [{'locale': 'es'}]}
    with pytest.raises((OSError, RuntimeError)) as caught:
        evaluator.evaluate(manifest, tmp_path, 'a' * 40, bounded=bounded)
    assert server.should_exit is True
    assert events == ['started', 'joined', 'socket_closed']
    assert json.loads((tmp_path / 'answers.json').read_text()) == []
    chain = causes(caught.value)
    assert 'synthetic_checkpoint_fsync_failure' in chain
    assert 'synthetic_run_failure' in chain
    if stop_error:
        assert 'synthetic_budget_stop_failure' in chain
    if join_error:
        assert 'synthetic_join_failure' in chain
    assert_pending_unchanged(envelope, before)
    captured = capsys.readouterr()
    assert 'synthetic_' not in captured.out + captured.err
    assert all('synthetic_' not in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize('startup', ['timeout', 'dead', 'start_error'])
def test_failed_startup_releases_owned_server_and_preserves_pending_reservation(
    tmp_path, monkeypatch, startup
):
    server, events = harness(monkeypatch, startup=startup)
    envelope, before = pending_budget(tmp_path)
    bounded = SimpleNamespace(envelope=envelope, _key='synthetic-unit-only-never-dispatched')
    with pytest.raises((OSError, RuntimeError)) as caught:
        evaluator.evaluate({'cases': []}, tmp_path, 'a' * 40, bounded=bounded)
    assert server.should_exit is True
    expected = (
        ['started', 'socket_closed'] if startup == 'start_error' else ['started', 'joined', 'socket_closed']
    )
    assert events == expected
    assert str(caught.value) == (
        'synthetic_thread_start_failure' if startup == 'start_error' else 'evaluation server did not start'
    )
    assert_pending_unchanged(envelope, before)
