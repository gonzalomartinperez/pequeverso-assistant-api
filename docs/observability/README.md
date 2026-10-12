# Optional private application observability

Application-owned artifacts only. vps-ops owns collectors, Prometheus, Grafana, private networks,
proxy, credentials and deployment. Nothing here publishes an image or activates the storefront.

Set `OBSERVABILITY_ENABLED=true` explicitly to enable authenticated
`GET /internal/v1/ops/telemetry` and `GET /internal/v1/ops/metrics`, both using the existing
`OPS_READ_TOKEN`. Without observability or the token the endpoints are absent (404).
Never expose `/internal/*` through the public proxy. Metrics are `no-store`; no bearer token
belongs in a query string or dashboard URL. Existing `/summary` and its schema are unchanged.

The independent private JSON contract is `contracts/ops.telemetry.schema.json`, example
`contracts/examples/ops.telemetry.json`, version1. It reports actual measurement time, current
process lifetime, in-process active runs and configured concurrency, real HTTP counters since
process start, process RSS/high-water and enclosing-cgroup counters/ceilings. Unknown resource
values are null. The cgroup may cover other processes: cgroup memory is not process RSS or an
exclusive reservation. `synthetic` means the provider configuration is a fixture; HTTP/resource
measurements remain actual. Readiness is a point-in-time local database/catalog check, not an
availability percentage, paid model probe, provider SLA or production capacity certification.
Provider observation is explicitly unknown/not_probed. HTTP5xx errors do not include SSE run
failures delivered within HTTP200: existing summary run outcomes and metrics cover those.

For traces additionally set `TELEMETRY_OTLP_ENDPOINT=http://collector:4318/v1/traces` (example
private service; vps-ops approves the actual endpoint), `TELEMETRY_TRACE_SAMPLING_RATIO=0.1`
and `TELEMETRY_EXPORT_TIMEOUT_SECONDS=2`. HTTPS is supported; plaintext HTTP is restricted to
single-label private service names or loopback. Credential-bearing URLs, queries and fragments
are refused. Nonempty ambient `OTEL_*` variables are rejected when tracing is configured to
prevent SDK environment headers, certificates or resource attributes from adding private data.
No global SDK provider or auto-instrumentation is registered. The SDK and exporter are loaded
only when observability is enabled; an absent endpoint starts no exporter/network traffic.

Manual HTTP spans contain only a normalized method, allowlisted route template and observed
status. No raw URL/path/query, body, prompt/answer, SQL, provider payload, customer/session/run
id, cookie, IP, credential or request id is exported. Incoming browser trace context is ignored.
A bounded W3C00 traceparent can be inherited only on three exact private ops routes after the
existing bearer is independently validated in constant time. No baggage or tracestate is
accepted; production cross-service correlation requires the actual backoffice/collector smoke.

Each app owns its SDK/Prometheus registry. Queues are256 spans and batches32, with a256KiB
serialized export ceiling, a2s default network timeout (maximum5s), and explicit sampling.
Exporter errors retain only content-free batch outcome/time counters. Telemetry is best effort,
not durable: shutdown closes the exporter before draining and drops queued spans rather than
repeating network timeouts. No dropped trace is proof that an application run was lost.

Metrics start with `pequeverso_`: `http_requests_total{method,route,status_class}`,
`http_request_duration_seconds{method,route}`, `process_uptime_seconds`, `process_rss_bytes`,
`process_peak_rss_bytes`, `cgroup_memory_current_bytes`, `cgroup_memory_limit_bytes`,
`cgroup_cpu_limit_cores`, `cgroup_pids_current`, `cgroup_pids_limit`, `ready`, `active_runs`,
`max_concurrent_runs`, `http_inflight`, `synthetic`, and `runs_window{outcome}`. The run window
is a trailing24h **gauge of recorded outcomes**, not a monotonic counter or complete historical
coverage; use legacy `metrics_since` to understand coverage. Unknown limits/failed run-window
queries export NaN rather than fabricate zero. The registry excludes automatic GC/process/file
collectors. Metric labels never contain ids or user-supplied paths. Separate Prometheus scrape
`up` from readiness, assistant availability and model availability.

References: [manual Python instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/),
[OTLP exporters](https://opentelemetry.io/docs/languages/python/exporters/),
[Prometheus registries](https://prometheus.github.io/client_python/registry/).
