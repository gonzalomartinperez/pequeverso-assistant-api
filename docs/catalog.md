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

## Current coverage (2026-10-18)

The snapshot comes from storefront main `fd2f150fe2e08955b3817c3b18ff14dea920d74e`:
**two products, nine resources, 26 documents and six links**. Grafismo Fonético remains the
priced core PDF kit. Guía de Alimentación para Bebés is a separately purchased, third-party
video course for complementary feeding from 6 to 12 months. Affiliate facts come exclusively
from `config/affiliates.ts` and `content/es/hub.ts`; no environment destination or external
producer page is scraped during export. The only purchase destination exported is the public
same-origin `/alimentacion-bebe/` redirect. Its operational destination is configured separately
by the storefront owner; catalog export does not prove that redirect works.

The affiliate registry publishes no price, PDFs, page counts, duration, certificates or personal
health advice. Price/count fields stay null and resources stay empty, validated strictly. Core
products retain required positive prices, counts and resources. Affiliate relationship text is
preserved in summary for older clients and in new optional card disclosure for revision1.5.

Documents and links carry product_ids. Legacy unscoped documents apply to core products only.
The course's published seven-day guarantee does not inherit the kit's guarantee or Pequeverso
support promises. Retrieval keeps both product records for comparisons, scopes support/policies
to explicit product mentions, and uses the latest assistant's structured product references for
follow-ups. A genuinely ambiguous question is clarified. Conversations are never indexed as
knowledge. Prices remain subject to freshness and null prices cannot borrow the kit price.
Bounded positive-claim recognizers reject explicit patterns such as curing anemia or preventing allergies/choking; this is not complete semantic verification. The prompt adds medical boundaries, and real-model review remains pending;
the assistant may describe course topics, not prescribe personal diets or medical treatment.

The initial affiliate-catalog increment closed the earlier coverage gap without adding a
vector store or graph database; that architecture decision was subsequently superseded by
[the production GraphRAG profile](decisions/ADR-0009-versioned-commercial-graphrag.md).
The October18 catalog refresh changes only the affiliate usage wording to "Primeras comidas
de tu bebé". Prices, policies, resource counts and links are unchanged. This refresh makes no
paid calls or indexing changes; historical evaluation and vector manifests keep their actual
source/hash identities rather than being relabeled as this snapshot.

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

The script reads the committed storefront revision through `git archive <sha>` into a temporary
directory. No storefront working tree, branch or index is touched. It links the storefront's
installed `node_modules` read-only, copies this API repository's `tools/catalog/export.ts` into
the archive, and runs that exporter with Node. Product facts come from the archived storefront
modules (`src/products`, `config/commerce.ts`, `content/es/**`), never uncommitted storefront
copy. The exporter itself is reviewed and versioned in the API; its hash is included in the sync
report. Review the diff (prices, counts, policy text) in a PR like any code change. Tests
assert that the page counts sum, that the offer never appears, and that every URL is https on an allowlisted host.

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
`LICENSE-CONTENT.md`). Core copy is used to answer product questions; affiliate metadata and disclosure use only
the approved public storefront registry, never course videos, private course material or
producer account information; the same text is already public in the storefront repository. This repository is public
and grants no license. The owner has been asked to confirm this use (docs/business-questions.md).


## Optional official platform evidence (2026-10-13)

The catalog remains the only authority for products, prices and merchant policies. Optional
[official platform evidence](official-web-evidence.md) explains general buyer procedures only;
its fetch time cannot refresh catalog price verification or change a merchant guarantee.
