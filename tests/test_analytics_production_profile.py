"""Production-capable configuration/HTTP with injected rows, no services or model dispatch."""

import asyncio
import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.application.product_analytics import AnalyticsService, Bucket
from app.bootstrap.config import Settings
from app.domain.product_analytics import Selection
from app.presentation.product_analytics import ReportOut, build_router
from tests.test_product_analytics import NOW, Rows, event
from tests.test_product_analytics_http import AUTH, HEADERS, ORIGIN, PATH, PRIVATE, TOKEN, Clock, Store


def production_settings(enabled=True):
    # Existing assistant/provider/security gates stay intact. No provider is constructed here.
    return Settings(
        _env_file=None,
        environment='production',
        assistant_enabled=False,
        session_cookie_secure=True,
        allowed_origins=['https://fixture.invalid'],
        client_hash_key='synthetic-production-test-key-at-least32chars',
        application_storage='postgres',
        knowledge_backend='graphrag',
        postgres_knowledge_dsn='postgresql://synthetic:synthetic@127.0.0.1/unused',
        neo4j_uri='bolt://127.0.0.1:7687',
        neo4j_password='synthetic-unused',
        postgres_private_dsn='postgresql://synthetic:synthetic@127.0.0.1/unused',
        product_analytics_enabled=enabled,
        product_analytics_country_enabled=True,
        product_analytics_country_proxy_ips='172.20.0.5',
    )


@pytest.mark.parametrize('enabled', [False, True])
def test_production_configuration_allows_opt_in_without_relaxing_assistant_gates(enabled):
    settings = production_settings(enabled)
    assert settings.product_analytics_enabled is enabled
    assert settings.environment == 'production' and settings.ai_provider == 'fixture'
    with pytest.raises(ValidationError, match='production cannot serve fixture answers'):
        Settings(**{**settings.model_dump(), 'assistant_enabled': True}, _env_file=None)


@pytest.mark.parametrize('enabled', [False, True])
def test_actual_production_class_http_channel_on_off_and_server_only_country(enabled):
    settings = production_settings(enabled)

    class Capture(Store):
        last = None

        async def ingest(self, value, now):
            self.last = value
            return await super().ingest(value, now)

    store = Capture()
    app = FastAPI()
    app.include_router(
        build_router(
            AnalyticsService(
                store,
                synthetic=settings.environment != 'production',
                country_collection='trusted_proxy_header',
            ),
            enabled=settings.product_analytics_enabled,
            token_digest=hashlib.sha256(TOKEN.encode()).digest(),
            origins=(ORIGIN,),
            clock=Clock(),
            country_enabled=settings.product_analytics_country_enabled,
            country_proxy_ips=settings.product_analytics_country_proxy_ips,
        )
    )
    with TestClient(app, client=('172.20.0.5', 123)) as http:
        assert http.post(PATH, json=event(), headers={**HEADERS, 'CF-IPCountry': 'AR'}).status_code == (
            204 if enabled else 404
        )
        response = http.get(PRIVATE, headers=AUTH)
        assert response.status_code == (200 if enabled else 404)
        if enabled:
            assert store.last.country == 'AR'
            assert response.json()['synthetic'] is False
            assert response.json()['country_collection'] == 'trusted_proxy_header'
            assert http.post(PATH, json=event(country='US'), headers=HEADERS).status_code == 422
        else:
            assert store.calls == store.checks == 0


def test_country_small_buckets_merge_without_erasing_unknown_and_history_survives_flag_off():
    async def run():
        rows = Rows(
            tuple(
                Bucket(NOW.replace(hour=0), 'page_view', -1, -1, count, NOW, NOW, country)
                for country, count in [('AR', 2), ('BR', 2), ('US', 3), ('unknown', 3)]
            )
        )
        for mode in ['disabled', 'trusted_proxy_header']:
            report = ReportOut.model_validate(
                await AnalyticsService(rows, synthetic=False, country_collection=mode).report(
                    NOW, Selection()
                )
            )
            assert [(r.code, r.count) for r in report.countries] == [
                ('US', 3),
                ('unknown', 3),
                ('withheld', 4),
            ]
            assert report.synthetic is False and report.totals.page_views == 10
            assert report.country_collection == mode

    asyncio.run(run())


def test_country_and_classification_wire_rejects_untrusted_labels_small_known_and_duplicate_groups():
    import json

    from contracts.product_analytics import artifacts

    original = json.loads(artifacts()['examples/product-analytics.json'])['report']
    for countries in [
        [{'code': 'ZZ', 'count': 9}],
        [{'code': 'AR', 'count': 2}, {'code': 'unknown', 'count': 7}],
        [{'code': 'AR', 'count': 4}, {'code': 'AR', 'count': 5}],
    ]:
        with pytest.raises(ValidationError):
            ReportOut.model_validate({**original, 'countries': countries})
    assert ReportOut.model_validate({**original, 'synthetic': False}).synthetic is False
    for synthetic in ['false', 0, None]:
        with pytest.raises(ValidationError):
            ReportOut.model_validate({**original, 'synthetic': synthetic})


def test_analytics_does_not_depend_on_fixture_ai_or_construct_a_provider():
    settings = production_settings()
    real_provider_config = Settings(
        **{
            **settings.model_dump(),
            'assistant_enabled': True,
            'ai_provider': 'openai',
            'allow_paid_ai': True,
            'openai_api_key': 'synthetic-not-a-live-key',
        },
        _env_file=None,
    )
    assert real_provider_config.product_analytics_enabled
    assert real_provider_config.ai_provider == 'openai'
    with pytest.raises(ValidationError, match='requires ALLOW_PAID_AI'):
        Settings(**{**real_provider_config.model_dump(), 'allow_paid_ai': False}, _env_file=None)
