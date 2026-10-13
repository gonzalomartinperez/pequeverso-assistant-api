"""Optional app-only telemetry never exports user content, credentials or raw URLs."""

import asyncio
import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from starlette.responses import JSONResponse

from app.adapters.observability import RuntimeTelemetry, TelemetryMiddleware
from app.application.operations import RunWindow
from app.bootstrap.config import Settings
from app.bootstrap.container import create_app

TOKEN = 'test-only-' + '0' * 32  # Explicit dummy bearer; never a deployable credential.
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


def test_ambient_sdk_headers_are_rejected_before_any_exporter_is_created(tmp_path, monkeypatch):
    monkeypatch.setenv('OTEL_EXPORTER_OTLP_HEADERS', 'authorization=private-sentinel')
    with pytest.raises(ValueError, match='ambient OTEL') as rejected:
        settings(
            tmp_path, observability_enabled=True, telemetry_otlp_endpoint='http://collector:4318/v1/traces'
        )
    assert 'private-sentinel' not in str(rejected.value)


@pytest.mark.parametrize(
    ('path', 'token', 'inherits'),
    [
        ('/internal/v1/ops/summary', TOKEN, True),
        ('/internal/v1/ops/telemetry', TOKEN, True),
        ('/internal/v1/ops/metrics', TOKEN, True),
        ('/internal/v1/ops/summary', 'not-authorized', False),
        ('/api/v1/session', TOKEN, False),
        ('/internal/v1/ops/unknown', TOKEN, False),
    ],
)
def test_only_authenticated_exact_private_routes_inherit_bounded_traceparent(path, token, inherits):
    import hashlib

    exporter = InMemorySpanExporter()

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
        exporter=exporter,
        sampling_ratio=1,
    )

    async def inner(scope, receive, send):
        await JSONResponse({'safe': True})(scope, receive, send)

    wrapped = TelemetryMiddleware(
        inner, telemetry, frozenset({path}), private_token_digest=hashlib.sha256(TOKEN.encode()).digest()
    )

    async def run():
        parent_trace_id = 'a' * 32
        scope = {
            'type': 'http',
            'method': 'GET',
            'path': path,
            'headers': [
                (b'authorization', f'Bearer {token}'.encode()),
                (b'traceparent', f'00-{parent_trace_id}-bbbbbbbbbbbbbbbb-01'.encode()),
                (b'baggage', b'secret=private-sentinel'),
                (b'tracestate', b'private-sentinel=value'),
            ],
            'route': type('Route', (), {'path': path})(),
        }

        async def send(message):
            pass

        async def receive():
            return {'type': 'http.request', 'body': b''}

        await wrapped(scope, receive, send)
        assert telemetry.trace_provider.force_flush(1000)
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        if inherits:
            assert spans[0].context.trace_id == int(parent_trace_id, 16)
            assert spans[0].parent.span_id == int('b' * 16, 16)
        else:
            assert spans[0].parent is None
            assert spans[0].context.trace_id != int(parent_trace_id, 16)
        assert not spans[0].context.trace_state
        assert 'private-sentinel' not in str(spans[0].attributes)

    asyncio.run(run())
    telemetry.shutdown()


def test_database_outage_keeps_readiness_metrics_and_unknown_run_window(caplog):
    async def ready():
        return False

    async def failed_window():
        raise RuntimeError('private-database-path-sentinel')

    telemetry = RuntimeTelemetry(
        started_at=datetime.now(UTC),
        synthetic=True,
        revision=None,
        ready=ready,
        active_runs=lambda: 0,
        max_runs=4,
        run_window=failed_window,
    )
    metrics = asyncio.run(telemetry.prometheus()).decode()
    assert 'pequeverso_ready 0.0' in metrics
    assert 'pequeverso_runs_window{outcome="completed"} NaN' in metrics
    assert 'private-database-path-sentinel' not in caplog.text + metrics
    telemetry.shutdown()


def test_actual_otlp_http_export_ignores_proxy_and_contains_safe_protobuf_only(monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    received = []

    class Collector(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            payload = ExportTraceServiceRequest()
            payload.ParseFromString(body)
            received.append(payload)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:1')
    monkeypatch.delenv('NO_PROXY', raising=False)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Collector)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    async def ready():
        return True

    async def window():
        return RunWindow({}, {}, 0, [], [])

    telemetry = RuntimeTelemetry(
        started_at=datetime.now(UTC),
        synthetic=True,
        revision='abcdef0',
        ready=ready,
        active_runs=lambda: 0,
        max_runs=4,
        run_window=window,
        endpoint=f'http://127.0.0.1:{server.server_port}/v1/traces',
        sampling_ratio=1,
    )
    try:
        span = telemetry.begin('GET')
        telemetry.finish(span, 'GET', '/health/live', 200, 0.01)
        assert telemetry.trace_provider.force_flush(2000)
        assert len(received) == 1
        exported = received[0].resource_spans[0]
        assert {a.key for a in exported.resource.attributes} == {'service.name', 'service.version'}
        assert len(exported.scope_spans[0].spans) == 1
        actual = exported.scope_spans[0].spans[0]
        assert actual.name == 'GET /health/live'
        assert {a.key for a in actual.attributes} == {
            'http.request.method',
            'http.route',
            'http.response.status_code',
        }
        state = asyncio.run(telemetry.snapshot())
        assert state.export_successes == 1 and state.last_export_success is True
    finally:
        telemetry.shutdown()
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


def test_exporter_shutdown_drops_queued_batches_without_repeating_timeouts():
    import threading
    import time

    from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

    class SlowBoundedExporter(SpanExporter):
        def __init__(self):
            self.started = threading.Event()
            self.closed = threading.Event()
            self.calls = 0

        def export(self, spans):
            self.calls += 1
            self.started.set()
            self.closed.wait(timeout=1)
            return SpanExportResult.FAILURE

        def shutdown(self):
            self.closed.set()

    async def ready():
        return True

    async def window():
        return RunWindow({}, {}, 0, [], [])

    exporter = SlowBoundedExporter()
    telemetry = RuntimeTelemetry(
        started_at=datetime.now(UTC),
        synthetic=True,
        revision=None,
        ready=ready,
        active_runs=lambda: 0,
        max_runs=4,
        run_window=window,
        exporter=exporter,
        sampling_ratio=1,
    )
    for _ in range(64):
        span = telemetry.begin('GET')
        telemetry.finish(span, 'GET', '/health/live', 200, 0.01)
    assert exporter.started.wait(timeout=2)
    started = time.monotonic()
    telemetry.shutdown()
    assert time.monotonic() - started < 2
    assert exporter.closed.is_set()
    assert telemetry.http_inflight == 0


def test_sdk_cleanup_exception_is_redacted_and_does_not_break_runtime_shutdown(caplog):
    class BrokenCleanup(InMemorySpanExporter):
        def shutdown(self):
            raise RuntimeError('private-shutdown-credential-sentinel')

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
        exporter=BrokenCleanup(),
        sampling_ratio=1,
    )
    telemetry.shutdown()
    assert 'private-shutdown-credential-sentinel' not in caplog.text


def test_actual_export_header_stall_has_overall_deadline_and_runtime_can_stop():
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    received = threading.Event()
    release = threading.Event()

    class StalledCollector(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            received.set()
            release.wait(timeout=2)
            # Send no headers until released: the client's overall await deadline expires.

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), StalledCollector)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

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
        endpoint=f'http://127.0.0.1:{server.server_port}/v1/traces',
        sampling_ratio=1,
        export_timeout=0.2,
    )
    try:
        started = time.monotonic()
        span = telemetry.begin('GET')
        telemetry.finish(span, 'GET', '/health/live', 200, 0.01)
        assert telemetry.trace_provider.force_flush(1500)
        assert received.is_set()
        assert time.monotonic() - started < 1.5
        state = asyncio.run(telemetry.snapshot())
        assert state.export_failures == 1 and state.last_export_success is False
        stopped = time.monotonic()
        telemetry.shutdown()
        assert time.monotonic() - stopped < 1
    finally:
        release.set()
        telemetry.shutdown()
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


@pytest.mark.parametrize('enabled', [False, True])
def test_framework_does_not_use_ambient_telemetry_or_public_parent(tmp_path, monkeypatch, enabled):
    # An ambient provider represents instrumentation installed by another library.
    # It must not capture public requests, even when our own telemetry is enabled.
    ambient_exporter = InMemorySpanExporter()
    ambient = TracerProvider(shutdown_on_exit=False)
    ambient.add_span_processor(SimpleSpanProcessor(ambient_exporter))
    monkeypatch.setattr(trace, 'get_tracer_provider', lambda: ambient)
    own_exporter = InMemorySpanExporter()
    instances = []

    class CapturedTelemetry(RuntimeTelemetry):
        def __init__(self, **kwargs):
            kwargs['exporter'] = own_exporter
            kwargs['sampling_ratio'] = 1
            super().__init__(**kwargs)
            instances.append(self)

    monkeypatch.setattr('app.adapters.observability.RuntimeTelemetry', CapturedTelemetry)
    try:
        with TestClient(create_app(settings(tmp_path, observability_enabled=enabled))) as client:
            response = client.get(
                '/api/v1/availability?private_query=visitor-query-sentinel',
                headers={
                    'traceparent': '00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01',
                    'x-private': 'visitor-header-sentinel',
                },
            )
            assert response.status_code == 200
            assert len(instances) == int(enabled)
            if enabled:
                assert instances[0].trace_provider.force_flush(1000)
                spans = own_exporter.get_finished_spans()
                assert spans and all(span.parent is None for span in spans)
                assert all(span.context.trace_id != int('a' * 32, 16) for span in spans)
                exported = str([(span.name, dict(span.attributes)) for span in spans])
                assert 'visitor-query-sentinel' not in exported
                assert 'visitor-header-sentinel' not in exported
            else:
                assert not own_exporter.get_finished_spans()
        assert ambient.force_flush(1000)
        assert not ambient_exporter.get_finished_spans()
    finally:
        ambient.shutdown()
