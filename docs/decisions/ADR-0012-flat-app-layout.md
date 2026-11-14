# ADR-0012: Keep the flat `app/` package layout (no `src/`)

Status: accepted (2026-11-14). Master-plan task PVA-M1.11, master-plan decision PVA-D2 (planned 2026-11-09).

## Context and problem statement

The Python packaging guide recommends a `src/` layout so that tests cannot import the working
tree by accident. This repository is a deployable service, not a published library: `[tool.uv]`
sets `package = false`, nothing is built as a wheel, and the container starts
`uvicorn app.main:app` from `infra/docker/app/Dockerfile`. 162 of the 226 tracked Python files import
`app.*` (95 files live under `app/`), and the same path appears in the image command and in the
deployment contract that `vps-ops` consumes.

## Considered options

1. Keep the flat `app/` package at the repository root.
2. Move to `src/app/` and adjust imports, tooling, the Dockerfile and the deployment contract.

## Decision outcome

Option 1. The benefit of `src/` (testing the installed artifact instead of the checkout) does not
apply because no artifact other than the container image exists, and the image is already tested
as built (`scripts/smoke_container.sh`, CI `container` job). Moving would churn every import,
the blame history and a cross-repository contract for no risk reduction.

### Consequences

- Good: no import churn; the `app.main:app` entry point and the `vps-ops` contract stay stable.
- Good: layer rules keep their current module names (`tests/test_architecture.py`).
- Bad: tests import from the working tree; accepted because the image smoke test covers the
  shipped artifact.
- Revisit only if the code is ever published as a package.

## Confirmation

- `pyproject.toml` keeps `[tool.uv] package = false`, and the image command stays
  `app.main:app`: the CI `container` job builds the image and `scripts/smoke_container.sh`
  starts it and exercises the API, so a moved package fails the build or the smoke test.
- The architecture guard (`tests/test_architecture.py`) runs on every PR and assumes the flat
  `app/` package.
