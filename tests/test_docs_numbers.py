"""The evaluation reference tracks the current offline evaluation data."""

from __future__ import annotations

from typing import TYPE_CHECKING

from scripts import docs_numbers

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_evaluation_numbers_are_current() -> None:
    assert docs_numbers.update_document(docs_numbers.DOCUMENT, check=True) == 0


def test_check_rejects_stale_numbers(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "evaluation.md"
    stale = f"# Evaluation\n\n{docs_numbers.START}\n\nStale counts\n\n{docs_numbers.END}\n\nMore text.\n"
    path.write_text(stale, encoding="utf-8")

    assert docs_numbers.update_document(path, check=True) == 1
    assert "Run uv run python -m scripts.docs_numbers" in capsys.readouterr().out
    assert path.read_text(encoding="utf-8") == stale

    assert docs_numbers.update_document(path, check=False) == 0
    refreshed = path.read_text(encoding="utf-8")
    assert refreshed.startswith(f"# Evaluation\n\n{docs_numbers.START}\n")
    assert refreshed.endswith(f"{docs_numbers.END}\n\nMore text.\n")
    assert docs_numbers.update_document(path, check=True) == 0
