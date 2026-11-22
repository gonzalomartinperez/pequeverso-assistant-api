"""The offline import CLI enforces quiescence and protects receipt and driver details."""

import asyncio
import json
import stat
import sys
from unittest.mock import AsyncMock, Mock

import pytest

from app.adapters.postgres.import_sqlite import ImportReceipt
from app.bootstrap import import_database


@pytest.fixture
def import_command(tmp_path, monkeypatch):
    snapshot = tmp_path / "source.sqlite"
    snapshot.write_bytes(b"synthetic source")
    receipt = tmp_path / "receipt.json"
    argv = ["import_database", "--snapshot", str(snapshot), "--receipt", str(receipt)]
    monkeypatch.setattr(sys, "argv", [*argv, "--source-quiescent"])
    monkeypatch.delenv("POSTGRES_IMPORT_DSN", raising=False)
    db = Mock(open=AsyncMock(), close=AsyncMock())
    database = Mock(return_value=db)
    importer = AsyncMock(return_value=ImportReceipt("a" * 64, "b" * 64, {"sessions": 2}))
    monkeypatch.setattr(import_database, "PostgresDatabase", database)
    monkeypatch.setattr(import_database, "import_snapshot", importer)
    return snapshot, receipt, database, db, importer


def test_import_requires_explicit_quiescence(import_command, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", sys.argv[:-1])
    with pytest.raises(SystemExit) as exc:
        asyncio.run(import_database.main())
    assert exc.value.code == 2
    assert "--source-quiescent" in capsys.readouterr().err
    _, receipt, database, _, _ = import_command
    database.assert_not_called()
    assert not receipt.exists()


def test_import_requires_an_environment_identity(import_command, capsys):
    _, receipt, database, _, _ = import_command
    assert asyncio.run(import_database.main()) == 2
    assert "POSTGRES_IMPORT_DSN is required" in capsys.readouterr().out
    database.assert_not_called()
    assert not receipt.exists()


def test_import_writes_private_receipt_and_preserves_source(import_command, monkeypatch, capsys):
    snapshot, receipt, database, db, importer = import_command
    monkeypatch.setenv("POSTGRES_IMPORT_DSN", "fixture-import")
    assert asyncio.run(import_database.main()) == 0
    database.assert_called_once_with("fixture-import", pool_size=2)
    db.open.assert_awaited_once()
    importer.assert_awaited_once_with(db, snapshot, source_quiescent=True)
    db.close.assert_awaited_once()
    assert json.loads(receipt.read_text()) == {
        "source_sha256": "a" * 64,
        "canonical_sha256": "b" * 64,
        "counts": {"sessions": 2},
        "source_schema_version": 2,
        "already_imported": False,
    }
    assert stat.S_IMODE(receipt.stat().st_mode) == 0o600
    assert snapshot.read_bytes() == b"synthetic source"
    assert "Import verified" in capsys.readouterr().out


@pytest.mark.parametrize("failure", ["driver", "receipt_exists"])
def test_import_failure_is_redacted_and_closes_database(
    import_command, monkeypatch, capsys, failure
):
    _, receipt, _, db, importer = import_command
    monkeypatch.setenv("POSTGRES_IMPORT_DSN", "fixture-import")
    if failure == "driver":
        importer.side_effect = RuntimeError("synthetic private row")
        expected = "RuntimeError"
    else:
        receipt.write_text("previous receipt")
        expected = "FileExistsError"

    assert asyncio.run(import_database.main()) == 1
    captured = capsys.readouterr()
    assert f"Import failed ({expected})" in captured.out
    assert "synthetic private row" not in captured.out + captured.err
    db.close.assert_awaited_once()
    if failure == "receipt_exists":
        assert receipt.read_text() == "previous receipt"
    else:
        assert not receipt.exists()
