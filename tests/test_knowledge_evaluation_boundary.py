import asyncio
import json
from datetime import UTC, datetime

import pytest

from app.bootstrap.knowledge_evaluation import (
    FixtureConnections,
    fixture_corpus,
    read_fixture_connections,
    safe_exception_hook,
    wait_for_fixture_projection,
)
from app.domain.knowledge import ProjectionStamp


def connection_data():
    return {
        'postgres_dsn': 'postgresql://knowledge_test:synthetic-password@127.0.0.1:55440/pv_graph_evaluation',
        'neo4j_uri': 'bolt://127.0.0.1:17689',
        'neo4j_username': 'neo4j',
        'neo4j_password': 'synthetic-graph-password',
    }


def test_fixture_credentials_require_an_owner_only_file_and_are_hidden_from_repr(tmp_path) -> None:
    path = tmp_path / 'fixture-connections.json'
    path.write_text(json.dumps(connection_data()))
    path.chmod(0o600)
    value = read_fixture_connections(path)
    assert value.neo4j_uri == 'bolt://127.0.0.1:17689'
    assert 'synthetic-password' not in repr(value)
    assert 'synthetic-graph-password' not in repr(value)
    path.chmod(0o644)
    with pytest.raises(ValueError, match='owner-only'):
        read_fixture_connections(path)


def test_symlink_and_extra_provider_key_configuration_are_rejected(tmp_path) -> None:
    target = tmp_path / 'fixture-connections.json'
    target.write_text(json.dumps({**connection_data(), 'OPENAI_API_KEY': 'nonfunctional-fixture-marker'}))
    target.chmod(0o600)
    link = tmp_path / 'link.json'
    link.symlink_to(target)
    with pytest.raises(ValueError, match='regular file'):
        read_fixture_connections(link)
    with pytest.raises(ValueError, match='fields are invalid'):
        read_fixture_connections(target)


@pytest.mark.parametrize(
    'replacement',
    [
        'postgresql://knowledge_test:synthetic-password@remote.invalid:55440/pv_graph_evaluation',
        'postgresql://knowledge_test:synthetic-password@127.0.0.1:55439/pv_graph_evaluation',
        'postgresql://knowledge_test:synthetic-password@127.0.0.1:55440/real-orders',
    ],
)
def test_evaluation_cannot_target_remote_or_another_application_database(replacement) -> None:
    with pytest.raises(ValueError, match='dedicated loopback'):
        FixtureConnections(**{**connection_data(), 'postgres_dsn': replacement})


def test_exception_boundary_never_prints_driver_messages_or_connection_values(capsys) -> None:
    safe_exception_hook(RuntimeError, RuntimeError('synthetic-password secret driver payload'), None)
    captured = capsys.readouterr()
    assert captured.out == ''
    assert captured.err == 'Fixture evaluation failed safely (RuntimeError); inspect the receipt\n'


def test_fixture_clock_preserves_export_time_instead_of_claiming_new_live_freshness() -> None:
    corpus = fixture_corpus()
    assert corpus.verified_at == datetime(2026, 10, 17, 15, 13, 29, tzinfo=UTC)


def test_restore_readiness_only_polls_existing_projection_and_closes_its_driver(monkeypatch) -> None:
    corpus = fixture_corpus()
    expected = ProjectionStamp(
        corpus.revision.version,
        corpus.revision.catalog_sha256,
        len(corpus.chunks),
        len(corpus.entities),
        len(corpus.relations),
    )
    calls = []

    class Database:
        driver = object()

        async def open(self):
            calls.append('open')

        async def close(self):
            calls.append('close')

    class Graph:
        def __init__(self):
            self.attempts = 0

        async def projection_stamp(self, version):
            assert version == expected.version
            self.attempts += 1
            calls.append('read_stamp')
            return None if self.attempts == 1 else expected

        # No stage method exists: rebuilding the missing projection would fail the test.

    graph = Graph()

    async def pause(seconds):
        assert seconds == 0.5

    monkeypatch.setattr('app.bootstrap.knowledge_evaluation.Neo4jDatabase', lambda *args: Database())
    monkeypatch.setattr('app.bootstrap.knowledge_evaluation.Neo4jPublicGraph', lambda driver: graph)
    monkeypatch.setattr('app.bootstrap.knowledge_evaluation.asyncio.sleep', pause)
    proof = asyncio.run(
        wait_for_fixture_projection('bolt://127.0.0.1:17689', 'neo4j', 'synthetic-only', expected)
    )
    assert proof.ready and proof.attempts == 2
    assert proof.failures == ('projection_missing_or_incomplete',)
    assert calls == ['open', 'read_stamp', 'read_stamp', 'close']
