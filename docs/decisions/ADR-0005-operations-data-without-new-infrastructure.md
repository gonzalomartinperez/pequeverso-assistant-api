# ADR-0005: Operations data from the ledger and run metrics, no metrics stack

Status: accepted (2026-10-05)

## Context

The backoffice needs health, catalog freshness, run outcomes, latency, tokens and spend. Options
considered: Prometheus/OpenTelemetry exporters with Grafana, an external tracing service
(LangSmith), or aggregates computed from data the API already owns.

## Decision

- Keep structured JSON logs (no content) and add one content-free `run_metrics` table
  (migration 002) next to the spend ledger, which gains explicit states
  (`pending`/`settled`/`unreported`) and reasoning-token counts.
- Serve aggregates through a private, token-protected `GET /internal/v1/ops/summary` that only
  the backoffice server calls over the private network.
- No Prometheus endpoint, OpenTelemetry collector, Grafana, LangSmith, Redis or PostgreSQL in the
  API now. Counters would not replace the ledger for spend, a collector failure must never block
  an answer, and the VPS monitoring stack belongs to vps-ops. An exporter can be added later
  against the same tables if vps-ops asks for scrape-based alerts (contract in the deployment
  handoff).

## Consequences

- The API stays one process with one SQLite file; metrics share its backup.
- Metrics writes are best effort and never fail a visitor's answer.
- History starts at deployment of migration 002 (`metrics_since`); the backoffice must not
  invent earlier data.
