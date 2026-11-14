# Local tasks. `just check` is the single local command and mirrors CI.
# AGENTS.md "Before a PR" spells out the same chain (tests/test_community.py keeps them equal).

set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

# The single local check: lint, format, types, tests, contract drift.
check:
    uv run ruff check . && uv run ruff format --check . && uv run python -m scripts.ruff_ratchet && uv run lint-imports && uv run python -m scripts.complexity_ratchet && uv run vulture && uv run mypy && uv run pytest -n auto && uv run python -m contracts.export --check

# Apply formatting and safe lint fixes.
fmt:
    uv run ruff format . && uv run ruff check --fix .

# Full test suite.
test:
    uv run pytest -n auto

# Unit tests only (no external service).
unit:
    uv run pytest -m unit -n auto

# Standards drift check; ES is the path to an engineering-standards checkout.
drift ES:
    uv run --with pyyaml==6.0.3 python {{ES}}/tools/standards_drift.py check --repo . --standards {{ES}}
