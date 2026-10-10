---
name: update-catalog
description: Re-sync the assistant catalog from a pinned Pequeverso storefront commit and review the fact changes. Not for unpublished storefront commits or hand edits.
---

# Update the catalog

1. Find the storefront's current `main` sha without touching its working tree:
   `git -C ../pequeverso fetch origin main && git -C ../pequeverso rev-parse origin/main` (or `gh api`).
2. `uv run python scripts/sync_catalog.py --storefront ../pequeverso --revision <sha>`
   (reads a `git archive`; needs the storefront's `node_modules` installed).
3. Review `git diff catalog/catalog.v1.json`: prices, page counts, resource titles, policy text and
   links. A price change is a business fact; mention it in the PR title.
4. Run `uv run pytest tests/test_catalog.py tests/test_evaluations.py` and
   `uv run python -m contracts.export` (examples embed catalog data), then commit both.
5. Never hand-edit the JSON, add facts that are not in the storefront, or include post-purchase
   offers.

## Limits

- Only commits reachable from the storefront's `origin/main` (the sync refuses others); no hand
  edits, no facts outside the storefront, no post-purchase offers.
- Evidence: the `catalog/sync-report.json` diff reviewed in the PR.
