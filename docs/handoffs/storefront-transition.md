# Storefront handoff: native assistant (revision 1.4)

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
| Navigation hints (1.3) | Optional nested `context: {opened_path, current_path, presentation}`; exact public route allowlist in docs/api-contract.md. Capture initial open separately from current pathname. UI uses compact/expanded; API also accepts page. No query/fragment/referrer/theme/identifying data, no offer/thank-you path; omit on ineligible routes. Context is untrusted data and does not extend widget eligibility. |
| Native language (1.4) | Always open with `locale: "es"` and send `response_language: "es"` on every message; no assistant language selector. Render each saved `message.language` as `lang`; do not rewrite legacy English history. Explicit requests for another reply language get a Spanish-only local notice without provider calls. |
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

## Pinning revision1.4

After the producer PR merges with required checks, pin its exact merged commit and regenerate
consumer types from `contracts/openapi.json`. Require backend revision at least1.4 for the
native Spanish policy; a1.3 backend rejects the new field. Existing clients may omit `context`
and `response_language`; responses
and SSE are compatible and the private ops schema remains1.2-compatible. No backoffice pin
update is required solely for these public request hints. Preserve local draft/history and old
English messages. The native response policy selects Spanish regardless of input language,
locale hints or previous English answers. Absence/null retains the legacy ES/EN precedence,
bilingual unsupported notice and exact idempotency digest; do not claim that every legacy v1
client is now Spanish-only. Including the policy in a reused legacy key conflicts rather than
replaying an English answer. Language metadata does not prove actual generated prose language:
inspect real replies and provisional streams before activation. Neither this handoff nor its
new fields enable the storefront build flag.
