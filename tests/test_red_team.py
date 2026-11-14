"""Red-team pack (PVA-M2.7): composition rules, the LLM10 refusal grader and the CLI wiring."""

from __future__ import annotations

import copy
from collections import Counter
from typing import Any

import pytest

from evals import graders, runner, schema

ITEMS = schema.load(schema.RED_TEAM)
ACTIVE = [item for item in ITEMS if item["status"] != "retired"]


def test_committed_pack_is_valid_and_sized_per_plan() -> None:
    assert schema.validate_red_team(ITEMS) == []
    low, high = schema.RED_TEAM_SIZE
    assert low <= len(ACTIVE) <= high
    per_class = Counter(item["owasp"] for item in ACTIVE)
    assert set(per_class) == schema.OWASP
    assert min(per_class.values()) >= schema.RED_TEAM_MIN_PER_CLASS


def test_every_non_active_attack_explains_itself() -> None:
    for item in ITEMS:
        if item["status"] != "active":
            assert item.get("status_reason"), item["id"]


def test_attacks_pin_the_bundled_catalog_and_are_adversarial() -> None:
    assert {item["catalog_sha256"] for item in ITEMS} == {schema.catalog_sha256()}
    assert all("adversarial" in item["strata"] for item in ITEMS)


def _mutated(**changes: Any) -> list[dict[str, Any]]:
    items = copy.deepcopy(ITEMS)
    items[0].update(changes)
    return items


@pytest.mark.parametrize(
    ("items", "message"),
    [
        (_mutated(owasp="LLM99"), "owasp must be one of"),
        (_mutated(owasp=None), "owasp must be one of"),
        (_mutated(id="g-999", group="g-999"), "ids in this set start with r-"),
        (copy.deepcopy(ITEMS[:39]), "plan says 40 to 60"),
    ],
)
def test_pack_rules_reject_malformed_packs(items: list[dict[str, Any]], message: str) -> None:
    assert any(message in problem for problem in schema.validate_red_team(items))


def test_a_class_below_three_attacks_is_rejected() -> None:
    items = [i for i in copy.deepcopy(ITEMS) if i["owasp"] != "LLM10"]
    items += [i for i in copy.deepcopy(ITEMS) if i["owasp"] == "LLM10"][:2]
    assert any("OWASP LLM10: 2 attacks" in p for p in schema.validate_red_team(items))


def test_refused_is_red_team_only_and_turns_must_still_be_strings() -> None:
    refused = next(item for item in ITEMS if item["expected_behavior"] == "refused")
    golden_like = {**copy.deepcopy(refused), "id": "g-901", "group": "g-901"}
    problems = schema.validate([golden_like], counts=False, split_family="red-team")
    assert any("refused is a red-team behaviour" in p for p in problems)
    bad_turns = {**copy.deepcopy(refused), "turns": [None]}
    problems = schema.validate([bad_turns], counts=False, split_family="red-team")
    assert any("turns must be" in p for p in problems)


def _ctx(item: dict[str, Any], gates: tuple[str, ...], final: dict[str, Any] | None) -> Any:
    return graders.GradeContext(
        item=item, final=final, stale=False, user_notices=frozenset(), gates=gates
    )


def test_request_refused_grader_needs_a_refusal_and_no_message() -> None:
    item = next(item for item in ITEMS if item["expected_behavior"] == "refused")
    invalid = 'request refused: HTTP 422 {"error":{"code":"invalid_request"}}'
    assert graders.grade(_ctx(item, (invalid,), None)) == {}
    for wrong in ("request refused: HTTP 403 {}", "request refused: HTTP 429 {}"):
        assert graders.grade(_ctx(item, (wrong,), None)) == {
            "request.refused": ["the request was accepted"]
        }
    accepted = graders.grade(_ctx(item, (), None))
    assert accepted == {"request.refused": ["the request was accepted"]}
    message = {"content": "hola", "links": [], "notices": []}
    produced = graders.grade(_ctx(item, (invalid,), message))
    assert produced == {"request.refused": ["a final message was produced"]}


def test_runner_offers_both_sets_with_their_own_cassettes() -> None:
    assert set(runner.SETS) == {"golden", "red-team"}
    assert runner.SETS["red-team"][1] == runner.RED_TEAM_CASSETTES
    assert runner.SETS["golden"][1] == runner.CASSETTES


def test_refused_items_have_one_turn_and_no_assertions() -> None:
    refused = next(item for item in ITEMS if item["expected_behavior"] == "refused")
    for changes in ({"turns": ["hola", "x" * 700]}, {"assertions": ["abstain.shape"]}):
        items = copy.deepcopy(ITEMS)
        target = next(i for i in items if i["id"] == refused["id"])
        target.update(changes)
        assert any("exactly one turn" in p for p in schema.validate_red_team(items))


def test_golden_validation_rejects_red_team_ids() -> None:
    golden = schema.load()
    items = copy.deepcopy(golden)
    items[0]["id"] = "r-900"
    problems = schema.validate(items, counts=False)
    assert any("ids in this set start with g-" in p for p in problems)
