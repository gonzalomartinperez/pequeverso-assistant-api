"""Draft v1.7 block and `run.progress` schemas validate their examples (PVA-M2-X).

The schemas live in `contracts/draft/`: not exported, not in `contracts/manifest.json` and not part
of the published v1 contract. M5 promotes them through `contracts.export`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

DRAFT = Path(__file__).resolve().parents[1] / "contracts" / "draft"
NAMES = ("blocks", "run-progress")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _validator(name: str) -> Draft202012Validator:
    schema = _load(DRAFT / f"{name}.schema.json")
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _examples(name: str, *, valid: bool) -> list[Path]:
    folder = DRAFT / "examples" / name / ("" if valid else "invalid")
    return sorted(folder.glob("*.json"))


@pytest.mark.parametrize("name", NAMES)
def test_at_least_six_valid_and_invalid_examples(name: str) -> None:
    assert len(_examples(name, valid=True)) >= 6
    assert len(_examples(name, valid=False)) >= 6


@pytest.mark.parametrize(
    "path", [p for n in NAMES for p in _examples(n, valid=True)], ids=lambda p: p.stem
)
def test_valid_examples_validate(path: Path) -> None:
    errors = list(_validator(path.parent.name).iter_errors(_load(path)))
    assert errors == [], [e.message for e in errors]


@pytest.mark.parametrize(
    "path", [p for n in NAMES for p in _examples(n, valid=False)], ids=lambda p: p.stem
)
def test_invalid_examples_are_rejected(path: Path) -> None:
    assert not _validator(path.parent.parent.name).is_valid(_load(path))


def test_draft_is_not_published() -> None:
    manifest = (DRAFT.parent / "manifest.json").read_text(encoding="utf-8")
    assert "draft" not in manifest
