---
name: api-review-weekly-dependencies
description: Reviews the single weekly Dependabot PR (all ecosystems: uv, GitHub Actions, Docker images) before the owner merges it into develop. Use when the weekly dependency PR is open, labelled needs-fix, or the deps-weekly-guard reports a problem. Not for merging into main or bypassing checks.
metadata:
  owner: gonzalomartinperez
  last-reviewed: "2026-11-14"
  version: "2.0.0"
---

# Review the weekly dependency PR

1. Confirm it is the one weekly group PR (`weekly-all`, base `develop`). The guard keeps at most one
   open; if two exist, the older is superseded, never reviewed in parallel.
2. Read the lockfile diff (`uv.lock`) and the changelogs between versions for sensitive packages:
   sessions and cookies (starlette), validation (pydantic), streaming and the Responses API
   (openai SDK), TLS and configuration loading. For openai, also review
   `app/adapters/providers/openai_provider.py` against the new SDK types.
3. Check image digest changes in `infra/docker/*` (app, postgres, neo4j) and GitHub Actions pins.
4. Check out the branch and run `uv sync --locked && uv run pytest -n auto && uv run python -m contracts.export --check`.
   A live check still needs the owner's authorization.
5. CI must be green, including the container image gates (Grype, SBOM).
6. The owner merges it into `develop` (OD-20). Agents may push fixes to the same branch only when the
   PR is labelled `needs-fix`; otherwise comment. Never push to `main`.

## Limits

- Never merge into `main`, never auto-approve, never bypass rulesets; majors and frameworks
  always get a human review.
