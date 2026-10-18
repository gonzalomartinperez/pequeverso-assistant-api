---
name: review-dependency-update
description: Review a Dependabot update using the read-only assessment and protected manual merge workflow. Not for merging into main or bypassing checks.
---

# Review a dependency update

1. Read the `Dependabot policy` job summary: it lists every changed package with its semantic
   update type and review reasons. Every update stays manual; classification and labels are not authorization.
2. For each package, read its changelog between the two versions. Focus on sessions and cookies
   (starlette), validation (pydantic), streaming and the Responses API (openai), TLS and
   configuration loading.
3. Check out the PR locally, then run `uv sync --frozen && uv run pytest && uv run python -m contracts.export --check`
   and `scripts/smoke_container.sh`. For openai, also review `app/adapters/providers/openai_provider.py`
   against the new SDK types. A live check still needs the owner's authorization.
4. Merge into `develop` only when CI is green and you understand the change. Otherwise comment,
   and use `@dependabot ignore this version` where appropriate. Never push to `main`.
5. Allowlist changes go in `.github/dependabot-policy.json` with a test in
   `tests/test_dependabot_policy.py`, never as a one-off bypass.

## Limits

- Never merge into `main`, never auto-approve, never bypass rulesets; majors and frameworks
  always get a human review.
