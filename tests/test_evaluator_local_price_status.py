"""Actual local price guard through in-process ASGI only; no TCP/service/provider/SDK calls."""

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.bootstrap.config import DEFAULT_CATALOG, Settings
from app.bootstrap.container import create_app
from app.domain.catalog import ActiveCatalog, PriceStatus
from scripts.evaluate_conversations import CATALOG, HEADERS, _events, _safety
from scripts.evaluate_end_to_end import (
    EvidenceProvider,
    catalog_price_snapshot,
    safety_price_status,
    safety_with_official_evidence,
)


class Clock:
    def __init__(self, now):
        self.value = now

    def now(self):
        return self.value


def test_exact_failed_local_equality_uses_actual_active_catalog_and_same_app_clock(tmp_path):
    clock = Clock(CATALOG.generated_at + timedelta(hours=1))
    provider = EvidenceProvider()
    settings = Settings(
        _env_file=None,
        environment='test',
        catalog_file=DEFAULT_CATALOG,
        catalog_url=None,
        database_path=str(tmp_path / 'isolated.sqlite3'),
        allowed_origins=['http://localhost:3000'],
    )
    app = create_app(settings, provider=provider, clock=clock)
    with TestClient(app) as http:
        services = app.state.services
        assert services.clock is clock
        active = services.catalog.active
        assert active is not None and active.catalog.generated_at == CATALOG.generated_at
        proof = catalog_price_snapshot(services)
        assert proof == {
            'status': 'verified',
            'catalog_sha256': active.sha256,
            'verified_at': CATALOG.generated_at.isoformat(),
            'snapshot_at': clock.now().isoformat(),
            'max_age_seconds': settings.catalog_price_max_age_hours * 3600,
        }
        session = http.post('/api/v1/session', headers=HEADERS, json={'locale': 'es'}).json()
        response = http.post(
            '/api/v1/messages',
            headers={
                **HEADERS,
                'X-CSRF-Token': session['csrf_token'],
                'Idempotency-Key': 'eval-local-price-01',
            },
            json={'content': '¿Ambos tienen el mismo precio?', 'page': 'product', 'response_language': 'es'},
        )
        assert response.status_code == 200
        events = _events(response.text)
        answer = next(event['message'] for event in events if event['type'] == 'message.completed')
        assert provider.records == []  # Local application guard, not generated/fixture model output.
        assert '14,99' in answer['content'] or '14.99' in answer['content']
        assert _safety(events, PriceStatus.UNVERIFIED)  # Original evaluator false RED reproduced.
        status = safety_price_status(provider.records, proof)
        assert status is PriceStatus.VERIFIED
        assert safety_with_official_evidence(events, status, []) == []
        # Correct freshness cannot exempt a genuine price hallucination from the existing gate.
        invalid = json.loads(json.dumps(events))
        completed = next(event['message'] for event in invalid if event['type'] == 'message.completed')
        completed['content'] = 'Ambos cuestan USD 999999.'
        assert safety_with_official_evidence(invalid, status, [])


@pytest.mark.parametrize(
    ('hours', 'expected'),
    [(0, PriceStatus.VERIFIED), (168, PriceStatus.VERIFIED), (169, PriceStatus.UNVERIFIED)],
)
def test_fresh_stale_and_exact_boundary_use_active_catalog_rule(hours, expected):
    clock = Clock(CATALOG.generated_at + timedelta(hours=hours))
    active = ActiveCatalog(CATALOG, 'a' * 64, CATALOG.generated_at, timedelta(hours=168))
    services = SimpleNamespace(catalog=SimpleNamespace(active=active), clock=clock)
    proof = catalog_price_snapshot(services)
    assert safety_price_status([], proof) is expected
    assert proof['snapshot_at'] == clock.value.isoformat()
    assert proof['verified_at'] == active.verified_at.isoformat()
    # Future/untrusted reply metadata cannot change the source snapshot.
    assert 'reply' not in proof


def test_missing_active_catalog_is_unverified_and_prepared_status_stays_authoritative():
    clock = Clock(CATALOG.generated_at)
    proof = catalog_price_snapshot(SimpleNamespace(catalog=SimpleNamespace(active=None), clock=clock))
    assert safety_price_status([], proof) is PriceStatus.UNVERIFIED
    assert proof['catalog_sha256'] is proof['verified_at'] is proof['max_age_seconds'] is None
    assert safety_price_status([{'price_status': 'verified'}], proof) is PriceStatus.VERIFIED
    verified = {**proof, 'status': 'verified'}
    assert safety_price_status([{'price_status': 'unverified'}], verified) is PriceStatus.UNVERIFIED
    with pytest.raises(ValueError, match='not a valid PriceStatus'):
        safety_price_status([{'price_status': 'invented'}], verified)


def test_snapshot_uses_actual_verified_at_not_static_export_date_or_wall_clock():
    # A live source may have reverified unchanged exported facts; use its real active timestamp.
    verified = CATALOG.generated_at + timedelta(hours=24)
    clock = Clock(CATALOG.generated_at + timedelta(hours=169))
    active = ActiveCatalog(CATALOG, 'b' * 64, verified, timedelta(hours=168))
    proof = catalog_price_snapshot(SimpleNamespace(catalog=SimpleNamespace(active=active), clock=clock))
    assert proof['verified_at'] == verified.isoformat()
    assert proof['catalog_sha256'] == active.sha256
    assert safety_price_status([], proof) is PriceStatus.VERIFIED
