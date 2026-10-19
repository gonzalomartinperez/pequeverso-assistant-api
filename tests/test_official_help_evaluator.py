"""Opt-in evaluation evidence recording uses the actual request, not a mutable source cache."""

from __future__ import annotations

import asyncio
import copy
import json

import pytest

from app.ai.provider import ModelInput, ModelRequest
from app.domain.catalog import PriceStatus
from app.domain.web_evidence import SOURCES
from scripts.evaluate_conversations import _safety
from scripts.evaluate_end_to_end import (
    EvidenceProvider,
    official_help_requested,
    safety_with_official_evidence,
)
from tests.support import ScriptedProvider


@pytest.mark.parametrize('value', [None, 0, 1, 'true', [], {}])
def test_manifest_rejects_nonboolean_web_opt_in(value: object) -> None:
    with pytest.raises(ValueError, match='must be a boolean'):
        official_help_requested({'official_help_enabled': value})


def test_manifest_defaults_off_and_accepts_explicit_boolean() -> None:
    assert official_help_requested({}) is False
    assert official_help_requested({'official_help_enabled': False}) is False
    assert official_help_requested({'official_help_enabled': True}) is True


def test_recorder_captures_only_actual_external_payload_and_no_private_prompt() -> None:
    catalog = {
        'price_status': 'verified',
        'products': [],
        'documents': {
            'columns': ['id', 'kind', 'title', 'text', 'product_ids'],
            'rows': [
                [
                    'policy.guarantee',
                    'policy',
                    'Guarantee',
                    'Complete public condition.',
                    ['grafismo-fonetico'],
                ]
            ],
        },
        'links': [],
    }
    actual = [
        {
            'id': 'hotmart:209033897',
            'title': SOURCES[0].title,
            'text': 'Synthetic procedure actually sent, not a newer global-cache article.',
            'verified_at': '2026-10-13T00:00:00+00:00',
            'sha256': '1' * 64,
            'scope': 'general_platform_procedure_not_merchant_facts',
        }
    ]
    provider = EvidenceProvider()
    provider.fixture = ScriptedProvider()  # type: ignore[assignment]
    request = ModelRequest(
        'PRIVATE-INSTRUCTIONS-SENTINEL',
        (
            ModelInput('user', 'store_data:\n' + json.dumps(catalog)),
            ModelInput('user', 'official_platform_data:\n' + json.dumps(actual)),
            ModelInput('user', 'visitor_turn:\nPRIVATE-HISTORY-SENTINEL'),
        ),
        {},
        4000,
        'private-session-sentinel',
        'cache-key',
    )

    async def run() -> None:
        async for _ in provider.stream(request):
            pass

    asyncio.run(run())
    assert provider.records[0]['official_platform'] == actual
    assert provider.records[0]['documents'] == ['policy.guarantee']
    serialized = json.dumps(provider.records)
    assert not any(s in serialized for s in ['PRIVATE-INSTRUCTIONS', 'PRIVATE-HISTORY', 'private-session'])
    # The absent-field baseline remains exactly the old evidence-record shape.
    provider.records.clear()
    request = ModelRequest('', (ModelInput('user', 'store_data:\n' + json.dumps(catalog)),), {}, 4000, '', '')
    asyncio.run(run())
    assert set(provider.records[0]) == {
        'sha256',
        'bytes',
        'price_status',
        'products',
        'resources',
        'documents',
        'links',
    }


def events_for(citation: dict[str, str]) -> list[dict[str, object]]:
    return [
        {'type': 'run.started'},
        {
            'type': 'message.completed',
            'message': {
                'content': 'Consulta el procedimiento general.',
                'products': [],
                'resources': [],
                'links': [],
                'sources': [citation],
            },
        },
        {'type': 'run.completed'},
    ]


def test_evaluator_accepts_only_exact_actually_sent_external_citation_without_mutating_events() -> None:
    source = SOURCES[0]
    citation = {'id': 'hotmart:209033897', 'title': source.title, 'url': source.url}
    events = events_for(citation)
    original = copy.deepcopy(events)
    evidence = [{'official_platform': [{'id': 'hotmart:209033897'}]}]
    assert _safety(events, PriceStatus.VERIFIED)  # old catalog-only URL gate remains strict
    assert safety_with_official_evidence(events, PriceStatus.VERIFIED, evidence) == []
    assert events == original
    for changes in [
        {'url': source.url + '?redirect=evil'},
        {'title': 'Other'},
        {'id': 'hotmart:360061973392'},
    ]:
        altered = events_for({**citation, **changes})
        assert safety_with_official_evidence(altered, PriceStatus.VERIFIED, evidence)
    assert safety_with_official_evidence(events, PriceStatus.VERIFIED, [])


@pytest.mark.parametrize('cap', [0, 651, True, 1.5, '650'])
def test_helper_rejects_invalid_attempt_cap_before_reading_key(tmp_path, monkeypatch, cap):
    from scripts import evaluate_end_to_end as evaluator

    reads = []
    monkeypatch.setattr(evaluator, 'dotenv_values', lambda *args, **kwargs: reads.append(True))
    with pytest.raises(ValueError, match='attempt cap must be an integer'):
        evaluator.load_live_provider(tmp_path / 'key.env', tmp_path / 'shared.sqlite3', max_attempts=cap)
    assert reads == [] and list(tmp_path.iterdir()) == []


def test_extended_helper_refuses_new_budget_path_before_key_read(tmp_path, monkeypatch):
    from scripts import evaluate_end_to_end as evaluator

    reads = []
    monkeypatch.setattr(evaluator, 'dotenv_values', lambda *args, **kwargs: reads.append(True))
    with pytest.raises(ValueError, match='existing shared evaluation budget'):
        evaluator.load_live_provider(tmp_path / 'key.env', tmp_path / 'new.sqlite3', max_attempts=650)
    assert reads == [] and list(tmp_path.iterdir()) == []


def test_existing_attempt_cap_mismatch_is_checked_before_credential_read(tmp_path, monkeypatch):
    from scripts import evaluate_end_to_end as evaluator
    from scripts.real_eval_budget import Envelope

    budget = tmp_path / 'shared.sqlite3'
    envelope = Envelope(budget)
    envelope.reserve()
    before = envelope.snapshot()
    key = tmp_path / 'synthetic.env'
    key.write_text('This is not a real credential and must not be read.\n')
    key.chmod(0o600)
    reads = []
    monkeypatch.setattr(evaluator, 'dotenv_values', lambda *args, **kwargs: reads.append(True))
    with pytest.raises(ValueError, match=r'attempt limit|attempt cap'):
        evaluator.load_live_provider(key, budget, max_attempts=650)
    assert reads == [] and envelope.snapshot() == before
