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
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


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


# Each invalid example must fail on its intended path and keyword, and on nothing else.
EXPECTED: dict[tuple[str, str], tuple[list[str | int], str]] = {
    ("blocks", "bad-date-time"): (["blocks", 0, "price", "verified_at"], "pattern"),
    ("blocks", "extra-field"): (["blocks", 0], "additionalProperties"),
    ("blocks", "four-link-chips"): (["blocks"], "maxContains"),
    ("blocks", "html-in-text"): (["blocks", 0, "markdown_lite"], "not"),
    ("blocks", "http-url"): (["blocks", 0, "url"], "pattern"),
    ("blocks", "memory-free-text"): (["blocks", 0, "proposed_facts", 0, "key"], "enum"),
    ("blocks", "memory-value-outside-enum"): (["blocks", 0, "proposed_facts", 0, "value"], "enum"),
    ("blocks", "price-without-currency"): (["blocks", 0, "price"], "required"),
    ("blocks", "product-card-bad-kind"): (["blocks", 0, "kind"], "enum"),
    ("blocks", "unknown-notice-code"): (["blocks", 0, "code"], "enum"),
    ("blocks", "unknown-type"): (["blocks", 0, "type"], "enum"),
    ("blocks", "url-trailing-newline"): (["blocks", 0, "url"], "pattern"),
    ("run-progress", "missing-run-id"): ([], "required"),
    ("run-progress", "negative-sources"): (["sources_found"], "minimum"),
    ("run-progress", "string-sequence"): (["sequence"], "type"),
    ("run-progress", "unknown-phase"): (["phase"], "enum"),
    ("run-progress", "visitor-text"): ([], "additionalProperties"),
    ("run-progress", "wrong-type"): (["type"], "const"),
}


def test_every_invalid_example_has_an_expectation() -> None:
    found = {(p.parent.parent.name, p.stem) for n in NAMES for p in _examples(n, valid=False)}
    assert found == set(EXPECTED)


@pytest.mark.parametrize("key", sorted(EXPECTED), ids=lambda k: f"{k[0]}/{k[1]}")
def test_invalid_examples_fail_on_the_intended_keyword(key: tuple[str, str]) -> None:
    name, stem = key
    path = DRAFT / "examples" / name / "invalid" / f"{stem}.json"
    errors = list(_validator(name).iter_errors(_load(path)))
    assert [(list(e.absolute_path), e.validator) for e in errors] == [EXPECTED[key]]


def test_draft_is_not_published() -> None:
    manifest = (DRAFT.parent / "manifest.json").read_text(encoding="utf-8")
    assert "draft" not in manifest
