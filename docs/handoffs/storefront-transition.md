# Storefront transition handoff

**No storefront changes were made.** During discovery the local clone
`~/projects/github/gonzalomartinperez/pequeverso` was switched from a stale local `main` to its default
branch `develop` (`7ae5987`, clean, fast-forward, no edits). No branch, commit, PR or uncommitted
file was created there. The previously planned in-store chat island and the catalog export
script were **never implemented** in the storefront; the export logic now lives here
(`tools/catalog/export.ts`, run against a `git archive` of a pinned storefront commit).

## What the storefront would own later (deferred, for its owner)

- The launcher button and an outer panel that hosts `https://assistant.pequeverso.com/embed` in an
  iframe. Pages proposed by the owner: home, `/grafismo-fonetico/`, `/soporte/`. Never on the
  Hotmart post-purchase offer page, the thank-you page or legal pages.
- A fixed `page` context (`home | product | support`) handed to the embed (as an
  iframe URL parameter or embed message; it is not a credential).
- CSP: add the assistant origin to `frame-src` (edge rules are report-only today).
- Lazy loading: do not load the iframe until the visitor opens the launcher. The store must render
  and sell with the assistant disabled or unreachable.
- Privacy: the owner approved a conditional `/privacidad/` section (docs/security.md, "User
  notice"), flagged for owner or legal review.
- Optional: publish `assistant/catalog.v1.json` at build time so the API can use `CATALOG_URL`
  (live freshness) instead of the pinned snapshot. Schema: `app/adapters/catalog_schema.py`.

## Assumptions the backend makes about the storefront

- `https://pequeverso.com/grafismo-fonetico/#comprar` stays the purchase section (card
  `purchase_url`).
- Media URLs in the snapshot (`/media/...` renditions) stay published. They are content-hashed;
  a storefront media change requires a catalog re-sync.
- The post-purchase offer stays excluded before purchase.
