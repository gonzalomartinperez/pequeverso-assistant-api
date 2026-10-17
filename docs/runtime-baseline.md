# Runtime baseline candidate — 2026-10-17 (17:35 UTC cohort)

The owner authorized execution of the shared deployment-readiness plan. This repository owns
its code, tests, image and runtime contract. The private vps-ops inventory owns the shared
baseline/routing/release policy; Coolify remains the sole deployment executor.

| Applicable component | Exact committed lock version |
| --- | --- |
| `fastapi` | `0.143.3` |
| `uvicorn` | `0.54.0` |
| `openai` | `3.33.0` |
| `pydantic` | `2.14.1` |
| `pydantic-settings` | `2.16.0` |
| `opentelemetry-sdk` | `1.45.1` |
| `mypy` | `2.4.0` |
| `ruff` | `0.17.1` |
| `pytest` | `9.1.1` |

The lockfile is authoritative for the complete dependency graph. This dated view does not
assert that these versions remain the newest forever or that an image has been published.
Python 3.15.0 is maintained stable, not named LTS; uv 0.13.1 is stable tooling.
Pequeverso has no Lingua dependency and uses SQLite rather than the portfolio retrieval stack.
The portfolio remains an immutable implementation reference, not evidence that Pequeverso
has passed its own checks. This candidate deliberately uses regular GIL CPython; no global lazy
imports, experimental JIT or free-threaded runtime is enabled.

Python 3.15.0 was [released on 2026-10-09](https://www.python.org/downloads/release/python-3150/).
The earlier unavailable-tag observation in the deployment contract is historical. The official
`3.15.0-slim-trixie` multi-platform manifest is now
`sha256:2da676046630d7bf14c6764ae1143dc7fa0377a53f94bf5a642f0b214aca5bce`;
its Linux amd64 manifest is
`sha256:a83d68dc3d8f1048ff5628bc6f8c9f859938eb5add44ca947b70105b0383e961`.
The uv 0.13.1 manifest is
`sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336`.
Both digests were verified against public registry metadata on 2026-10-17; metadata alone
does not prove installation, ABI behavior or application correctness. The complete locked
Python dependency graph has candidate CP315-compatible wheels on Linux amd64. Frozen install
and runtime tests remain required. Mypy targets 3.15; Ruff keeps the pre-existing conservative
`py313` syntax target to avoid unrelated rewrites.

See [candidate verification](verification/runtime-cohort-2026-10-17.md) for release-note review,
configuration and actual-SDK transport regressions, measured checks and outstanding gates.

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
