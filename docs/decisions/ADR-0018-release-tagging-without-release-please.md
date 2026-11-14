# ADR-0018: Release tagging without release-please

Status: accepted (2026-11-14). Master-plan task PVA-M1.10, owner decision OD-78, following
engineering-standards ADR 0003.

## Context and problem statement

The plan (`docs/master-plan/ci-cd.md` section 9) proposed release-please on `develop`. That needs a
GitHub App token or a fine-grained PAT, because pull requests opened with `GITHUB_TOKEN` do not
trigger CI and both protected branches require a green `ci-gate`. Granting either is an owner-only
action. OD-78 makes the engineering-standards ADR 0003 pattern the ecosystem default.

## Considered options

1. release-please with a GitHub App (waits for the owner).
2. A release PR on `develop` that bumps the version and curates the CHANGELOG section, then a
   workflow on `main` that tags `vX.Y.Z` and publishes that section.

## Decision outcome

Option 2.

- The version has a single source, `[project].version` in `pyproject.toml`. This differs from the
  engineering-standards `VERSION` file because `uv` and the image already read the project version.
- `CHANGELOG.md` follows Keep a Changelog. Every PR adds entries under `[Unreleased]`. The release PR
  moves them under `## [X.Y.Z] - YYYY-MM-DD` (Added, Changed, Deprecated, Removed, Fixed, Security).
- After the promotion PR (`develop` to `main`, merge commit) lands, `.github/workflows/release.yml`
  creates the tag and the GitHub Release from that section with `GITHUB_TOKEN` (`contents: write` on
  that job only). It does nothing when the release exists. It never re-targets an existing tag:
  `v1.0.0` predates this flow and stays as it is.
- The promotion itself stays owner-gated (M7). Image build, SBOM, provenance and the `vps-ops` pin
  follow the release in later milestones. A tag or release created with `GITHUB_TOKEN` does not
  trigger other workflows, so those jobs must be called from `release.yml` (`workflow_call`) or
  dispatched, not keyed on `push: tags` or `release` events.

### Consequences

- Good: no extra credentials, and every release commit passed `ci-gate`.
- Bad: the CHANGELOG is curated by hand.
- Owner actions: enable immutable releases and the `v*` tag ruleset (engineering-standards
  `rulesets/`). Revisit release-please if the owner provides a GitHub App.

## Confirmation

`tests/test_release.py` requires the `[Unreleased]` section and a dated section for the current
version, unless the version is the pre-flow 1.0.0. It also pins the workflow to `main` with least
privilege. `scripts/release_notes.py` fails on an empty section.
