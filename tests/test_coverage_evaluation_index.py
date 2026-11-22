"""Fixture evaluation composition owns its adapters and records only retrieval metadata."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import SecretStr

from app.adapters.graph.composer import GraphPrepared
from app.adapters.providers.openai_embeddings import FixtureHashEmbeddings
from app.application.operations import Spend
from app.application.ports import DeltaEvent
from app.bootstrap import evaluation_index
from app.bootstrap.config import DEFAULT_CATALOG
from app.bootstrap.knowledge_evaluation import FrozenClock, fixture_corpus
from app.domain.knowledge import RetrievedKnowledge
from tests.test_knowledge_indexing import Graph, Store

CLOCK = FrozenClock(datetime(2026, 11, 22, 10, 5, tzinfo=UTC))
CONFIG = evaluation_index.EvaluationIndexConfig(
    SecretStr("indexer"), SecretStr("accounting"), "bolt://fixture", "neo4j", SecretStr("fixture")
)


@pytest.fixture
def indexing_resources(monkeypatch):
    events = []
    store = Store(events)
    graph = Graph(store, events)
    public, accounting, neo = [Mock(open=AsyncMock(), close=AsyncMock()) for _ in range(3)]
    for name, db in zip(("public", "accounting", "neo"), (public, accounting, neo), strict=True):
        db.open.side_effect = lambda name=name: events.append(f"open:{name}")
        db.close.side_effect = lambda name=name: events.append(f"close:{name}")
    connect = Mock(side_effect=[public, accounting])
    monkeypatch.setattr(evaluation_index, "PostgresDatabase", connect)
    monkeypatch.setattr(evaluation_index, "Neo4jDatabase", Mock(return_value=neo))
    recovery = AsyncMock()
    monkeypatch.setattr(
        evaluation_index, "PostgresLedger", Mock(return_value=Mock(abandon_index_pending=recovery))
    )
    monkeypatch.setattr(evaluation_index, "PostgresKnowledgeStore", Mock(return_value=store))
    monkeypatch.setattr(evaluation_index, "Neo4jPublicGraph", Mock(return_value=graph))
    return events, store, connect, recovery


def test_invalid_snapshot_is_rejected_before_connecting(indexing_resources):
    _, _, connect, _ = indexing_resources
    factory = Mock()
    with pytest.raises(ValueError, match="Field required"):
        asyncio.run(evaluation_index.index_evaluation_snapshot(CONFIG, b"{}", CLOCK, factory))
    connect.assert_not_called()
    factory.assert_not_called()


@pytest.mark.parametrize("owned_transport", [False, True])
def test_fixture_index_activates_snapshot_and_closes_owned_resources(
    indexing_resources, owned_transport
):
    events, store, _, recovery = indexing_resources
    expected_corpus = fixture_corpus()
    clock = FrozenClock(expected_corpus.verified_at + timedelta(days=1))
    transport_close = AsyncMock(side_effect=lambda: events.append("close:embeddings"))
    factory = Mock(
        return_value=evaluation_index.EmbeddingResource(
            FixtureHashEmbeddings(), transport_close if owned_transport else None
        )
    )
    result = asyncio.run(
        evaluation_index.index_evaluation_snapshot(
            CONFIG, DEFAULT_CATALOG.read_bytes(), clock, factory
        )
    )
    factory.assert_called_once()
    recovery.assert_awaited_once()
    assert result.version == store.active_version
    assert store.staged == expected_corpus
    assert result.reused_vectors is False
    assert events[:3] == ["open:public", "open:accounting", "open:neo"]
    expected = ["close:neo", "close:accounting", "close:public"]
    if owned_transport:
        expected.insert(0, "close:embeddings")
    assert events[-len(expected) :] == expected


def test_spend_snapshot_queries_only_frozen_month_and_day(monkeypatch):
    private, public = [Mock(open=AsyncMock(), close=AsyncMock()) for _ in range(2)]
    monkeypatch.setattr(evaluation_index, "PostgresDatabase", Mock(side_effect=[private, public]))
    query = Mock(spend=AsyncMock(side_effect=[Spend(7, 4, 1), Spend(4, 2, 0)]))
    queries = Mock(return_value=query)
    monkeypatch.setattr(evaluation_index, "PostgresOperationsQueries", queries)

    snapshot = asyncio.run(
        evaluation_index.evaluation_spend_snapshot(SecretStr("private"), SecretStr("public"), CLOCK)
    )
    queries.assert_called_once_with(private, public)
    assert [entry.args for entry in query.spend.await_args_list] == [
        ("month", "2026-11"),
        ("day", "2026-11-22"),
    ]
    assert snapshot == [
        {"period": "month", "confirmed": 7, "estimated": 4, "pending": 1},
        {"period": "day", "confirmed": 4, "estimated": 2, "pending": 0},
    ]
    private.close.assert_awaited_once()
    public.close.assert_awaited_once()


@pytest.mark.parametrize("mode", ["baseline", "catalog_only", "retrieval_cancelled"])
def test_recording_composer_forwards_deltas_and_records_on_stream_close(mode):
    corpus = fixture_corpus()
    baseline = Mock()
    prepared = baseline
    closed = []
    records = []
    delta = DeltaEvent("synthetic delta")
    if mode != "baseline":
        prepared = GraphPrepared(
            turn=Mock(),
            baseline=baseline,
            reservation_bytes=1024,
            catalog_only=mode == "catalog_only",
        )
        if mode == "retrieval_cancelled":
            prepared.retrieval = RetrievedKnowledge(corpus.revision, (), ())
            prepared.sent_chunk_ids = (corpus.chunks[0].id,)

    async def compose(actual):
        assert actual is prepared
        try:
            yield delta
        finally:
            closed.append(True)

    turn = Mock()
    delegate = Mock(model="fixture", prepare=Mock(return_value=prepared), compose=compose)
    wrapper = evaluation_index.RecordingComposer(delegate, records)
    assert wrapper.model == "fixture"
    assert wrapper.prepare(turn) is prepared
    delegate.prepare.assert_called_once_with(turn)

    async def collect():
        stream = wrapper.compose(prepared)
        if mode == "retrieval_cancelled":
            assert await anext(stream) is delta
            await stream.aclose()
        else:
            assert [event async for event in stream] == [delta]

    asyncio.run(collect())
    assert closed == [True]
    if mode == "baseline":
        assert records == []
    else:
        assert len(records) == 1
        record = records[0]
        assert record["catalog_only"] is (mode == "catalog_only")
        assert record["generation_started"] is False
        if mode == "retrieval_cancelled":
            assert record["retrieved"]["revision"]["version"] == corpus.revision.version
            assert record["sent_chunk_ids"] == [corpus.chunks[0].id]
        else:
            assert record["retrieved"] is None
            assert record["sent_chunk_ids"] == []
