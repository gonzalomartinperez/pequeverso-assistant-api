"""Evaluation gates that are deterministic: retrieval ranking, safety across all scenarios, and the
server-side guards against a misbehaving model. Fixture answer quality is not asserted."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_conversations
import evaluate_corpus
import evaluate_retrieval

from app.bootstrap.config import Settings


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        messages_per_session_per_day=100,  # type: ignore[call-arg]
        messages_per_client_per_hour=1000,
        sessions_per_client_per_hour=1000,
    )


def test_retrieval_quality_floor() -> None:
    report = evaluate_retrieval.evaluate()
    assert report["recall_at_3"] >= 0.9
    assert report["mrr"] >= 0.85


def test_every_scenario_is_safe_in_fixture_mode() -> None:
    results = evaluate_conversations.run_conversations(_settings())
    assert len(results) >= 15
    assert [r for r in results if r["safety"]] == []


def test_server_side_guards_hold_against_a_misbehaving_model() -> None:
    results = evaluate_conversations.run_guards(_settings())
    assert len(results) >= 10
    assert [r for r in results if r["problems"]] == []


# --- full evaluation set (evals/full) -------------------------------------------------------------

# Regression floors only for families where lexical ranking already meets them (measured
# 2026-10-05: 0.80-0.93 recall@3). Other families are reported, not gated: see docs/reference/evaluation.md.
FAMILY_RECALL_FLOORS = {
    "age-fit": 0.75,
    "comparison-resources": 0.75,
    "delivery-and-access": 0.75,
    "follow-ups": 0.75,
    "price-and-currency": 0.75,
    "product-contents": 0.75,
    "refunds-guarantee-withdrawal": 0.75,
}


def test_corpus_is_valid_and_split_without_leakage() -> None:
    cases = evaluate_corpus.load()
    assert evaluate_corpus.validate(cases) == []
    assert len(cases) == 318  # 288 cleaned corpus v1 cases plus the 30 added in v2
    families = {c["family"] for c in cases}
    assert len(families) >= 18
    for family in families:
        members = [c for c in cases if c["family"] == family]
        dev = sum(c["split"] == "dev" for c in members) / len(members)
        assert 0.6 <= dev <= 0.85, family
    splits_by_group: dict[str, set[str]] = {}
    for case in cases:
        splits_by_group.setdefault(case["group"], set()).add(case["split"])
    assert all(len(s) == 1 for s in splits_by_group.values())


def test_corpus_retrieval_floors() -> None:
    report = evaluate_corpus.retrieval(evaluate_corpus.load())
    assert report["overall"]["recall_at_3"] >= 0.65
    for family, floor in FAMILY_RECALL_FLOORS.items():
        assert report["by_family"][family]["recall_at_3"] >= floor, family


def test_every_corpus_case_passes_the_pipeline_gates_in_fixture_mode() -> None:
    cases = evaluate_corpus.load()
    results = evaluate_corpus.run_pipeline(evaluate_corpus.settings_for_eval(), cases)
    assert len(results) == len(cases)
    assert [(r["id"], r["gates"]) for r in results if r["gates"]] == []
    # No accepted reply-language detector misses remain (lang-016 fixed with Portuguese markers).
    assert [r["id"] for r in results if r["language"]] == []


NATIVE_ENGLISH = {"lang-023", "lang-024", "lang-025", "lang-026"}


def test_english_cases_get_a_spanish_reply_in_fixture_mode() -> None:
    english = [c for c in evaluate_corpus.load() if c["locale"] == "en"]
    assert len(english) == 11  # 7 legacy full-set cases and the 4 added in v2
    results = evaluate_corpus.run_pipeline(evaluate_corpus.settings_for_eval(), english)
    flags = [(r["id"], r["gates"], r["language"]) for r in results if r["gates"] or r["language"]]
    assert flags == []
    # The grader of evals/graders.py (language.reply) runs on the new items through `assertions`.
    graded = {r["id"]: r["behavior"] for r in results if r["id"] in NATIVE_ENGLISH}
    assert set(graded) == NATIVE_ENGLISH
    assert [i for i, found in graded.items() if any("language.reply" in b for b in found)] == []
    native = [c for c in english if c.get("client") == "native"]
    assert {c["id"] for c in native} == NATIVE_ENGLISH
    assert all("language.reply" in c["assertions"] for c in native)
    assert all(c["response_language"] in ("es", "unsupported") for c in native)
