# Catalog: source, updates and freshness

`catalog/catalog.v1.json` is the assistant's only product and policy knowledge. It is generated
from the storefront's own typed registry and copy (`gonzalomartinperez/pequeverso`, public) at a
pinned commit of `main`, the branch customers see.

## What it contains (and excludes)

- Purchasable core products with price (USD reference + local-currency note), composition, age
  range, format, usage, method, "for / not for" lists, age guidance, images and the resources
  (main PDF and included bonuses) with page counts.
- Documents: the landing FAQ, guarantee/refund, payment/currency, digital delivery, Argentine
  withdrawal right (summary + link), support routes, support limits, contact, access problems.
- Links: support, purchases & refunds, withdrawal, Hotmart buyer area, Hotmart refund form,
  product page.
- **Excluded:** post-purchase offers (owner decision 2026-09-24: paid extras never appear before
  purchase). Their names become `forbidden_terms`: an answer that mentions them is replaced.
  Also excluded are seller tax id and address, legal-only mailboxes, and anything not
  customer-facing.

## Updating

```
uv run python scripts/sync_catalog.py --storefront ../pequeverso --revision <full sha of storefront main>
uv run pytest tests/test_catalog.py && uv run python -m contracts.export && git diff catalog/
```

The script reads the storefront through `git archive <sha>` into a temporary directory. No
storefront working tree, branch or index is touched. It links the storefront's installed
`node_modules` read-only and runs `tools/catalog/export.ts` with Node, so every value comes
from the storefront modules (`src/products`, `config/commerce.ts`, `content/es/**`). Review the
diff (prices, counts, policy text) in a PR like any code change. Tests assert that the page
counts sum, that the offer never appears, and that every URL is https on an allowlisted host.

## Freshness policy

- **Prices** are quoted only while `now − verified_at ≤ CATALOG_PRICE_MAX_AGE_HOURS` (168 h).
  - For the bundled snapshot, `verified_at` is its `generated_at` (export time).
  - For a live `CATALOG_URL` source, `verified_at` is the last successful fetch.
  - After the window: no price in the evidence, `price: null` in cards, and any amount in an
    answer causes replacement. The assistant points to the product page and the Hotmart
    checkout, where Hotmart shows the final total.
- **Operationally:** re-sync after any storefront price or content change. At the latest,
  re-sync weekly to keep prices quotable. A storefront release that changes a price must be
  followed by a catalog PR here.
- **Stock and availability:** not applicable (digital). **Promotions:** none exist.

## Live source (optional, future)

`CATALOG_URL` supports a storefront-published document with the same schema. It is https-only
on an allowlisted host, with no redirects, a 256 KiB cap and refresh every 15 min. A failed or
invalid fetch keeps the last good snapshot (content-addressed in SQLite; last 5 kept). It would
need a storefront change, owned by the storefront team; see
docs/handoffs/storefront-transition.md.

## Content rights

Storefront copy and media are © Pequeverso, all rights reserved (storefront
`LICENSE-CONTENT.md`). They are used here only to answer questions about Pequeverso's own
product, in the owner's private repository. The owner has been asked to confirm this use.
