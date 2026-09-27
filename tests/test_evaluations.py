"""Evaluation gates that are deterministic: retrieval ranking, safety across all scenarios, and the
server-side guards against a misbehaving model. Fixture answer quality is not asserted."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import evaluate_conversations
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
