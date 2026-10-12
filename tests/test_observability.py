"""Optional app-only telemetry never exports user content, credentials or raw URLs."""

import asyncio
import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from starlette.responses import JSONResponse

from app.adapters.observability import RuntimeTelemetry, TelemetryMiddleware
from app.application.operations import RunWindow
from app.bootstrap.config import Settings
from app.bootstrap.container import create_app

TOKEN = 'synthetic-ops-bearer-private-01234567890123456789'
AUTH = {'Authorization': f'Bearer {TOKEN}'}


def settings(tmp_path, **overrides):
    return Settings(
        _env_file=None,
        environment='test',
        database_path=str(tmp_path / 'api.sqlite3'),
        ai_provider='fixture',
        allow_paid_ai=False,
        openai_api_key=None,
        ops_read_token=TOKEN,
        **overrides,
    )


def test_observability_is_disabled_by_default_and_legacy_summary_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv('OTEL_EXPORTER_OTLP_ENDPOINT', 'http://127.0.0.1:1')
    with TestClient(create_app(settings(tmp_path))) as client:
        assert client.get('/internal/v1/ops/telemetry', headers=AUTH).status_code == 404
        assert client.get('/internal/v1/ops/metrics', headers=AUTH).status_code == 404
        summary = client.get('/internal/v1/ops/summary', headers=AUTH).json()
        assert 'telemetry' not in summary
        assert set(summary) == {
            'schema_version',
            'generated_at',
            'service',
            'availability',
            'catalog',
            'budget',
            'windows',
            'daily',
            'metrics_since',
            'pricing',
            'recent',
        }


def test_private_metrics_and_telemetry_require_bearer_and_do_not_probe_provider(tmp_path):
    with TestClient(create_app(settings(tmp_path, observability_enabled=True))) as client:
        for path in ('/internal/v1/ops/telemetry', '/internal/v1/ops/metrics'):
            assert client.get(path).status_code == 401
            assert client.get(path, headers={'Authorization': 'Bearer nope'}).status_code == 401
        assert client.get('/api/v1/ops/metrics', headers=AUTH).status_code == 404
        state = client.get('/internal/v1/ops/telemetry', headers=AUTH).json()
        assert state['schema_version'] == '1'
        assert state['readiness']['measurement'] == 'point_in_time'
        assert state['readiness']['status'] == 'ready'
        assert state['provider_observation'] == {'status': 'unknown', 'reason': 'not_probed'}
        assert state['synthetic'] is True
        assert state['active_runs'] == 0 and state['max_concurrent_runs'] == 4
        assert state['traces']['last_export_success'] is None
        assert not state['traces']['enabled']
        metrics = client.get('/internal/v1/ops/metrics', headers=AUTH)
        assert metrics.status_code == 200 and metrics.headers['cache-control'] == 'no-store'
        assert 'pequeverso_http_requests_total' in metrics.text
        assert 'pequeverso_runs_window{outcome="completed"} 0.0' in metrics.text
        assert 'python_gc_' not in metrics.text and 'process_open_fds' not in metrics.text
        assert TOKEN not in json.dumps(state) + metrics.text
        assert 'uptime_percent' not in json.dumps(state)


@pytest.mark.parametrize(
    'endpoint',
    [
        'https://user:password@collector/v1/traces',
        'http://public.example/v1/traces',
        'http://collector/v1/traces?secret=value',
        'http://collector/v1/traces#secret',
        'file:///v1/traces',
    ],
)
def test_otlp_endpoint_rejects_unsafe_configuration(tmp_path, endpoint):
    with pytest.raises(ValueError, match='OTLP'):
        settings(tmp_path, observability_enabled=True, telemetry_otlp_endpoint=endpoint)


def test_otlp_endpoint_requires_explicit_observability(tmp_path):
    with pytest.raises(ValueError, match='OTLP'):
        settings(tmp_path, telemetry_otlp_endpoint='http://collector:4318/v1/traces')


def test_manual_traces_drop_inbound_context_raw_paths_headers_and_body():
    exporter = InMemorySpanExporter()

    async def ready():
        return True

    async def run_window():
        return RunWindow({}, {}, 0, [], [])

    telemetry = RuntimeTelemetry(
        started_at=datetime.now(UTC),
        synthetic=True,
        revision='abcdef0',
        ready=ready,
        active_runs=lambda: 0,
        max_runs=4,
        run_window=run_window,
        exporter=exporter,
        sampling_ratio=1,
    )

    async def app(scope, receive, send):
        # A malicious/unknown path is never a metric label or span name.
        await JSONResponse({'safe': True})(scope, receive, send)

    app = TelemetryMiddleware(app, telemetry, frozenset({'/api/v1/session'}))

    async def run():
        scope = {
            'type': 'http',
            'method': 'GET',
            'path': '/private-customer-secret',
            'query_string': b'key=private-query-secret',
            'headers': [
                (b'authorization', b'Bearer private-header-secret'),
                (b'traceparent', b'00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01'),
            ],
            'route': type('Route', (), {'path': '/untrusted-parameter-secret'})(),
        }
        messages = []

        async def send(message):
            messages.append(message)

        async def receive():
            return {'type': 'http.request', 'body': b'private-body-secret'}

        await app(scope, receive, send)
        assert telemetry.http_inflight == 0
        assert telemetry.trace_provider.force_flush(1000)
        metrics = (await telemetry.prometheus()).decode()
        spans = exporter.get_finished_spans()
        assert len(spans) == 1 and spans[0].parent is None
        assert spans[0].name == 'GET unmatched'
        assert set(spans[0].attributes) == {'http.request.method', 'http.route', 'http.response.status_code'}
        serialized = metrics + str(spans[0].attributes) + spans[0].name + str(spans[0].resource.attributes)
        for sentinel in (
            'private-customer-secret',
            'private-query-secret',
            'private-header-secret',
            'private-body-secret',
            'untrusted-parameter-secret',
            'aaaaaaaa',
        ):
            assert sentinel not in serialized
        assert 'service.instance.id' not in spans[0].resource.attributes

    asyncio.run(run())
    telemetry.shutdown()


def test_export_failure_is_content_free_and_never_changes_http_status(caplog):
    class FailingExporter(InMemorySpanExporter):
        def export(self, spans):
            raise RuntimeError('private-provider-and-credentials-sentinel')

    async def ready():
        return True

    async def window():
        return RunWindow({}, {}, 0, [], [])

    telemetry = RuntimeTelemetry(
        started_at=datetime.now(UTC),
        synthetic=True,
        revision=None,
        ready=ready,
        active_runs=lambda: 0,
        max_runs=4,
        run_window=window,
        exporter=FailingExporter(),
        sampling_ratio=1,
    )
    span = telemetry.begin('GET')
    telemetry.finish(span, 'GET', '/health/live', 200, 0.01)
    assert telemetry.trace_provider.force_flush(1000)
    state = asyncio.run(telemetry.snapshot())
    assert state.export_failures == 1 and state.last_export_success is False
    assert state.http_server_errors == 0
    assert 'private-provider-and-credentials-sentinel' not in caplog.text
    telemetry.shutdown()
