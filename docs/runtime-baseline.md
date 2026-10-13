# Runtime baseline acceptance — 2026-10-13

The owner authorized execution of the shared deployment-readiness plan. This repository owns
its code, tests, image and runtime contract. The private vps-ops inventory owns the shared
baseline/routing/release policy; Coolify remains the sole deployment executor.

| Applicable component | Exact committed lock version |
| --- | --- |
| `fastapi` | `0.143.0` |
| `uvicorn` | `0.54.0` |
| `openai` | `3.29.0` |
| `pydantic` | `2.14.1` |
| `pydantic-settings` | `2.15.0` |
| `opentelemetry-sdk` | `1.45.1` |
| `mypy` | `2.4.0` |
| `ruff` | `0.17.0` |
| `pytest` | `9.1.1` |

The lockfile is authoritative for the complete dependency graph. This dated view does not
assert that these versions remain the newest forever or that an image has been published.
Python3.14.8 is maintained stable, not named LTS; uv0.13.0 is stable tooling. Both APIs share these runtimes and the shared packages above. Portfolio alone needs Lingua2.2.0 (no CP315 wheel), LangGraph/LangChain1.x LTS, pgvector and Neo4j. Pequeverso uses SQLite, not that retrieval stack.

## Image and operations boundaries

Build dependencies are isolated from the runtime. Frozen installs and dependency-cache mounts
reduce repeated downloads; cache content is not copied into the runtime. Dockerfile frontend
and image bases are digest-pinned. Private registry visibility and immutable release manifests
remain prerequisites for publication and deployment; local image identifiers are not registry
provenance. Images are built in application verification, never rebuilt on the VPS.

The HTTP image uses UID65532, a read-only root with its declared writable paths and an exec-form Python probe. No new provider calls, accounts, network service or model-budget setting is introduced. OpenTelemetry stays opt-in; FastAPI0.143 changes automatic exporter setup to opt-in. This matches the explicit exporter policy rather than enabling ambient hooks.

Databases and writable data stay isolated by project. Secret values are excluded from Git,
images, source build arguments and diagnostics. Runtime credentials are delivered by Coolify;
recovery credentials remain independently available. Existing public websites stay on Business
and their assistant activation remains deferred. No deployment trigger is enabled.

## Verification and remaining gates

Frozen installation, formatting/linting, typing, unit/contract checks and fixture-mode verification were run locally. No paid provider call or real key was used. Exact-image and real-service/restore evidence must accompany the release; migration rollback is separately reviewed.

See [deployment contract](deployment-contract.md) for ports, health, secrets, data and shutdown.
The shared baseline does not promise zero downtime, production capacity or an advisory-free
image. Current unfixed OS findings remain visible; no package is removed or scanner weakened
merely to change a vulnerability count.
