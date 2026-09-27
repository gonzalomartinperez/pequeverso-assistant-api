# Handoff to pequeverso-assistant-web

| Item | Value |
|---|---|
| Contract | v1, `schema_version: "1"`, introduced in `0750524f4682109b4ad901102c858bd6ca5d9bce` (PR #1), unchanged since |
| Artifacts | `contracts/openapi.json`, `contracts/sse.schema.json`, `contracts/examples/*.sse|*.json`, hashes in `contracts/manifest.json` (sha256 of the manifest at that commit starts `d163b6d775a9b8c8`) |
| Normative doc | `docs/api-contract.md` at the same commit |
| Local API | `uv sync --frozen && uv run uvicorn app.main:app --port 8000` (fixture answers, bundled catalog). Allowed dev origins: `http://localhost:3000`, `http://127.0.0.1:3000` (`ALLOWED_ORIGINS` to change) |
| Slow streams for UI work | `FIXTURE_CHUNK_DELAY_MS=120` (delta pacing), so stop and cancel can be exercised |
| Web revision verified together | none yet (the web repository held only its bootstrap commit `ce86f6d` on 2026-09-27) |

## Checklist for the web implementation

1. Call relative `/api/v1/...`. In dev, proxy `/api` to `:8000` with the prefix **preserved**, or
   list the dev origin in `ALLOWED_ORIGINS` and call the API cross-origin with credentials.
2. `POST /api/v1/session` on load (and after `401 session_expired`). Keep `csrf_token` in memory;
   use `availability` and `limits.max_message_chars`.
3. Send questions with `X-CSRF-Token` and a new `Idempotency-Key` per attempt. Parse SSE
   yourself from `fetch` (POST), since `EventSource` cannot POST. Ignore `:` comment lines.
4. Render `message.delta` as a provisional draft, and **replace** it with
   `message.completed.message.content`. Render content as text (bold and `- ` lists only);
   never as HTML, never auto-linkify.
5. Product cards only from `products[]`: image, name, `price.display` + `price.note` when `price`
   is not null, and "Ver el kit" (`url`) / "Comprar" (`purchase_url`), opened in a new tab.
   Resources from `resources[]`. Links and sources from `links[]` and `sources[]`.
   Suggestions from `follow_ups[]` (tapping one sends it as a question).
6. Stop: abort the fetch **and** `POST /api/v1/runs/{X-Run-ID}/cancel`. A drop before a terminal
   event is "interrupted": offer a retry with a new key.
7. Map error codes and `run.failed.code` to Spanish copy; `retryable` decides whether to show a
   retry. For `budget_exhausted`, `assistant_disabled` and `catalog_unavailable`, show the store
   support link (`https://pequeverso.com/soporte/`).
8. Notices: `contact_data_redacted` → "Quitamos datos de contacto de tu mensaje";
   `payment_data_refused` → already explained in the answer text; `answer_replaced` → no extra
   UI needed.
9. "Borrar conversación" → `DELETE /api/v1/session`, then open a new session.
10. Embed: keep the iframe mounted while minimized. No credentials or tokens in `postMessage` or
    URLs. Use `frame-ancestors https://pequeverso.com` on `/embed`.

Contract questions or change requests go to this repository as an issue or PR. The API keeps
v1 backward compatible (additive only).
