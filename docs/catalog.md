# Catalog: source, updates and freshness

`catalog/catalog.v1.json` is the assistant's only product and policy knowledge. It is generated
from the storefront's own typed registry and copy (`gonzalomartinperez/pequeverso`, public) at a
pinned commit reachable from `main`. Git provenance and deployment provenance are separate:
reachability alone does not prove that customers currently see that revision.

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

## Current coverage (2026-10-13)

The snapshot is exported from storefront `main` revision
`18b68692867ddd379a3e30130a473dcb7e8a355b`: one core product, nine resources,
23 documents and six links. Every commercial field is identical to the prior
`eb68a041b4515d71a734626fdaee0ef06d8693c3` snapshot; this sync updates source provenance
and verification time only. It does not prove the checkout or the deployed storefront was
verified, and original evaluation artifacts retain their original catalog hashes. Regenerated
contract examples change only the existing price verification timestamp in two SSE examples
and their manifest hashes. Public schemas, event envelopes and v1 revision1.4 are unchanged;
consumers keep their compatible, pinned historical artifact bundles without a forced repin.

**Known coverage gap:** the home now recommends the third-party video course “Guía de
Alimentación para Bebés” through `config/affiliates.ts`. The exporter reads `coreProducts()`
and `offerProducts()` from the separate product registry, not the affiliate registry. This is
missing support for the new registry, not an explicit decision to exclude affiliates. The
course is absent from catalog products, documents and links; its name, content and producer
policies cannot be supplied by generic Hotmart procedure evidence. The current assistant
coverage remains Grafismo Fonético and authorized general platform procedures.

Affiliate support requires a separate reviewed exporter/grounding increment. The PDF product
schema requires page/PDF/resource counts and a positive USD price; do not fabricate those
fields for a video course whose price is not supplied by the public affiliate configuration.
Keep the third-party producer and sponsorship distinct from Pequeverso's own kit, preserve
source-scoped guarantees, and do not claim health outcomes. No affiliate deployment hotlink,
price or additional product has been introduced by this sync. Post-purchase offers remain
excluded by the existing explicit policy.

## Updating

```
git -C ../pequeverso fetch origin main
uv run python scripts/sync_catalog.py --storefront ../pequeverso --revision <full sha on storefront main>
uv run pytest tests/test_catalog.py tests/test_catalog_diff.py && uv run python -m contracts.export
git diff catalog/   # catalog.v1.json + sync-report.json
```

The script **refuses a revision that is not reachable from `origin/main`** of the storefront
(exit 2): content still on `develop` cannot change prices or promises in production. It
validates the export with the runtime schema before writing (exit 3 leaves the snapshot
untouched) and writes `catalog/sync-report.json`: source and previous revision, published ref,
generation time, SHA-256 of the snapshot and of the exporter, counts, and a semantic diff
(products added or **retired**, price changes, resources, documents, links, forbidden terms).
A retired product disappears from answers as soon as the new snapshot is active, because every
reference is resolved against the active catalog. Re-syncing an unchanged `main` commit only
refreshes `generated_at` and restarts the price-freshness window. It verifies the Git source
only; before enabling the assistant, reconcile the snapshot with the actually deployed
storefront revision and its public commercial content. Do not use repeated exports as proof
of production freshness.

The script reads the storefront through `git archive <sha>` into a temporary directory. No
storefront working tree, branch or index is touched. It links the storefront's installed
`node_modules` read-only and runs `tools/catalog/export.ts` with Node, so every value comes
from the storefront modules (`src/products`, `config/commerce.ts`, `content/es/**`). Review the
diff (prices, counts, policy text) in a PR like any code change. Tests assert that the page
counts sum, that the offer never appears, and that every URL is https on an allowlisted host.

## Freshness policy

- **Prices** are quoted only while `now − verified_at ≤ CATALOG_PRICE_MAX_AGE_HOURS` (168 h).
  - For the bundled snapshot, `verified_at` is its `generated_at` (export time). Re-sync at least
    weekly or prices are withheld (honest degradation: the answer points to the product page and
    Hotmart instead of quoting an old amount; cards show no price).
  - For a live `CATALOG_URL` source, `verified_at` is the last successful fetch.
  - After the window: no price in the evidence, `price: null` in cards, and any amount in an
    answer causes replacement. The assistant points to the product page and the Hotmart
    checkout, where Hotmart shows the final total.
- **Operationally:** re-sync after any storefront price or content change. At the latest,
  re-sync weekly to keep prices quotable. A storefront release that changes a price must be
  followed by a catalog PR here.
- **Stock and availability:** the catalog lists a digital product, not live inventory, payment
  approval or per-order access. It cannot confirm those dynamic states. **Promotions:** none
  are present in this snapshot; do not infer future discounts.

The 2026-10-10 audit compared bundled source `ae6d237` with Git main `a0ae53e`: public
commercial source files are unchanged. Hostinger is not connected; no new deployment was
performed or inferred from that comparison.

## Live source (optional, future)

`CATALOG_URL` supports a storefront-published document with the same schema. It is https-only
on an allowlisted host, with no redirects, a 256 KiB cap and refresh every 15 min. A failed or
invalid fetch keeps the last good snapshot (content-addressed in SQLite; last 5 kept). It would
need a storefront change, owned by the storefront team; see
docs/handoffs/storefront-transition.md.

## Content rights

Storefront copy and media are © Pequeverso, all rights reserved (storefront
`LICENSE-CONTENT.md`). They are used here only to answer questions about Pequeverso's own
product; the same text is already public in the storefront repository. This repository is public
and grants no license. The owner has been asked to confirm this use (docs/business-questions.md).


## Optional official platform evidence (2026-10-13)

The catalog remains the only authority for products, prices and merchant policies. Optional
[official platform evidence](official-web-evidence.md) explains general buyer procedures only;
its fetch time cannot refresh catalog price verification or change a merchant guarantee.
