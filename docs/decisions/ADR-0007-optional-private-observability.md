# ADR-0007: Optional private observability alongside the operations ledger

Status: accepted (2026-10-12); extends ADR-0005

## Context

The owner requests application availability/resource telemetry, integration with OpenTelemetry,
Prometheus/Grafana and an understandable custom backoffice dashboard. Shared infrastructure,
proxy, receivers and deployment remain the responsibility of vps-ops.

## Decision

- Keep the existing private summary revision1.2, SQLite ledger and content-free run metrics.
  Add independently versioned telemetry1.0 JSON and Prometheus text under authenticated private
  routes. Unknown data stays unknown; readiness, scrape reachability, SSE outcomes and provider
  availability are distinct signals. Counters start with the process; no invented uptime percent.
- Default observability off. Register no global tracer provider, automatic SQL/HTTP/provider
  instrumentation or process collectors. Manual attributes and metric labels are bounded and
  contain no message, prompt, identity, request/run/session id, body, URL, credentials or query.
- Inherit bounded W3C traceparent only on exact bearer-authenticated private ops routes; ignore
  public-browser context, baggage and tracestate. Backoffice correlation remains server-side.
- Use application-owned SDK/registry instances, sampled finite queues and explicit transport
  deadlines. Refuse ambient OTEL configuration, redirects, proxy trust and credential-bearing
  endpoints. Collector failures never delay database cleanup; trace delivery is best effort.
- Provide alert/scrape/Grafana examples without deploying any collector or metrics server.
  The custom backoffice consumes private JSON after its own permission check. Existing summary
  rendering continues when the optional telemetry endpoint is off or unavailable.

## Consequences and limits

The API remains one process and one SQLite volume. There is no Neo4j, Redis, vector database
or PostgreSQL added to the API. The backoffice retains its independent identity PostgreSQL.
Ledger estimates and uncertain reservations cannot be replaced by sampled traces or invoices
inferred from counters. Resource readings from a cgroup may include other processes.

Python SDK/exporter1.45.1 has three explicit beta0.66b1 dependencies. It is not an entirely
stable/LTS dependency tree. Prometheus3.13 is the shared LTS target; Grafana has a separate support
policy and no invented LTS label. vps-ops selects compatible receiver images/components.

Fixture tests cover private authorization, exact metrics/JSON, safe span attributes, bounded
export failure and shutdown. Actual local OTLP capture and active-stream container termination
are recorded with exact images; neither proves deployed receiver ingestion, VPS capacity,
production availability or privacy after proxy misconfiguration. See
[the operational contract](../observability/README.md) and [deployment](../deployment-contract.md).
