"""Run the real contract exporter with an isolated destination."""

import hashlib
import json
import sys
from pathlib import Path
from shutil import copytree, ignore_patterns

import pytest

from contracts import export


@pytest.fixture
def export_root(tmp_path, monkeypatch):
    root = tmp_path / "contracts"
    monkeypatch.setenv("AI_PROVIDER", "fixture")
    monkeypatch.setenv("ALLOW_PAID_AI", "false")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("APPLICATION_STORAGE", "sqlite")
    monkeypatch.setenv("KNOWLEDGE_BACKEND", "sqlite")
    monkeypatch.setenv("OFFICIAL_HELP_ENABLED", "false")
    monkeypatch.setattr(export, "ROOT", root)
    return root


def test_check_accepts_committed_contracts_then_reports_missing_and_changed_files(
    export_root, monkeypatch, capsys
):
    copytree(
        Path(export.__file__).parent,
        export_root,
        ignore=ignore_patterns("*.py", "__pycache__"),
    )
    monkeypatch.setattr(sys, "argv", ["contracts.export", "--check"])
    assert export.main() == 0
    assert capsys.readouterr().out == ""

    changed = export_root / "openapi.json"
    changed.write_text("{}\n")
    missing = export_root / "examples/stream.failed.sse"
    missing.unlink()

    assert export.main() == 1
    output = capsys.readouterr().out
    assert "stale contract artifacts" in output
    assert set(output.strip().split("): ", 1)[1].split(", ")) == {
        "openapi.json",
        "examples/stream.failed.sse",
    }
    assert changed.read_text() == "{}\n"
    assert not missing.exists()


def test_write_creates_versioned_artifacts_and_hashes(tmp_path, export_root, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["contracts.export"])
    assert export.main() == 0

    manifest = json.loads((export_root / "manifest.json").read_text())
    files = {
        path.relative_to(export_root).as_posix()
        for path in export_root.rglob("*")
        if path.is_file()
    }
    assert manifest["contract_version"] == "1"
    assert set(manifest["artifacts"]) == files - {"manifest.json"}
    for name, digest in manifest["artifacts"].items():
        assert hashlib.sha256((export_root / name).read_bytes()).hexdigest() == digest

    public = json.loads((export_root / "openapi.json").read_text())["paths"]
    internal = json.loads((export_root / "openapi.internal.json").read_text())["paths"]
    assert "/api/v1/session" not in internal
    assert all(not path.startswith("/internal/") for path in public)
    for status in ("200", "201"):
        links = public["/api/v1/session"]["post"]["responses"][status]["links"]
        assert set(links) == {"session_to_message", "session_to_cancel", "session_to_delete"}
        assert all(
            link["parameters"]["x-csrf-token"] == "$response.body#/csrf_token"
            for link in links.values()
        )

    assert list(tmp_path.iterdir()) == [export_root]


def test_unknown_argument_is_rejected_without_creating_files(export_root, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["contracts.export", "--unknown"])
    with pytest.raises(SystemExit) as exc:
        export.main()
    assert exc.value.code == 2
    assert "unrecognized arguments: --unknown" in capsys.readouterr().err
    assert not export_root.exists()
