"""Evaluation gates that are deterministic: retrieval ranking, safety across all scenarios, and the
server-side guards against a misbehaving model. Fixture answer quality is not asserted."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import evaluate_conversations
import evaluate_corpus
import evaluate_retrieval

from app.bootstrap.config import Settings


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        environment='test',
        messages_per_session_per_day=100,  # type: ignore[call-arg]
        messages_per_client_per_hour=1000,
        sessions_per_client_per_hour=1000,
    )


def test_retrieval_quality_floor() -> None:
    report = evaluate_retrieval.evaluate()
    assert report['recall_at_3'] >= 0.9
    assert report['mrr'] >= 0.85


def test_every_scenario_is_safe_in_fixture_mode() -> None:
    results = evaluate_conversations.run_conversations(_settings())
    assert len(results) >= 15
    assert [r for r in results if r['safety']] == []


def test_server_side_guards_hold_against_a_misbehaving_model() -> None:
    results = evaluate_conversations.run_guards(_settings())
    assert len(results) >= 10
    assert [r for r in results if r['problems']] == []


# --- evaluation corpus (evals/corpus) -------------------------------------------------------------

# Regression floors only for families where lexical ranking already meets them (measured
# 2026-10-05: 0.80-0.93 recall@3). Other families are reported, not gated: see docs/evaluation.md.
FAMILY_RECALL_FLOORS = {
    'age-fit': 0.75,
    'comparison-resources': 0.75,
    'delivery-and-access': 0.75,
    'follow-ups': 0.75,
    'price-and-currency': 0.75,
    'product-contents': 0.75,
    'refunds-guarantee-withdrawal': 0.75,
}


def test_corpus_is_valid_and_split_without_leakage() -> None:
    cases = evaluate_corpus.load()
    assert evaluate_corpus.validate(cases) == []
    assert len(cases) >= 250
    families = {c['family'] for c in cases}
    assert len(families) >= 18
    for family in families:
        members = [c for c in cases if c['family'] == family]
        dev = sum(c['split'] == 'dev' for c in members) / len(members)
        assert 0.6 <= dev <= 0.85, family
    splits_by_group: dict[str, set[str]] = {}
    for case in cases:
        splits_by_group.setdefault(case['group'], set()).add(case['split'])
    assert all(len(s) == 1 for s in splits_by_group.values())


def test_corpus_retrieval_floors() -> None:
    report = evaluate_corpus.retrieval(evaluate_corpus.load())
    assert report['overall']['recall_at_3'] >= 0.65
    for family, floor in FAMILY_RECALL_FLOORS.items():
        assert report['by_family'][family]['recall_at_3'] >= floor, family


# Known reply-language detector misses (app/domain/language.py), kept explicit so a fix or a new
# regression changes this set and fails the test. lang-016: "Quanto custa o kit e como faço para
# comprar?" is detected as unknown (shares "kit", "como", "para" with Spanish) and gets Spanish.
KNOWN_LANGUAGE_MISSES = {'lang-016'}


def test_every_corpus_case_passes_the_pipeline_gates_in_fixture_mode() -> None:
    cases = evaluate_corpus.load()
    results = evaluate_corpus.run_pipeline(evaluate_corpus.settings_for_eval(), cases)
    assert len(results) == len(cases)
    assert [(r['id'], r['gates']) for r in results if r['gates']] == []
    assert {r['id'] for r in results if r['language']} == KNOWN_LANGUAGE_MISSES
