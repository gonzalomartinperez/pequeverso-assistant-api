"""Operator jobs fail closed before storage access and emit content-free receipts."""

import hashlib
import json
import stat
import sys
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from app.application.indexing import IndexResult
from app.bootstrap import knowledge_jobs
from app.bootstrap.config import DEFAULT_CATALOG
from app.domain.knowledge import ProjectionStamp


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ([], "index|migrate"),
        (["unknown"], "index|migrate"),
        (["migrate", "--dsn=fixture"], "Migration accepts no arguments"),
    ],
)
def test_operator_job_rejects_invalid_dispatch(monkeypatch, capsys, args, message):
    monkeypatch.setattr(sys, "argv", ["knowledge_jobs", *args])
    assert knowledge_jobs.main() == 2
    assert message in capsys.readouterr().out


def test_migration_requires_an_environment_identity(monkeypatch, capsys):
    database = Mock()
    monkeypatch.setattr(knowledge_jobs, "PostgresDatabase", database)
    monkeypatch.setattr(sys, "argv", ["knowledge_jobs", "migrate"])
    monkeypatch.delenv("POSTGRES_MIGRATION_DSN", raising=False)

    assert knowledge_jobs.main() == 2
    assert "POSTGRES_MIGRATION_DSN is required" in capsys.readouterr().out
    database.assert_not_called()


@pytest.mark.parametrize("failure", [None, "open", "migrate"])
def test_migration_closes_database_and_reports_only_failure_type(monkeypatch, capsys, failure):
    db = Mock(open=AsyncMock(), migrate=AsyncMock(), close=AsyncMock())
    database = Mock(return_value=db)
    monkeypatch.setattr(knowledge_jobs, "PostgresDatabase", database)
    monkeypatch.setattr(sys, "argv", ["knowledge_jobs", "migrate"])
    monkeypatch.setenv("POSTGRES_MIGRATION_DSN", "fixture-migration")
    if failure:
        getattr(db, failure).side_effect = RuntimeError("synthetic private driver details")
    assert knowledge_jobs.main() == (1 if failure else 0)
    database.assert_called_once_with("fixture-migration", pool_size=2)
    db.open.assert_awaited_once()
    db.close.assert_awaited_once()
    assert db.migrate.await_count == (0 if failure == "open" else 1)
    captured = capsys.readouterr()
    assert (
        "Migration failed (RuntimeError)" if failure else "migrations completed"
    ) in captured.out
    assert "synthetic private driver details" not in captured.out + captured.err


@pytest.fixture
def index_command(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.json"
    body = DEFAULT_CATALOG.read_bytes()
    catalog.write_bytes(body)
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "knowledge_jobs",
            "index",
            "--catalog",
            str(catalog),
            "--expected-catalog-sha256",
            hashlib.sha256(body).hexdigest(),
            "--receipt",
            str(receipt),
        ],
    )
    settings = knowledge_jobs.IndexSettings(
        postgres_indexer_dsn="fixture-indexer",
        postgres_embedding_dsn="fixture-accounting",
        neo4j_uri="bolt://fixture",
        neo4j_password="synthetic",
        ai_provider="fixture",
        allow_paid_ai=False,
        openai_api_key=None,
        daily_budget_usd=Decimal(1),
        monthly_budget_usd=Decimal(10),
    )
    monkeypatch.setattr(knowledge_jobs, "IndexSettings", lambda: settings)
    return catalog, receipt, settings


@pytest.mark.parametrize(
    ("failure", "kind"),
    [
        ("provider", "ValueError"),
        ("paid_gate", "ValueError"),
        ("budget", "ValueError"),
        ("digest", "ValueError"),
        ("size", "ValueError"),
        ("receipt_exists", "FileExistsError"),
    ],
)
def test_invalid_index_inputs_are_rejected_before_resources_open(
    index_command, monkeypatch, capsys, failure, kind
):
    catalog, receipt, settings = index_command
    database = Mock()
    monkeypatch.setattr(knowledge_jobs, "PostgresDatabase", database)
    if failure == "provider":
        settings.ai_provider = "unknown"
    elif failure == "paid_gate":
        settings.ai_provider = "openai"
    elif failure == "budget":
        settings.monthly_budget_usd = Decimal("0.50")
    elif failure == "digest":
        catalog.write_bytes(b"wrong snapshot")
    elif failure == "size":
        monkeypatch.setattr(knowledge_jobs, "MAX_PUBLIC_BODY_BYTES", 1)
    else:
        receipt.write_text("previous receipt")

    assert knowledge_jobs.main() == 1
    assert f"Indexing failed ({kind})" in capsys.readouterr().out
    database.assert_not_called()
    if failure == "receipt_exists":
        assert receipt.read_text() == "previous receipt"
    else:
        assert not receipt.exists()


@pytest.mark.parametrize("fail", [False, True])
def test_index_receipt_records_activation_and_resources_close(
    index_command, monkeypatch, capsys, fail
):
    catalog, receipt, _ = index_command
    resources = Mock()
    public, accounting, neo = [Mock(open=AsyncMock(), close=AsyncMock()) for _ in range(3)]
    for name, resource in zip(
        ("public", "accounting", "neo"), (public, accounting, neo), strict=True
    ):
        resources.attach_mock(resource, name)
    monkeypatch.setattr(knowledge_jobs, "PostgresDatabase", Mock(side_effect=[public, accounting]))
    monkeypatch.setattr(knowledge_jobs, "Neo4jDatabase", Mock(return_value=neo))
    monkeypatch.setattr(knowledge_jobs, "PostgresLedger", Mock())
    monkeypatch.setattr(knowledge_jobs, "PostgresKnowledgeStore", Mock())
    monkeypatch.setattr(knowledge_jobs, "Neo4jPublicGraph", Mock())

    async def index(corpus):
        assert json.loads(receipt.read_text())["status"] == "started"
        assert corpus.catalog_body == catalog.read_bytes()
        if fail:
            raise RuntimeError("synthetic private driver details")
        version = corpus.revision.version
        return IndexResult(
            version,
            ProjectionStamp(
                version,
                corpus.revision.catalog_sha256,
                len(corpus.chunks),
                len(corpus.entities),
                len(corpus.relations),
            ),
            False,
        )

    fake_index = AsyncMock(side_effect=index)
    monkeypatch.setattr(
        knowledge_jobs, "KnowledgeIndexer", Mock(return_value=Mock(index=fake_index))
    )
    assert knowledge_jobs.main() == int(fail)

    fake_index.assert_awaited_once()
    assert [entry[0] for entry in resources.mock_calls] == [
        "public.open",
        "accounting.open",
        "neo.open",
        "neo.close",
        "accounting.close",
        "public.close",
    ]
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
    output = json.loads(receipt.read_text())
    captured = capsys.readouterr()
    if fail:
        assert output == {"status": "started", "cost_status": "not_yet_known"}
        assert "Indexing failed (RuntimeError)" in captured.out
        assert "synthetic private driver details" not in captured.out + captured.err
    else:
        assert output["status"] == "verified"
        assert output["provider"] == "fixture"
        assert output["catalog_sha256"] == hashlib.sha256(catalog.read_bytes()).hexdigest()
        assert output["result"]["reused_vectors"] is False
        assert "verified and activated" in captured.out
