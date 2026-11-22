"""The fixture evaluation CLI validates its inputs and preserves offline receipts."""

import asyncio
import json
import sys
from contextlib import nullcontext
from dataclasses import asdict, replace
from unittest.mock import AsyncMock, Mock

import pytest

from app.application.knowledge_evaluation import FixtureKnowledgeEvaluator, QueryObservation
from app.bootstrap import knowledge_evaluation as evaluation
from app.domain.errors import FailureCode, RejectedError
from app.domain.knowledge import (
    EmbeddingPurpose,
    ProjectionStamp,
    RetrievalStrategy,
    RetrievedKnowledge,
)
from app.domain.language import Language
from tests.test_hybrid_knowledge import setup

CONNECTIONS = {
    "postgres_dsn": "postgresql://fixture:synthetic@127.0.0.1:55440/pv_graph_evaluation",
    "neo4j_uri": "bolt://127.0.0.1:17689",
    "neo4j_username": "neo4j",
    "neo4j_password": "synthetic",
}


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"neo4j_password": 42}, "fields are invalid"),
        ({"neo4j_username": "operator"}, "dedicated loopback"),
        ({"postgres_dsn": "postgresql://127.0.0.1:55440/other"}, "dedicated loopback"),
        ({"neo4j_uri": "bolt://127.0.0.1:7687"}, "dedicated loopback"),
    ],
)
def test_connection_file_rejects_other_identities_and_malformed_values(tmp_path, change, message):
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(CONNECTIONS | change))
    path.chmod(0o600)
    with pytest.raises(ValueError, match=message):
        evaluation.read_fixture_connections(path)


def test_connection_file_must_be_regular_private_and_not_a_symlink(tmp_path):
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(CONNECTIONS))
    path.chmod(0o644)
    with pytest.raises(ValueError, match="owner-only regular file"):
        evaluation.read_fixture_connections(path)
    with pytest.raises(ValueError, match="owner-only regular file"):
        evaluation.read_fixture_connections(tmp_path)
    path.chmod(0o600)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="private regular file"):
        evaluation.read_fixture_connections(link)
    assert asdict(evaluation.read_fixture_connections(path)) == CONNECTIONS


@pytest.fixture
def comparison(tmp_path, monkeypatch):
    connections = tmp_path / "fixture.json"
    connections.write_text(json.dumps(CONNECTIONS))
    connections.chmod(0o600)
    corpus = evaluation.fixture_corpus()
    cases = [
        {
            "id": f"case-{i}",
            "question": f"Synthetic question {i}",
            "relevant_chunk_ids": [corpus.chunks[0].id],
            "language": "en" if i % 2 else "es",
        }
        for i in range(200)
    ]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"catalog_sha256": corpus.revision.catalog_sha256, "cases": cases})
    )
    output = tmp_path / "results"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "knowledge_evaluation",
            "--fixture",
            "--connections",
            str(connections),
            "--manifest",
            str(manifest),
            "--output",
            str(output),
        ],
    )
    monkeypatch.setenv("PV_EVALUATION_CODE_REVISION", "a" * 40)
    return corpus, manifest, output


def test_comparison_requires_explicit_fixture_mode(comparison, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [arg for arg in sys.argv if arg != "--fixture"])
    with pytest.raises(SystemExit) as exc:
        evaluation.main()
    assert exc.value.code == 2
    assert "the following arguments are required: --fixture" in capsys.readouterr().err
    assert not comparison[2].exists()


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("in_checkout", "outside the source checkout"),
        ("digest", "frozen matching catalog"),
        ("size", "at least 200 cases"),
        ("label", "must name actual public source chunks"),
    ],
)
def test_comparison_rejects_invalid_manifest_before_database_access(
    comparison, monkeypatch, failure, message
):
    _, manifest, output = comparison
    database = Mock()
    monkeypatch.setattr(evaluation, "PostgresDatabase", database)
    content = json.loads(manifest.read_text())
    if failure == "in_checkout":
        monkeypatch.setattr(sys, "argv", [*sys.argv[:-1], str(evaluation.ROOT / "invalid-output")])
    elif failure == "digest":
        content["catalog_sha256"] = "0" * 64
    elif failure == "size":
        content["cases"].pop()
    else:
        content["cases"][-1]["relevant_chunk_ids"] = ["unpublished"]
    manifest.write_text(json.dumps(content))
    with pytest.raises(ValueError, match=message):
        evaluation.main()
    assert not output.exists()
    database.assert_not_called()


@pytest.mark.parametrize("outcome", ["complete", "interrupted", "missing_proof"])
def test_comparison_activation_receipt_and_incremental_observations(
    comparison, monkeypatch, outcome, capsys
):
    corpus, _, output = comparison
    stamp = ProjectionStamp(
        corpus.revision.version,
        corpus.revision.catalog_sha256,
        len(corpus.chunks),
        len(corpus.entities),
        len(corpus.relations),
    )
    database = Mock(open=AsyncMock(), migrate=AsyncMock(), close=AsyncMock())
    neo = Mock(open=AsyncMock(), close=AsyncMock())
    store = Mock(
        indexing_lock=Mock(side_effect=nullcontext),
        stage=AsyncMock(),
        mark_prepared=AsyncMock(),
        activate_prepared=AsyncMock(),
    )
    graph = Mock(
        stage=AsyncMock(),
        projection_stamp=AsyncMock(return_value=None if outcome == "missing_proof" else stamp),
    )

    async def observe(question, _labels, _language):
        if outcome == "interrupted" and question.endswith(" 2"):
            raise RuntimeError("synthetic private driver text")
        return QueryObservation(question, (), ())

    observe_mock = AsyncMock(side_effect=observe)
    for name, fake in {
        "PostgresDatabase": database,
        "Neo4jDatabase": neo,
        "PostgresKnowledgeStore": store,
        "Neo4jPublicGraph": graph,
        "FixtureKnowledgeEvaluator": Mock(evaluate=observe_mock),
    }.items():
        monkeypatch.setattr(evaluation, name, Mock(return_value=fake))

    if outcome == "complete":
        evaluation.main()
    else:
        with pytest.raises(ValueError if outcome == "missing_proof" else RuntimeError) as exc:
            evaluation.main()
        evaluation.safe_exception_hook(type(exc.value), exc.value, None)
        err = capsys.readouterr().err
        assert f"failed safely ({type(exc.value).__name__})" in err
        assert "synthetic private driver text" not in err

    database.migrate.assert_awaited_once()
    database.close.assert_awaited_once()
    neo.close.assert_awaited_once()
    graph.stage.assert_awaited_once_with(corpus)
    staged, vectors = store.stage.await_args.args
    assert staged == corpus
    assert len(vectors) == len(corpus.chunks)
    assert {len(vector) for vector in vectors} == {64}

    receipt = json.loads((output / "receipt.json").read_text())
    assert receipt["catalog_sha256"] == stamp.catalog_sha256
    assert receipt["execution_code_revision"] == "a" * 40
    assert receipt["provider_calls"] == receipt["paid_calls"] == 0
    assert receipt["generation_executed"] is False

    if outcome == "missing_proof":
        store.activate_prepared.assert_not_awaited()
        observe_mock.assert_not_awaited()
        assert receipt["status"] == "interrupted"
        assert receipt["failure_type"] == "ValueError"
        assert not (output / "observations.jsonl").exists()
    else:
        store.mark_prepared.assert_awaited_once_with(stamp.version, stamp)
        store.activate_prepared.assert_awaited_once_with(stamp.version)
        rows = [
            json.loads(line) for line in (output / "observations.jsonl").read_text().splitlines()
        ]
        count = 200 if outcome == "complete" else 2
        assert [row["id"] for row in rows] == [f"case-{i}" for i in range(count)]
        assert rows[0]["question"] == "Synthetic question 0"
        assert observe_mock.await_args_list[0].args[1:] == ((corpus.chunks[0].id,), Language.ES)
        assert observe_mock.await_args_list[1].args[2] is Language.EN
        if outcome == "complete":
            assert receipt["status"] == "completed"
            assert receipt["completed_queries"] == count
        else:
            assert receipt["status"] == "interrupted"
            assert receipt["failure_type"] == "RuntimeError"


@pytest.mark.parametrize("ready", [False, True])
def test_fixture_readiness_requires_exact_stamp_and_closes_connection(monkeypatch, ready):
    clock = [0.0]

    async def advance(seconds):
        clock[0] += seconds if ready else 30.0

    stamp = ProjectionStamp("a" * 64, "b" * 64, 1, 0, 0)
    graph = Mock(
        projection_stamp=AsyncMock(
            side_effect=[RejectedError(FailureCode.DEPENDENCY_UNAVAILABLE), None, stamp],
        ),
    )
    database = Mock(open=AsyncMock(), close=AsyncMock())
    connect = Mock(return_value=database)
    monkeypatch.setattr(evaluation, "Neo4jDatabase", connect)
    monkeypatch.setattr(evaluation, "Neo4jPublicGraph", Mock(return_value=graph))
    monkeypatch.setattr(evaluation, "monotonic", lambda: clock[0])
    monkeypatch.setattr(evaluation.asyncio, "sleep", advance)
    with pytest.raises(ValueError, match="isolated fixture"):
        asyncio.run(
            evaluation.wait_for_fixture_projection("bolt://elsewhere", "neo4j", "fake", stamp)
        )
    connect.assert_not_called()

    result = asyncio.run(
        evaluation.wait_for_fixture_projection(CONNECTIONS["neo4j_uri"], "neo4j", "fake", stamp)
    )
    assert result.ready is ready
    assert result.attempts == (3 if ready else 2)
    assert result.duration_seconds == (1.0 if ready else 60.0)
    assert result.failures == ("dependency_unavailable", "projection_missing_or_incomplete")
    database.close.assert_awaited_once()


@pytest.mark.parametrize(
    ("strategy", "mislabel"),
    [
        (RetrievalStrategy.LEXICAL, RetrievalStrategy.VECTOR),
        (RetrievalStrategy.VECTOR, RetrievalStrategy.GRAPH),
        (RetrievalStrategy.GRAPH, RetrievalStrategy.LEXICAL),
    ],
)
def test_comparison_does_not_score_mislabeled_candidates(strategy, mislabel):
    retrieval, store, graph, embeddings, active = setup()
    product = "product:grafismo-fonetico"
    store.lexical = (store.hit(product),)
    hit = (store.hit(product, mislabel),)
    if strategy is RetrievalStrategy.GRAPH:
        graph.hits = hit
    else:
        setattr(store, strategy.value, hit)
    evaluator = FixtureKnowledgeEvaluator(
        store, graph, embeddings, retrieval, active, store.revision
    )

    with pytest.raises(RejectedError, match="catalog_unavailable") as error:
        asyncio.run(evaluator.evaluate("Grafismo Fonético", (product,)))
    assert error.value.code is FailureCode.CATALOG_UNAVAILABLE


def test_comparison_requires_one_query_embedding(monkeypatch):
    retrieval, store, graph, embeddings, active = setup()
    encode = AsyncMock(return_value=())
    monkeypatch.setattr(embeddings, "encode", encode)
    monkeypatch.setattr(store, "vector_candidates", vector_candidates := AsyncMock())
    evaluator = FixtureKnowledgeEvaluator(
        store, graph, embeddings, retrieval, active, store.revision
    )

    with pytest.raises(RejectedError, match="dependency_unavailable") as error:
        asyncio.run(evaluator.evaluate("Grafismo Fonético", ()))
    assert error.value.code is FailureCode.DEPENDENCY_UNAVAILABLE
    encode.assert_awaited_once_with(("Grafismo Fonético",), EmbeddingPurpose.QUERY)
    vector_candidates.assert_not_awaited()


@pytest.mark.parametrize("advanced", ["hybrid", "active"])
def test_comparison_refuses_results_that_cross_a_catalog_activation(monkeypatch, advanced):
    retrieval, store, graph, embeddings, active = setup()
    revision = store.revision
    next_revision = replace(revision, version="f" * 64)

    async def retrieve(*_args):
        if advanced == "active":
            store.revision = next_revision
        return RetrievedKnowledge(next_revision if advanced == "hybrid" else revision, (), ())

    monkeypatch.setattr(retrieval, "retrieve", retrieve)
    evaluator = FixtureKnowledgeEvaluator(store, graph, embeddings, retrieval, active, revision)

    with pytest.raises(RejectedError, match="catalog_unavailable") as error:
        asyncio.run(evaluator.evaluate("Grafismo Fonético", ()))
    assert error.value.code is FailureCode.CATALOG_UNAVAILABLE
