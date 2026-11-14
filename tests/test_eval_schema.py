"""Golden-set schema v2 loader (PVA-M2.4): the committed set is valid; malformed items are rejected."""

from __future__ import annotations

import copy
import json
from collections import Counter
from typing import TYPE_CHECKING, Any

import pytest

from evals import schema
from scripts.evaluate_corpus import load as load_full_set

if TYPE_CHECKING:
    from pathlib import Path

ITEMS = schema.load()


def _with(index: int, **changes: Any) -> list[dict[str, Any]]:
    items = copy.deepcopy(ITEMS)
    items[index].update(changes)
    return items


def _problems(items: list[dict[str, Any]]) -> list[str]:
    return schema.validate(items, counts=False)


def test_committed_golden_set_is_valid_and_matches_the_plan() -> None:
    full_ids = {case["id"] for case in load_full_set()}
    assert schema.validate(ITEMS, full_set_ids=full_ids) == []
    assert len(ITEMS) == 60
    assert Counter(item["split"] for item in ITEMS) == {"dev": 42, "holdout": 18}


def test_every_item_pins_the_bundled_catalog() -> None:
    assert {item["catalog_sha256"] for item in ITEMS} == {schema.catalog_sha256()}


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"unexpected": 1}, "unknown keys"),
        ({"schema_version": 1}, "schema_version must be 2"),
        ({"turns": []}, "turns must be non-empty strings"),
        ({"turns": ["x" * 601]}, "600-character"),
        ({"strata": ["answerable", "abstain"]}, "exactly one primary stratum"),
        ({"strata": ["answerable", "slang"]}, "known tags"),
        ({"expected_behavior": "maybe"}, "invalid expected_behavior"),
        ({"response_language": "pt"}, "invalid response_language"),
        ({"locale": "fr"}, "invalid locale"),
        ({"gold_evidence_ids": ["document:nope"]}, "is not a catalog passage"),
        ({"gold_evidence_ids": []}, "needs gold_evidence_ids and required_facts"),
        ({"required_facts": []}, "needs gold_evidence_ids and required_facts"),
        ({"assertions": ["made.up"]}, "unknown grader"),
        ({"forbidden_claims": ["rudeness"]}, "unknown forbidden claim"),
        ({"forbidden_claims": ["term: "]}, "unknown forbidden claim"),
        ({"notices": ["confetti"]}, "unknown notice"),
        ({"provenance": "internet"}, "invalid provenance"),
        ({"catalog_sha256": "0" * 64}, "does not pin the bundled catalog"),
        ({"clock_offset_days": "10"}, "non-negative integer"),
        ({"status": "quarantined"}, "needs an owner and a deadline"),
        ({"status": "retired"}, "needs a status_reason"),
        ({"split": "holdout" if ITEMS[0]["split"] == "dev" else "dev"}, "group-preserving rule"),
        ({"strata": None}, "must be a list of strings"),
        ({"gold_evidence_ids": [["x"]]}, "must be a list of strings"),
        ({"locale": ["es"]}, "must be a string"),
        ({"forbidden_claims": [1]}, "must be a list of strings"),
        ({"required_facts": "414"}, "must be a list of strings"),
        ({"required_facts": [""]}, "empty alternative"),
        ({"required_facts": ["414|"]}, "empty alternative"),
        ({"assertions": []}, "answer items assert facts.required"),
        ({"clock_offset_days": True}, "non-negative integer"),
        ({"clock_offset_days": -1}, "non-negative integer"),
        ({"id": ""}, "id must look like g-001"),
        ({"id": 5}, "must be a string"),
        ({"locale": "en"}, "english tag"),
    ],
)
def test_malformed_answer_item_is_rejected(changes: dict[str, Any], message: str) -> None:
    assert any(message in problem for problem in _problems(_with(0, **changes)))


def test_missing_key_and_abstain_without_shape_assertion_are_rejected() -> None:
    items = copy.deepcopy(ITEMS)
    del items[0]["turns"]
    assert any("missing keys" in p for p in _problems(items))
    abstain = next(i for i, item in enumerate(ITEMS) if item["expected_behavior"] == "no_info")
    assert any("abstain.shape" in p for p in _problems(_with(abstain, assertions=[])))


def test_multi_turn_stratum_matches_the_number_of_turns() -> None:
    assert any("multi_turn" in p for p in _problems(_with(0, turns=["a", "b"])))


def test_duplicate_ids_and_full_set_collisions_are_rejected() -> None:
    items = [*copy.deepcopy(ITEMS), copy.deepcopy(ITEMS[0])]
    assert any("duplicate id" in p for p in _problems(items))
    assert any(
        "collides" in p for p in schema.validate(ITEMS, full_set_ids={ITEMS[0]["id"]}, counts=False)
    )


def test_stratum_counts_are_checked() -> None:
    assert any("stratum answerable" in p for p in schema.validate(ITEMS[1:], counts=True))


def test_loader_rejects_non_object_lines(tmp_path: Path) -> None:
    path = tmp_path / "golden.jsonl"
    path.write_text(json.dumps(ITEMS[0], ensure_ascii=False) + "\n\n[1, 2]\n", encoding="utf-8")
    with pytest.raises(TypeError, match="must be a JSON object"):
        schema.load(path)


def test_payment_refusal_needs_its_notice() -> None:
    index = next(
        i for i, it in enumerate(ITEMS) if it["expected_behavior"] == "refuse_payment_data"
    )
    assert any("payment_data_refused" in p for p in _problems(_with(index, notices=[])))


def test_clock_offsets_near_the_stale_boundary_are_rejected() -> None:
    assert any("0 (fresh) or above" in p for p in _problems(_with(0, clock_offset_days=7)))
