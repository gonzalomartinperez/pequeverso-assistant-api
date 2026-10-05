# Storefront handoff: native assistant (revision 1.1)

The storefront (`gonzalomartinperez/pequeverso`) renders the only public conversation UI,
natively (no iframe), **disabled by default** behind its own build-time flag. It calls this API
cross-origin. This repository does not edit the storefront.

## What the storefront needs from this API

| Need | Contract |
|---|---|
| Origin | Proposed `https://assistant.pequeverso.com` (pending approval/DNS); calls go to `<origin>/api/v1/...` |
| Credentials | `fetch(..., {credentials: 'include'})`; host-only `__Host-pv_assistant` cookie set by the API (Secure, HttpOnly, SameSite=Lax) |
| CORS | `ALLOWED_ORIGINS=["https://pequeverso.com"]` on the API (exact); preflight handled by the API |
| CSRF | `csrf_token` from `POST /session`, in memory, sent as `X-CSRF-Token`; `Idempotency-Key` per attempt |
| Page context | `page`: `home` \| `product` \| `support`; never on the thank-you page, the post-purchase offer or legal pages |
| Language | `locale` from the UI (`es` today); render `message.language` as `lang` |
| Starters | `SessionOut.starters` before the first message |
| Availability | `availability` in `SessionOut` / `GET /availability`; when unavailable show the support link and keep the store fully usable |
| Storefront CSP | add the API origin to `connect-src` when enabling |

## Assumptions the backend makes about the storefront

- `https://pequeverso.com/grafismo-fonetico/#comprar` stays the purchase section (card
  `purchase_url`).
- Media URLs in the snapshot (`/media/...` renditions) stay published; a media change needs a
  catalog re-sync.
- Facts come only from commits on the storefront `main` branch (sync refuses others).
- The post-purchase offer stays excluded before purchase.
- Privacy: the owner-approved `/privacidad/` assistant section must be live before enabling.
