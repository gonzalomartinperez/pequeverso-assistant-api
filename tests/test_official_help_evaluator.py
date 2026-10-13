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
    catalog = {'price_status': 'verified', 'products': [], 'documents': [], 'links': []}
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
