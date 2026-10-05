# Handoff to the backoffice (`pequeverso-assistant-backoffice`, formerly `pequeverso-assistant-web`)

The public conversation moved into the storefront (native, no iframe). This repository's web
app becomes the private operations backoffice. It consumes **only** the private ops API.

| Item | Value |
|---|---|
| Contract | `GET /internal/v1/ops/summary`, schema `contracts/ops.schema.json`, example `contracts/examples/ops.summary.json` (contract revision 1.1; pin from the merged commit of this repository, never a working tree) |
| Auth | `Authorization: Bearer <OPS_READ_TOKEN>`, server-side only (never `NEXT_PUBLIC_*`, never in the browser) |
| Network | Private Docker network, e.g. `OPS_API_URL=http://pequeverso-assistant-api:8000`. `/internal/*` is never routed by the public proxy |
| Errors | `404` when the API has no token configured; `401 unauthorized` for a missing/wrong token; `5xx`/timeout → show "no disponible" |
| Local | `OPS_READ_TOKEN=<32+ chars> uv run uvicorn app.main:app --port 8000` (fixture: `service.synthetic: true`) |

Rendering rules: unknown values are `null` → "no disponible", never 0; `daily` has only days
with records and `metrics_since` marks the start of history (do not draw gaps as zeros);
`service.synthetic` must be shown prominently; money is USD decimal strings; spend is
confirmed / estimated / pending (definitions in docs/api-contract.md).
