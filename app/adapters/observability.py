"""Manual, bounded observability. Never instruments models, SQL, headers or message bodies."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import re
import resource
import threading
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import requests
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
from opentelemetry.trace import Span, SpanKind, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.application.operations import RunWindow
from app.application.telemetry import RuntimeResources, TelemetrySnapshot

log = logging.getLogger(__name__)
PRIVATE_PATHS = frozenset(
    {'/internal/v1/ops/summary', '/internal/v1/ops/telemetry', '/internal/v1/ops/metrics'}
)
TRACEPARENT = re.compile(r'^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$')
METHODS = frozenset({'GET', 'POST', 'DELETE', 'PUT', 'PATCH', 'HEAD', 'OPTIONS'})
BUCKETS = (0.01, 0.05, 0.1, 0.5, 1, 5, 15, 30, 60, 120)


def _integer_file(path: str) -> int | None:
    try:
        value = Path(path).read_text().strip()
        number = int(value)
        return number if number >= 0 else None
    except (OSError, ValueError):
        return None


def resources() -> RuntimeResources:
    try:
        rss = int(Path('/proc/self/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
    except (OSError, ValueError, IndexError):
        rss = None
    try:
        quota, period = Path('/sys/fs/cgroup/cpu.max').read_text().split()
        cpu = int(quota) / int(period) if quota != 'max' and int(period) > 0 else None
    except (OSError, ValueError):
        cpu = None
    return RuntimeResources(
        process_rss_bytes=rss,
        process_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        cgroup_memory_current_bytes=_integer_file('/sys/fs/cgroup/memory.current'),
        cgroup_memory_limit_bytes=_integer_file('/sys/fs/cgroup/memory.max'),
        cgroup_cpu_limit_cores=cpu,
        cgroup_pids_current=_integer_file('/sys/fs/cgroup/pids.current'),
        cgroup_pids_limit=_integer_file('/sys/fs/cgroup/pids.max'),
    )


class DeadlineSession(requests.Session):
    """Supported SDK Session hook with an overall deadline, no response-body reads or proxies.

    Requests' inactivity timeout alone cannot bound a trickling response. The existing
    async HTTP client supplies cancellation under asyncio.timeout inside the SDK worker.
    This does not replace OTLP encoding/export logic or instrument that client's traffic.
    """

    def __init__(self, ceiling: float) -> None:
        super().__init__()
        self.trust_env = False
        self.ceiling = ceiling
        self._closed = False
        self._state_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[requests.Response] | None = None

    def request(self, method: str | bytes, url: str | bytes, *args: Any, **kwargs: Any) -> requests.Response:
        if args:
            raise requests.RequestException('positional collector options unsupported')
        timeout = min(self.ceiling, float(kwargs.get('timeout', self.ceiling)))
        if timeout <= 0 or self._closed:
            raise requests.RequestException('collector request stopped')

        async def send() -> requests.Response:
            with self._state_lock:
                self._loop = asyncio.get_running_loop()
                self._task = asyncio.current_task()
                if self._closed:
                    raise requests.RequestException('collector request stopped')
            try:
                async with (
                    asyncio.timeout(timeout),
                    httpx.AsyncClient(
                        trust_env=False,
                        timeout=timeout,
                        follow_redirects=False,
                        verify=self.verify if self.verify is not None else True,
                    ) as client,
                    client.stream(
                        method.decode() if isinstance(method, bytes) else method,
                        url.decode() if isinstance(url, bytes) else url,
                        headers=kwargs.get('headers'),
                        content=kwargs.get('data'),
                    ) as response,
                ):
                    if 300 <= response.status_code < 400:
                        raise requests.RequestException('collector redirect refused')
                    result = requests.Response()
                    result.status_code = response.status_code
                    result.headers = requests.structures.CaseInsensitiveDict(response.headers)
                    # The SDK consumes status and Retry-After only. Do not retain/read a
                    # collector body or untrusted reason text (including on an error).
                    result.reason = ''
                    return result
            finally:
                with self._state_lock:
                    self._loop = None
                    self._task = None

        try:
            return asyncio.run(send())
        except asyncio.CancelledError:
            raise requests.RequestException('collector request stopped') from None

    def close(self) -> None:
        with self._state_lock:
            self._closed = True
            if self._loop is not None and self._task is not None:
                self._loop.call_soon_threadsafe(self._task.cancel)
        super().close()


class SafeExporter(SpanExporter):
    """Keep content-free export outcomes; failures never change application requests."""

    def __init__(self, delegate: SpanExporter) -> None:
        self.delegate = delegate
        self.successes = 0
        self.failures = 0
        self.last_at: datetime | None = None
        self.last_success: bool | None = None
        self.lock = threading.Lock()
        self.closed = False

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        with self.lock:
            if self.closed:
                return SpanExportResult.FAILURE
        try:
            result = self.delegate.export(spans)
        except Exception:  # noqa: BLE001 -- telemetry is best effort, never log exception text
            result = SpanExportResult.FAILURE
            log.warning('{"operation":"telemetry_export","outcome":"failed"}')
        with self.lock:
            succeeded = result == SpanExportResult.SUCCESS
            self.successes += int(succeeded)
            self.failures += int(not succeeded)
            self.last_at = datetime.now(UTC)
            self.last_success = succeeded
        return result

    def shutdown(self) -> None:
        with self.lock:
            if self.closed:
                return
            self.closed = True
        try:
            self.delegate.shutdown()
        except Exception:  # noqa: BLE001 -- monitoring cleanup cannot break application cleanup
            log.warning('{"operation":"telemetry_shutdown","outcome":"failed"}')

    def state(self) -> tuple[int, int, datetime | None, bool | None]:
        with self.lock:
            return self.successes, self.failures, self.last_at, self.last_success


class RuntimeTelemetry:
    def __init__(
        self,
        *,
        started_at: datetime,
        synthetic: bool,
        revision: str | None,
        ready: Callable[[], Awaitable[bool]],
        active_runs: Callable[[], int],
        max_runs: int,
        run_window: Callable[[], Awaitable[RunWindow]],
        endpoint: str | None = None,
        sampling_ratio: float = 0.1,
        export_timeout: float = 2,
        exporter: SpanExporter | None = None,
    ) -> None:
        self.started_at = started_at
        self.monotonic_start = time.monotonic()
        self.synthetic = synthetic
        self.ready = ready
        self.active_runs = active_runs
        self.max_runs = max_runs
        self.run_window = run_window
        self.sampling_ratio = sampling_ratio
        self.http_requests = 0
        self.http_server_errors = 0
        self.http_inflight = 0
        self.registry = CollectorRegistry()
        self.requests = Counter(
            'pequeverso_http_requests_total',
            'Completed HTTP requests since process start.',
            ['method', 'route', 'status_class'],
            registry=self.registry,
        )
        self.duration = Histogram(
            'pequeverso_http_request_duration_seconds',
            'HTTP duration including the lifetime of streamed responses.',
            ['method', 'route'],
            buckets=BUCKETS,
            registry=self.registry,
        )
        self.gauges = {
            name: Gauge(f'pequeverso_{name}', description, registry=self.registry)
            for name, description in {
                'process_uptime_seconds': 'Current process uptime, not historical availability.',
                'process_rss_bytes': 'Current process RSS in bytes.',
                'process_peak_rss_bytes': 'Process RSS high-water in bytes.',
                'cgroup_memory_current_bytes': 'Current enclosing cgroup memory, scope may be shared.',
                'cgroup_memory_limit_bytes': 'Configured enclosing cgroup limit if known.',
                'cgroup_cpu_limit_cores': 'Configured enclosing cgroup CPU quota if known.',
                'cgroup_pids_current': 'Current enclosing cgroup PID count, scope may be shared.',
                'cgroup_pids_limit': 'Configured enclosing cgroup PID ceiling if known.',
                'ready': 'Point-in-time application readiness, no provider probe.',
                'active_runs': 'Current in-process active runs.',
                'max_concurrent_runs': 'Configured application concurrent run ceiling.',
                'http_inflight': 'Current HTTP requests, including streams.',
                'synthetic': 'One for fixture provider configuration, zero for real provider configuration.',
            }.items()
        }
        self.run_counts = Gauge(
            'pequeverso_runs_window',
            'Recorded runs in trailing24h, not a monotonic counter.',
            ['outcome'],
            registry=self.registry,
        )
        self.exporter: SafeExporter | None = None
        self.trace_provider: TracerProvider | None = None
        if endpoint or exporter:
            if exporter is None:
                session = DeadlineSession(export_timeout)
                exporter = OTLPSpanExporter(
                    endpoint=endpoint,
                    timeout=export_timeout,
                    session=session,
                    headers={},
                    max_request_size=256 * 1024,
                )
            self.exporter = SafeExporter(exporter)
            self.trace_provider = TracerProvider(
                resource=Resource(
                    {'service.name': 'pequeverso-assistant-api', 'service.version': revision or 'unknown'}
                ),
                sampler=TraceIdRatioBased(sampling_ratio),
                shutdown_on_exit=False,
            )
            self.trace_provider.add_span_processor(
                BatchSpanProcessor(
                    self.exporter,
                    max_queue_size=256,
                    max_export_batch_size=32,
                    schedule_delay_millis=5000,
                    export_timeout_millis=5000,
                )
            )
        self.tracer = self.trace_provider.get_tracer('pequeverso.http') if self.trace_provider else None

    async def snapshot(self) -> TelemetrySnapshot:
        ready = await self.ready()
        successes, failures, last_at, last_success = (
            self.exporter.state() if self.exporter else (0, 0, None, None)
        )
        return TelemetrySnapshot(
            generated_at=datetime.now(UTC),
            process_started_at=self.started_at,
            process_uptime_seconds=max(0, time.monotonic() - self.monotonic_start),
            synthetic=self.synthetic,
            ready=ready,
            active_runs=self.active_runs(),
            max_concurrent_runs=self.max_runs,
            resources=resources(),
            http_requests=self.http_requests,
            http_server_errors=self.http_server_errors,
            http_inflight=self.http_inflight,
            traces_enabled=self.tracer is not None,
            trace_sampling_ratio=self.sampling_ratio,
            export_successes=successes,
            export_failures=failures,
            last_export_at=last_at,
            last_export_success=last_success,
        )

    async def prometheus(self) -> bytes:
        snapshot = await self.snapshot()
        values: dict[str, float | int | bool | None] = {
            'process_uptime_seconds': snapshot.process_uptime_seconds,
            'ready': snapshot.ready,
            'active_runs': snapshot.active_runs,
            'max_concurrent_runs': snapshot.max_concurrent_runs,
            'http_inflight': snapshot.http_inflight,
            'synthetic': snapshot.synthetic,
            **{name: getattr(snapshot.resources, name) for name in snapshot.resources.__dataclass_fields__},
        }
        for name, value in values.items():
            self.gauges[name].set(float(value) if value is not None else float('nan'))
        try:
            window = await self.run_window()
        except Exception:  # noqa: BLE001 -- dependency outage must not hide readiness telemetry
            window = None
            log.warning('{"operation":"telemetry_run_window","outcome":"unavailable"}')
        for outcome in ('completed', 'failed', 'cancelled', 'interrupted', 'refused'):
            self.run_counts.labels(outcome).set(window.counts.get(outcome, 0) if window else float('nan'))
        return generate_latest(self.registry)

    def begin(self, method: str, context: Context | None = None) -> Span | None:
        self.http_inflight += 1
        return (
            self.tracer.start_span(
                'HTTP request',
                context=context or Context(),
                kind=SpanKind.SERVER,
                attributes={'http.request.method': method},
                record_exception=False,
                set_status_on_exception=False,
            )
            if self.tracer
            else None
        )

    def finish(self, span: Span | None, method: str, route: str, status: int, duration: float) -> None:
        self.http_inflight -= 1
        self.http_requests += 1
        self.http_server_errors += int(status >= 500)
        self.requests.labels(method, route, f'{status // 100}xx' if status else 'unknown').inc()
        self.duration.labels(method, route).observe(duration)
        if span:
            span.update_name(f'{method} {route}')
            span.set_attribute('http.route', route)
            if status:
                span.set_attribute('http.response.status_code', status)
            if status >= 500:
                span.set_status(StatusCode.ERROR)
            span.end()

    def shutdown(self) -> None:
        if self.trace_provider:
            # Stop the exporter before draining the bounded queue: queued spans are
            # intentionally dropped rather than extending shutdown by many network timeouts.
            if self.exporter:
                self.exporter.shutdown()
            self.trace_provider.shutdown()


class TelemetryMiddleware:
    """Pure ASGI: stream lifetime, optional authenticated private traceparent only; no body."""

    def __init__(
        self,
        app: ASGIApp,
        telemetry: RuntimeTelemetry,
        routes: frozenset[str],
        private_token_digest: bytes | None = None,
    ) -> None:
        self.app = app
        self.telemetry = telemetry
        self.routes = routes
        self.private_token_digest = private_token_digest

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return
        method = scope['method'] if scope['method'] in METHODS else 'OTHER'
        started = time.monotonic()
        context = Context()
        if self.private_token_digest is not None and scope['path'] in PRIVATE_PATHS:
            headers = dict(scope.get('headers', []))
            scheme, _, value = headers.get(b'authorization', b'').partition(b' ')
            incoming = headers.get(b'traceparent', b'').decode('latin-1')
            if (
                scheme.lower() == b'bearer'
                and value
                and len(incoming) == 55
                and hmac.compare_digest(hashlib.sha256(value).digest(), self.private_token_digest)
                and TRACEPARENT.fullmatch(incoming)
            ):
                context = TraceContextTextMapPropagator().extract({'traceparent': incoming})
        span = self.telemetry.begin(method, context)
        status = 0

        async def capture_status(message: Message) -> None:
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status'] if 100 <= message['status'] <= 599 else 500
            await send(message)

        try:
            await self.app(scope, receive, capture_status)
        finally:
            route = getattr(scope.get('route'), 'path', 'unmatched')
            self.telemetry.finish(
                span,
                method,
                route if route in self.routes else 'unmatched',
                status,
                max(0, time.monotonic() - started),
            )
