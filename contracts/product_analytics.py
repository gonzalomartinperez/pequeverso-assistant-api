"""Independent Peque profile/report artifacts; no reuse of Portfolio runtime wire models."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from app.domain.product_analytics import PROFILE, PROFILE_SOURCE
from app.presentation.product_analytics import EventIn, ReportOut, SelectionOut
from contracts.analytics_semantics import SEMANTICS


def artifacts() -> dict[str, bytes]:
    now = datetime(2026, 10, 18, 12, tzinfo=UTC)
    report = ReportOut(
        synthetic=True,
        generated_at=now,
        selection=SelectionOut(
            period='day', offset=0, route='/', section_id='hero', viewport_bucket='all', locale='es'
        ),
        start=now.replace(hour=0),
        end=datetime(2026, 10, 19, tzinfo=UTC),
        partial=True,
        first_observed_at=now,
        last_observed_at=now,
        totals={'page_views': 2, 'section_views': 3, 'public_clicks': 4},
        daily=[{'day': '2026-10-18', 'page_views': 2, 'section_views': 3, 'public_clicks': 4}],
        countries=[{'code': 'unknown', 'count': 9}],
        grid={
            'available': True,
            'visible_clicks': 3,
            'withheld_clicks': 1,
            'unselected_clicks': 0,
            'cells': [{'x': 2, 'y': 4, 'count': 3}],
        },
    )
    values: dict[str, Any] = {
        'analytics-semantics.examples.json': SEMANTICS,
        'site-experience-pequeverso-v1.schema.json': EventIn.model_json_schema(),
        'product-analytics.schema.json': ReportOut.model_json_schema(mode='serialization'),
        'examples/product-analytics.json': {
            'fixture': True,
            'scope': 'local_synthetic_product_analytics',
            'report': report.model_dump(mode='json'),
        },
        'product-analytics.source.json': {
            'contract_revision': '1.1',
            'profile_source_revision': PROFILE_SOURCE,
            'source_repository': 'gonzalomartinperez/pequeverso',
            'layout_revision': 'pequeverso-v1',
            'routes': {route: list(sections) for route, sections in PROFILE.items()},
            'locales': ['es'],
            'viewport_widths_css_px': {'mobile': [0, 767], 'tablet': [768, 1023], 'desktop': [1024, None]},
            'public_endpoint': '/api/v1/analytics/events',
            'private_endpoint': '/internal/v1/ops/product-analytics',
            'scope': 'committed_profile_reference_not_production_collection_or_deployment',
            'pointer_only_clicks': True,
            'country_collection': 'disabled',
            'country_collection_modes': ['disabled', 'trusted_proxy_header'],
            'classification': 'persisted synthetic boolean; production environment only selects false namespace',
            'country_configuration_is_not_edge_verification': True,
        },
    }
    result = {
        name: (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
        for name, value in values.items()
    }
    provenance = values['product-analytics.source.json']
    provenance['artifacts_sha256'] = {
        name: hashlib.sha256(body).hexdigest()
        for name, body in result.items()
        if name != 'product-analytics.source.json'
    }
    result['product-analytics.source.json'] = (
        json.dumps(provenance, ensure_ascii=False, indent=2) + '\n'
    ).encode()
    return result
