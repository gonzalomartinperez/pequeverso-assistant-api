"""Real TCP HTTP/SSE and OTLP must export registered templates, never visitor paths."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import uvicorn
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from app.bootstrap.container import create_app
from tests.support import JSON_HEADERS, parse_sse
from tests.test_observability import AUTH, settings


def test_real_http_exports_lazy_router_templates_and_private_parents(tmp_path):
    payloads = []

    class Collector(BaseHTTPRequestHandler):
        def do_POST(self):
            request = ExportTraceServiceRequest()
            request.ParseFromString(self.rfile.read(int(self.headers['Content-Length'])))
            payloads.append(request)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    collector = ThreadingHTTPServer(('127.0.0.1', 0), Collector)
    collector_thread = threading.Thread(target=collector.serve_forever)
    collector_thread.start()
    app = create_app(
        settings(
            tmp_path,
            observability_enabled=True,
            telemetry_otlp_endpoint=f'http://127.0.0.1:{collector.server_port}/v1/traces',
            telemetry_trace_sampling_ratio=1,
        )
    )
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=0, log_config=None, access_log=False))
    sock = server.config.bind_socket()
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]})
    thread.start()
    parent = '00-' + 'a' * 32 + '-' + 'b' * 16 + '-01'
    try:
        deadline = time.monotonic() + 15
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        with httpx.Client(
            base_url=f'http://127.0.0.1:{sock.getsockname()[1]}', timeout=10, trust_env=False
        ) as http:
            assert http.get('/health/live').status_code == 200
            assert http.get('/health/ready').status_code == 200
            for path in ('/internal/v1/ops/summary', '/internal/v1/ops/telemetry'):
                assert http.get(path, headers={**AUTH, 'traceparent': parent}).status_code == 200
            assert http.get('/internal/v1/ops/summary', headers={'traceparent': parent}).status_code == 401
            session = http.post('/api/v1/session', headers={**JSON_HEADERS, 'traceparent': parent}, json={})
            assert session.status_code == 201
            headers = {**JSON_HEADERS, 'X-CSRF-Token': session.json()['csrf_token']}
            response = http.post(
                '/api/v1/messages',
                headers={**headers, 'Idempotency-Key': 'route-telemetry-test-001', 'traceparent': parent},
                json={'content': '¿Qué incluye el kit?', 'locale': 'es'},
            )
            assert response.status_code == 200
            events = parse_sse(response.text)
            assert events[-1]['type'] == 'run.completed'
            run_id = events[0]['run_id']
            # The completed run is no longer active, but its matched template
            # must still be classified on this intentional application 404.
            assert http.post(f'/api/v1/runs/{run_id}/cancel', headers=headers).status_code == 404
            assert http.get('/visitor-path-sentinel?secret=query-sentinel').status_code == 404
            metrics = http.get('/internal/v1/ops/metrics', headers=AUTH).text
            for route in (
                '/health/live',
                '/health/ready',
                '/internal/v1/ops/summary',
                '/internal/v1/ops/telemetry',
                '/api/v1/session',
                '/api/v1/messages',
                '/api/v1/runs/{run_id}/cancel',
                'unmatched',
            ):
                assert f'route="{route}"' in metrics
            expected_names = {
                'GET /health/live',
                'GET /health/ready',
                'GET /internal/v1/ops/summary',
                'GET /internal/v1/ops/telemetry',
                'POST /api/v1/session',
                'POST /api/v1/messages',
                'POST /api/v1/runs/{run_id}/cancel',
                'GET unmatched',
            }
            deadline = time.monotonic() + 10
            while True:
                spans = [
                    span
                    for payload in payloads
                    for resource in payload.resource_spans
                    for scope in resource.scope_spans
                    for span in scope.spans
                ]
                if {span.name for span in spans} >= expected_names or time.monotonic() >= deadline:
                    break
                time.sleep(0.01)
            assert {span.name for span in spans} >= expected_names
            for span in spans:
                attributes = {item.key: item.value for item in span.attributes}
                route = attributes['http.route'].string_value
                status = attributes['http.response.status_code'].int_value
                inherits = (
                    route in ('/internal/v1/ops/summary', '/internal/v1/ops/telemetry') and status == 200
                )
                assert bool(span.parent_span_id) is inherits
                if inherits:
                    assert span.parent_span_id.hex() == 'b' * 16
                    assert span.trace_id.hex() == 'a' * 32
                assert set(attributes) == {'http.request.method', 'http.route', 'http.response.status_code'}
            serialized = metrics + json.dumps([str(span) for span in spans])
            for sentinel in (run_id, 'visitor-path-sentinel', 'query-sentinel', AUTH['Authorization']):
                assert sentinel not in serialized
    finally:
        server.should_exit = True
        thread.join(10)
        sock.close()
        collector.shutdown()
        collector.server_close()
        collector_thread.join(5)
    assert not thread.is_alive() and not collector_thread.is_alive()
