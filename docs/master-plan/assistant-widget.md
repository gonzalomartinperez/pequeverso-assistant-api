# Assistant widget: shared interaction standard with per-site identity

Status: design specification (proposal) for M5 (build) and M2 (test scaffolding). Scope: `portfolio` (EN/ES, dark and light, Instrument blue) and `pequeverso` (Spanish only, single light theme, warm navy and coral, conversion first). Date: 2026-11-09.

Evidence: existing assistant clients, docs and contracts on `origin/develop` of both repos, both `design-playbook.md`, `cro.md`, `hero-particles.md`, research 13 and 06. Patterns attributed to Intercom Fin, Vercel v0, Linear, Stripe, Perplexity and ChatGPT come from the author's expertise and were **not verified live** (web search not used). Numbers marked "proposal" must be validated by the test named beside them; none is a measurement.

## 0. Principles and decisions

1. **One standard, two skins.** Geometry, states, timings, accessibility, streaming rules, events and tests are shared; tokens, launcher form, copy and product cards are per site.
2. **Quiet by default.** Never opens itself, never steals focus, never calls the network before intent (section 9).
3. **Honest AI.** Always disclosed. "Thinking" appears only while a real request has no text; stages appear only if the API emits them (portfolio `run.status`).
4. **Server-validated facts only.** Prices, guarantees, links and sources render only from validated fields of `message.completed`. Deltas are provisional and replaced by the final message (existing contract rule). Prose is never parsed into a price.
5. **Never in the way of the money action.** Pequeverso yields to the buy bar and offer card; portfolio to the recruiter chip and contact CTA.

Departures from current code (need owner or ADR approval):

| # | Decision | Current | Reason |
|---|---|---|---|
| W-1 | Portfolio 56/52 px circle; pequeverso 52 px pill "Pregúntanos" | 60 px icon; 44 px star | Playbook section 8 specifies the pill; 44 px is a floor |
| W-2 | One panel size, 400 x up to 640 | 440x700; 408x560 | Less to test; about 60 characters per line |
| W-3 | Visible "IA" disclosure in the header | pq: accessible description only | `cro.md` section 7 requires it |
| W-4 | Docked = non-modal region; expanded, portrait tablet, phone = modal | same split | Keep (5.1) |
| W-5 | Analytics optional, consent-aware, closed schema | none | Section 10; gated by PF-MV-2 and PV-D4 |

## 1. Launcher

### 1.1 Form and geometry

| Property | Portfolio | Pequeverso |
|---|---|---|
| Form | Circle, icon only; label chip ("Ask" / "Preguntar") slides left on nudge, hover (fine pointer) and focus | Pill: icon + "Pregúntanos"; collapses to a 48 px circle under 360 px width or in landscape phones |
| Size | 56 px desktop; 52 px at max-width 767 px | 52 px high, about 148 px wide |
| Offset | `right/bottom: max(20px, env(safe-area-inset-*))`; 16 px on phones | same; with the buy bar visible: `bottom = var(--sticky-bar-h) + 12px + env(safe-area-inset-bottom)` |
| Icon | Sparkles outline 24 px, 1.75 px stroke (existing) | Gold star with speech tail on navy (existing star plus tail) |
| z-index | 35 (above header 20 and drawer 30, below dialog 40) | 40 (order from playbook: launcher < bar 45 < consent 50 < scrim 55 < panel 60) |

The launcher is a real `<button type="button" aria-haspopup="dialog" aria-expanded aria-controls>` in the **initial server HTML** (about 400 bytes plus inline SVG; no JS needed to paint). Without JS it degrades to a link (`/soporte/` on pequeverso, `mailto:` on portfolio), never a dead button.

Accessible names contain the visible label (WCAG 2.5.3): "Open assistant chat" / "Abrir chat del asistente" (pf); "Pregúntanos, abrir el asistente automático de Pequeverso" (pq). When open: "Minimizar asistente".

### 1.2 States

| State | Visual and behaviour |
|---|---|
| idle | Raised surface, 1 px accent border, wash halo; static |
| hover (fine pointer only) | 2 px rise, halo scales (pseudo-element transform, never animated box-shadow); label chip after 150 ms; starts prefetch |
| focus-visible | Site focus ring, never clipped or covered; chip shows at once; starts prefetch |
| pressed | `scale(0.96)`, 100 ms |
| nudge | Label chip for 6 s, once per session at most, after the gate in 1.3; visual only, not announced |
| unread | 10 px dot (accent / coral-700) with 2 px ground-colour ring; accessible name gains ", new answer"; set when an answer completes while minimized, cleared on open |
| loading | After a click, if the chunk is not ready in 100 ms: ring spinner, `aria-busy="true"`; after 3 s a tooltip "Sigue cargando..."; pressing again retries |
| disabled / unavailable | `aria-disabled="true"` (stays focusable), 55% opacity, dashed border; activation opens a small popover with the support link. Pequeverso while not activated: **nothing rendered** (no DOM, layout or request, rule R5) |

### 1.3 Entrance and timing

The intro runs after `requestIdleCallback` (timeout 4 s), at least 3 s after navigation start and **after the LCP entry is observed** (fallback timer 5 s). 320 ms, `--ease-out`, opacity and a 8 px translate only. Reduced motion: appears at once, no motion. `position: fixed`, so zero layout shift.

### 1.4 Collision rules (first match wins) and stacking

1. **Pequeverso buy bar.** The bar publishes `--sticky-bar-h` on `<html>` (ResizeObserver; 0 when hidden); the launcher moves with the same 220 ms transform so they travel as one. Never intersects the bar's CTA (bounding-box test at 320, 360, 390, 430).
2. **Offer card or final offer in view** (pequeverso): launcher fades out and becomes `inert` (IntersectionObserver, 120 ms). The visitor never chooses between the assistant and "Obtener el kit".
3. **Consent banner.** Launcher hidden on phones while it shows, raised above it on desktop; the banner keeps focus-order priority; the panel may open over it.
4. **Portfolio stack.** One bottom-right column: launcher, then back-to-top 12 px above; the recruiter chip is bottom-left and collapses to an icon under 400 px.
5. **Hero canvas.** Behind everything; launcher not yet visible in the first 3 s; `holdPageMotion` freezes the stage when a modal panel opens.
6. **Primary CTA guard.** Invariant: the launcher rect never intersects `[data-primary-cta]` at any 25% scroll step; on a hit it hides while that CTA is in view.
7. **Landscape phone** (under 500 px high): 44 px circle at 66% height.

Stacking: hero 0 to 10; header 20; launcher 35 (pq 40); scrim 39 (pq 55); panel 41 (pq 60); toast 50; tooltip 60. A native site `<dialog>` wins; the panel minimizes when one opens.

## 2. Panel geometry and viewport behaviour

| Viewport | Presentation | Size |
|---|---|---|
| >= 1024 | Docked, non-modal, anchored to the launcher corner | `width: 400px`; `height: min(640px, calc(var(--vvh, 100dvh) - 48px))`, `min-height: min(420px, 100dvh - 24px)`; 20 px from edges (24 px at >= 1536) |
| 768 to 1023 | Landscape: docked as above (`min(400px, 100vw - 32px)`). Portrait: **modal bottom sheet**, 560 px centered, 80dvh, top radius 24 px | |
| < 768 | Full-screen modal sheet | `position: fixed; inset: 0; height: var(--vvh, 100dvh)`; safe-area padding on all sides |
| Landscape phone (< 500 px high) | Full sheet, one-row 48 px header, starters hidden | Composer always visible |
| Foldable spanning | Confined to one segment (`env(viewport-segment-*)`, `horizontal-viewport-segments: 2`) | Never straddles the fold (untested on hardware) |

Motion: docked panel scales from `bottom right` (`scale(0.96) translateY(8px)` to identity plus opacity, 220 ms, close 160 ms); phone sheet slides up 280 ms. Never animate height or blur. Reduced motion: 120 ms opacity.

**Keyboard and viewport.** `--vvh` and `--vv-top` come from one rAF-throttled `visualViewport` `resize`/`scroll` listener; the sheet uses `height: var(--vvh)` and `translateY(var(--vv-top))` so the composer sits above the keyboard on iOS Safari (where `dvh` does not shrink with the keyboard). Android Chromium uses `interactive-widget=resizes-content`; the listener is idempotent. A transcript at the bottom stays there when the keyboard opens.

**Scroll lock** (modal only): `html { overflow: hidden; scrollbar-gutter: stable }`, `overscroll-behavior: contain` on the transcript, page `inert` (existing), position restored on close.

**Zoom.** 200% text and pinch zoom follow the visual viewport; header and composer are `flex: none`, transcript `flex: 1; min-height: 0; overflow-y: auto`, no fixed heights.

## 3. Panel content

### 3.1 Header (56 px; 64 px on phone sheet)

- **Identity**: 32 px mark, title 15 px 600 (portfolio "Rampy assistant" / "Asistente de Rampy"; pequeverso "Asistente de Pequeverso").
- **AI disclosure**: visible chip "IA" (EN "AI") plus 12 px muted "Respuestas automáticas, puede equivocarse"; wraps to two lines at 320 px, never hidden. The full sentence is also the first, non-streamed assistant message labelled "Aviso" and the panel's `aria-describedby`. Pequeverso text per playbook section 10.
- **Status**: 6 px dot plus text ("En línea", "Conectando", "Sin conexión", "No disponible"); colour never alone; opacity-only pulse (playbook "Live dot": truthful state only), off under reduced motion.
- **Controls** (44 px hit area, 18 px icons): New conversation (inline confirm, existing), Minimize, and on desktop Expand. Close equals Minimize: closing never destroys the conversation.

### 3.2 Messages

- **User**: right-aligned bubble, `max-width: 85%`, radius 18 px with a 6 px tail corner, accent/navy fill with white or cream text.
- **Assistant**: no bubble (reads like a page, as in ChatGPT and Perplexity; unverified), 28 px mark on the first message of a run. Line length 62 ch; expanded mode caps at 68 ch.
- Rich text: only **bold** and "- " lists as text nodes (contract rule); no HTML, no auto-links; links only from validated `links` and `sources`.
- Timestamps: none per message; a centred 12 px separator ("Hoy 14:32") after a 30-minute gap; `<time datetime>` on hover/focus.

### 3.3 Type scale (rem-based, follows zoom)

Title 15/20 600; body 15/24 (16/25 on phones) 400; sources and notices 13/18 500; meta and chips 12/16 600 with +0.02em; mono for code paths (portfolio). Portfolio uses Inter Tight; pequeverso Fraunces for title and price (22/26, tabular lining figures if the subset exposes them) and Nunito Sans for text.

### 3.4 Streaming UX (mapped to real events)

1. **Send**: user bubble appears instantly and scrolls into view; send swaps to Stop in the same frame; composer clears and keeps focus (not forced when the visitor dismissed the iOS keyboard).
2. **Waiting** (no text): after 150 ms an assistant row shows "Pensando…" / "Thinking…" with three dots whose opacity staggers (decorative, `aria-hidden`, still under reduced motion). On portfolio `run.status: evidence_found` the line becomes "Revisando fuentes…" / "Checking sources…". Pequeverso never shows stages.
3. **Time to first token**: at 8 s "Está tardando más de lo normal" with Stop; at 25 s an explicit "Reintentar". Never automatic; idempotency rules of `application/assistant.ts` unchanged.
4. **Token rendering**: deltas buffered and flushed at most once per animation frame into one text node via a ref (`appendData`), not React state per token; container has `contain: content`. Draft labelled "en curso" until `message.completed` replaces it with authoritative text (a swap; earlier messages never reflow).
5. **Caret**: 2 px accent caret at the draft end, 1 Hz opacity blink; static under reduced motion; removed on completion.
6. **Stop**: 44 px icon button "Detener respuesta"; the partial draft stays, labelled "Detenida". Stop never deletes text.
7. **Completion**: sources, notices and product blocks mount after `message.completed` with a 160 ms opacity fade, appended below the reader's anchor so they cannot move text being read.
8. **Scroll following**: follow within 48 px of the bottom; upward intent stops following without moving the reader; a 44 px "Ir a la respuesta nueva" pill sits at the transcript bottom, outside the reading column (the existing 68 px gutter regression).

### 3.5 Sources and product cards

- **Sources** (portfolio): collapsible "Sources (n)"; chip = type icon + label; code sources show `path:L12-30` in mono; opens in a new tab with `rel="noopener noreferrer"` on click only. Pequeverso: "Fuentes", keeping the "Hotmart · procedimiento general" suffix (never a product guarantee). A citation absent from the validated list never renders.
- **Pequeverso product card**: 72 px thumbnail (validated `image`, its `alt`, fixed `width`/`height`), name, `age_range` chip, summary clamped to 3 lines with an expand control (no script truncation), price block, actions: quiet "Ver el kit" (to `url`, same-tab) and, only when `purchase_url` exists and only on the first product of an answer, coral "Obtener el kit" through the shared `CheckoutLink` with `sck=assistant` (new allowed position, at most 30 characters).
  - **Price rules**: a price block renders only when `price` is non-null in the validated payload, with its date label ("Precio al {date}", date from the field). `price: null` shows "Consulta el precio en la página" with no number or currency. The client never computes, rounds, converts or formats a price from prose. Currency note comes from the same config as the page. Affiliate cards keep commission disclosure and the lookup text.
  - **CTA rules**: at most one coral button per answer; none inside refusals, `price-unverified`, `payment-data-refused`, language-unsupported or failed states. Links pass `domain/links.ts`.

### 3.6 Empty state and starters

- Title "¿En qué te puedo ayudar?" (pq) / "Ask about my work" / "Pregunta sobre mi trabajo" (pf), one sentence on scope and limits, 3 to 4 starters. Pequeverso starters come from real objections (age fit, contents, format and delivery, refund; `content/es/assistant.ts`); portfolio from recruiter questions ("What did you ship in production?", "How does the RAG assistant work?", "How can I contact you?" plus ES).
- Chips: natural width, 36 px (fine) or 44 px (coarse) high; the request carries the full original question (existing allowlist rule).
- After the first answer, API `follow_ups` replace starters as a scroll-snap row of buttons (edge fade only, no scrollbar).

### 3.7 Composer

- Autosize `<textarea rows="1">`, 1 to 6 lines (max 144 px, then scroll), 16 px on phones, radius 20 px, `line-control` border (3:1), placeholder at 4.5:1.
- **Enter** sends, **Shift+Enter** newline; never sends during IME composition. On coarse pointers Enter inserts a newline and the Send button is the sole send action.
- **Character limit** mirrors the API (proposal: 600 until the contract states one). Counter at 80%, danger text at 100%, send disabled with the reason in `aria-describedby`; never silently truncate.
- **Send states**: disabled (empty), enabled, sending (Stop in the same slot), cooldown (429: "Puedes enviar otra en 12 s").
- **Attachments: none.**
- Footer line, 12 px: "Respuestas generadas por IA. Cómo tratamos tus mensajes" linking to the privacy page.
- Draft survives minimize, resize, route and language change in memory only.

## 4. Errors, limits and states

| State | Trigger | UI | Recovery |
|---|---|---|---|
| Offline | Network error before first byte | "Sin conexión. Tu borrador está guardado"; send disabled | Re-enables on `online` |
| Interrupted | Stream ends with no terminal event | Draft kept, "Respuesta incompleta", Retry | Same-key replay (existing) |
| Rate limit | 429 with `Retry-After` | Cooldown countdown | Re-enables at 0 |
| Budget exhausted | `run.failed` `budget_exhausted` | "Hoy ya respondí demasiadas consultas. Escríbenos a {support_email}" plus handoff; send disabled for the session | Handoff only |
| Provider or catalog unavailable | `provider_unavailable`, `catalog_unavailable`, `timeout`, `generation_failed` | "No pude responder ahora" | Retry and handoff |
| Cannot start or expired | Session fails, API incompatible, cookie expired | Status "No disponible" or "La conversación venció" with support link; launcher shows the disabled style next view | Retry connection, or New conversation |
| Policy outcomes (pq) | `language-unsupported`, `payment-data-refused`, `price-unverified`, `unknown-policy` | Neutral info notice (never red), no product CTA | Handoff visible |

`role="alert"` for the first failure per run only. Copy has no codes or model names. Every state has an action.

## 5. Accessibility (WCAG 2.2 AA)

### 5.1 Dialog or non-modal: decision

| Mode | Semantics | Reason |
|---|---|---|
| Docked desktop | `<section role="region" aria-labelledby>` (non-modal), no `aria-modal`, no trap, page stays interactive | A chat that coexists with reading the page should not capture focus; Tab leaves, Esc returns |
| Expanded, portrait tablet, phone | `role="dialog" aria-modal="true"`, page `inert`, Tab contained | It covers the page, so the page must be unreachable |

Crossing a breakpoint while open keeps focus on the composer and swaps semantics in one render.

### 5.2 Focus

- Open: focus the composer for keyboard or fine-pointer opens; on touch focus the heading (`tabindex="-1"`) so the keyboard does not pop up uninvited (existing rule).
- Close/minimize: focus returns to the launcher. Esc closes in both modes after any open confirm or tooltip consumed it. Esc never stops a run; Stop is the button.
- Transcript is one tab stop (`tabindex="0"`, arrows scroll). 2.4.11: `scroll-padding-block: 56px 96px`; 2.5.8: every control 44 px (24 px floor).

### 5.3 Live regions

- A hidden `aria-live="polite"` status announces **lifecycle only**: "Enviado", "Pensando", "Respondiendo", "Respuesta lista", "Detenida", "Error: ...". The transcript is not `role="log"` (it would read every delta).
- The draft is inside `aria-busy="true"`; on completion one announcement reads the first 140 characters plus "respuesta completa disponible"; the full text is in the DOM for arrow-key reading. If testers prefer progressive reading, fallback is paragraph-boundary chunks, at most one per 2 s, never per token. **Judgment call: verify with NVDA, VoiceOver and TalkBack in M5.**
- Errors: first is `role="alert"`, rest polite.

### 5.4 Keys, motion, contrast, zoom, labels

Enter/Space opens; Esc closes; Tab cycles header, transcript, chips, composer, Send; arrows scroll the transcript. No global hotkeys (screen reader and page conflicts).

- Reduced motion: no stagger or caret blink, opacity-only open and intro, no hover rise.
- Contrast: body 7:1, components and rings 3:1, placeholder 4.5:1, recomputed from tokens by script. `forced-colors`: `CanvasText` borders, `Highlight` ring. `prefers-reduced-transparency`: no blur.
- Zoom 200% and 320 px reflow: no 2-D scroll or clipped control; header status wraps; chips wrap.
- Every icon button has an EN/ES (pf) or ES (pq) accessible name (Minimizar, Enviar, Detener, Nueva conversación, "Respuesta útil", Ampliar). Panel `lang` follows the page; stored answers keep their own `lang`.

## 6. Feedback, handoff, persistence, privacy

- **Feedback**: thumbs on the last completed answer only, 44 px, `aria-pressed`. Thumbs down shows a one-step chip row (Incorrecta, Desactualizada, No ayuda, Otro), no free text. Shown only if the contract has a feedback endpoint (portfolio yes; pequeverso hidden until the API adds one, never faked).
- **Handoff**: pequeverso persistent link "Hablar con una persona: {support_email}" (mailto with subject "Consulta desde el asistente", never prefilled with chat text), promoted to a button after any error, refusal, refund/payment topic or `price-unverified`. Portfolio: "Email me" plus CV link.
- **Persistence and reset**: history is server-side behind the HttpOnly cookie (existing); the client keeps in-memory UI state only; reload restores history without a generation; "Nueva conversación" confirms inline. Browser storage: only an optional `assistant:nudged` boolean in try/catch.
- **Privacy and consent**: the privacy line shows before the first message, which is the single trigger that creates the session and cookie. Analytics follow site consent (pq stored grant; pf off by default). No third-party requests from the panel.

## 7. Responsive matrix

| Width x height | Launcher | Panel | Verify |
|---|---|---|---|
| 320x568; 360x640; 390x844; 430x932 | 48 px circle (pq pill collapses at 320) / 52 px, above the bar | Full sheet | No bar overlap; 200% text; composer visible with keyboard |
| 568x320 landscape | 44 px circle at 66% height | Full sheet, compact header | Composer and Send visible |
| 768x1024 | 56 px | Bottom sheet 560 x 80dvh | Focus trap |
| 1024x768 | 56 px | Docked 400 x min(640, 100dvh - 48) | Non-modal |
| 1280x800, 1440x900 | 56 px | Docked, 20 px offsets | Hero overlap |
| 1920x1080 | 56 px | Docked, 24 px offsets; expanded caps 720x760 | Width does not grow |

## 8. Visual identity

### 8.1 Shared structure

Radii: panel 24, bubble 18, chip 999, card 14 (pq 16), control 12 px. Durations: instant 100, fast 160, base 220, sheet 280, intro 320 ms. Easings: out `cubic-bezier(0.22, 1, 0.36, 1)`, in-out `cubic-bezier(0.65, 0, 0.35, 1)`. Animate only `transform` and `opacity`. Icons inline SVG, rounded caps, 24 px grid, about 9 icons.

### 8.2 Portfolio tokens (reuse design-playbook primitives and semantics)

| Token | Dark | Light |
|---|---|---|
| surface | `oklch(0.21 0.055 262)` | `oklch(1 0 0)` |
| ground (transcript) | `oklch(0.17 0.05 262)` | `oklch(0.985 0.006 262)` |
| line / line-control | `oklch(0.33 0.07 262)` / `oklch(0.58 0.10 262)` | `oklch(0.85 0.025 262)` / `oklch(0.58 0.06 262)` |
| fg / fg-2 / muted | `oklch(0.97 0.01 262)` / `oklch(0.82 0.03 262)` / `oklch(0.72 0.04 262)` | `oklch(0.20 0.06 262)` / `oklch(0.40 0.05 262)` / `oklch(0.48 0.045 262)` |
| accent | cyan-400 `oklch(0.82 0.13 210)` | blue-700 `oklch(0.46 0.18 262)` |
| user bubble (white text) | blue-600 `oklch(0.55 0.20 262)`; use blue-700 if the test reports under 7:1 | blue-700 |
| ring | cyan-300 `oklch(0.88 0.09 210)` | blue-500 `oklch(0.64 0.19 262)` |
| danger | `oklch(0.72 0.17 25)` | `oklch(0.52 0.19 25)` |
| elevation | `0 24px 64px -16px oklch(0.05 0.05 262 / 70%)` + 1 px line | `0 1px 0 oklch(0.28 0.11 262 / 8%), 0 24px 48px -16px oklch(0.28 0.11 262 / 28%)` |

Dark: lighter surface plus border; light: shadow.

**Signature details**

1. **Orbit dot.** Header monogram in a 1 px ring with a 3 px cyan satellite that orbits (60 s, `rotate`) only while streaming; static otherwise and under reduced motion. Echoes the hero.
2. **Evidence trace.** When sources mount, a 16 px hairline grows (`clip-path`, 160 ms) from the answer to each chip; code chips show `path:L12-30` in mono. Evidence is the portfolio's USP.
3. **Instrument readout.** Mono 12 px line under the composer in place of a generic "AI can make mistakes" line, for example `grounded in public repos`. Copy must be verified true before shipping.

### 8.3 Pequeverso tokens (single light theme, `color-scheme: light`)

| Token | Value |
|---|---|
| surface | cream `oklch(0.987 0.012 80)` |
| header | navy `oklch(0.318 0.109 256)` with cream text (12.45) |
| line / control border | paper-100 `oklch(0.945 0.009 80)` / navy-600 `oklch(0.52 0.111 256)` |
| fg / fg-2 | ink (15.9) / paper-600 `oklch(0.52 0.019 80)` (5.5) |
| user bubble | navy with cream text |
| accent (links, icons) | teal-text `oklch(0.435 0.075 191)` (7.34) |
| CTA | coral `oklch(0.562 0.172 28)` white text 5.0; hover `0.493 0.157 28`; press `0.44 0.14 28` |
| price | coral-700 `oklch(0.43 0.151 28)` on coral-100 `oklch(0.945 0.027 28)` |
| gold | `oklch(0.891 0.165 94)` on navy grounds only, never text on light |
| ring | 3 px navy, 2 px cream offset; gold on navy |
| elevation | `--shadow-paper-2` (navy-950 tinted) |

Rounder geometry; 20 px icons; Fraunces for title and price.

**Signature details**

1. **Paper-cut night header.** Navy header with a 6 px scalloped paper edge (SVG mask) and two static gold stars from the night-sky concept; no animation.
2. **Sticker prices.** A validated price renders as a coral-100 sticker (static 2 deg rotation) with "Precio al {date}"; no price renders a dashed sticker "Mira el precio en la página". No number without provenance.
3. **Star that listens.** The launcher star's points glow (opacity 0.7 to 1, 2.4 s) only while a run is in progress and the panel is minimized, then rest with the unread dot; reduced motion shows only the dot.

## 9. Performance

- **Zero cost until intent.** Initial HTML: launcher, inline SVG, about 1 KB CSS. No fetch, session, cookie or panel code.
- **Intent signals** (first wins): hover or focus, `touchstart`, idle 2 s after the intro (skipped if `saveData` or `2g`), or click. Prefetch via `import()` of the panel entry (Next dynamic, `ssr: false`) or an injected `modulepreload`. Save-Data: hover and click only.
- **Budgets (proposals, measure in M5)**: launcher plus critical CSS at most 2.5 KB gz; panel chunk at most 60 KB gz JS and 8 KB gz CSS (pequeverso plan target); custom two-feature Markdown renderer, no library, no animation library.
- **No layout shift**: fixed launcher, overlay panel, `scrollbar-gutter: stable`, intrinsic image sizes.
- **INP-safe streaming**: one DOM write per frame; formatting applied at paragraph boundaries or on completion in slices of at most 8 ms (`scheduler.yield()` where available); no React state per token; older messages beyond 40 use `content-visibility: auto` with `contain-intrinsic-size`. Target INP under 200 ms in a 1,500-token fixture at 60 tokens/s and no long animation frame over 100 ms attributable to the panel.
- Host pages enabled-and-closed vs disabled: LCP delta at most 100 ms, CLS 0, TBT delta at most 30 ms (median of 5).

## 10. Analytics and product events

Consent-aware, closed schema, in the style of each contract (`product-event.schema.json`: `event_id` UUIDv4, `project`, `locale`, closed enums; pequeverso `site-experience-pequeverso-v1`). Sent through `features/site-analytics`; without a grant `track()` is a no-op and nothing is queued. Until each contract adds these names (same pattern as PF-M4-9) the widget calls a no-op port.

| `event_name` | When | Fields |
|---|---|---|
| `assistant_launcher_shown` | Intro completes | `viewport_class` (phone, tablet, desktop) |
| `assistant_open` | Panel opens | `trigger` (launcher, nudge, keyboard), `presentation` (compact, expanded, sheet) |
| `assistant_starter_click` | Starter or follow-up | `starter_id` (allowlist), `kind` |
| `assistant_message_sent` | Send | `length_bucket` (<=40, <=160, <=600), `turn_index` (1..20) |
| `assistant_first_token` | First delta | `ttft_bucket_ms` (<=1000, <=2500, <=5000, >5000) |
| `assistant_answer_completed` | `message.completed` | `duration_bucket_ms`, `source_count` (0..5), `product_count` (0..3) |
| `assistant_stopped` | Stop | `phase` (waiting, streaming) |
| `assistant_failed` | Failure | `code` (budget_exhausted, provider_unavailable, generation_failed, timeout, catalog_unavailable, offline, rate_limited, other) |
| `assistant_citation_click` | Source link | `source_type` (page, code, hotmart-help) |
| `assistant_product_click` | Pequeverso card | `action` (view, checkout), `product_id` (allowlist), `position: assistant` |
| `assistant_feedback` | Thumb | `value` (up, down), `reason` (incorrect, outdated, unhelpful, other, none) |
| `assistant_handoff_click` | Email or support | `origin` (header, error, refusal, footer) |
| `assistant_close` | Close or minimize | `reason` (button, escape, backdrop), `turns` (0..20) |
| `assistant_reset` | New conversation | none |

Envelope: `schema_version`, `project`, `source: "site"`, `event_id`, `locale`, `section`, and a per-page-view `widget_session` (random, never persisted, never linked to the API cookie). **Never sent**: message text, answers, URLs with queries, referrer, device data, API conversation ids, prices. Checkout reuses the existing `checkout_open` counter with position `assistant`.

## 11. Test plan

Fixtures: pequeverso `examples/stream.*.sse` and portfolio `sse.examples.json` via a Playwright route handler with pacing helpers (slow, stall, cut).

**E2E (Chromium, WebKit, Firefox; WebKit mobile for keyboard)**

1. Launcher in SSR HTML with JS disabled; zero API or chunk requests before intent; chunk on hover, focus, touch; Save-Data suppresses idle prefetch.
2. Open/close by click, Enter, Space, Esc; focus returns; minimize preserves the run; unread dot.
3. Stream scenarios: normal, recommendation with card, price-unverified, payment-data-refused, language-unsupported, cancelled, each failure code, interrupted with same-key replay, slow TTFT (8 s and 25 s with fake timers), 429 cooldown, offline toggle, budget exhausted, session unavailable.
4. Composer: Enter, Shift+Enter, IME composition, counter at 80% and 100%, draft survives minimize, route and locale change.
5. Product rules: price block only when payload price is non-null; `price: null` shows lookup text; a fixture whose prose says "US$99" but payload has no price shows no price block; no coral CTA in refusals; affiliate disclosure; URL policy.
6. Mobile keyboard: emulate `visualViewport` shrink via `page.evaluate`; composer box stays inside the visual viewport and header stays visible; real WebKit for the `offsetTop` case.
7. Collision: 25% scroll steps at 320, 360, 390, 430: launcher never intersects the buy bar, `[data-primary-cta]`, consent banner (pq) or recruiter chip and back-to-top (pf).
8. Keyboard-only journey; reduced-motion lane (`document.getAnimations()` shows opacity animations at most).
9. Privacy: no cookie before the first message; no analytics request without grant; with grant, payloads validate against the closed schema and carry no text.

**Accessibility**: axe (`wcag22aa`) in every state (closed, empty, thinking, streaming, answer with sources and card, each error), both themes, EN and ES, docked and modal: 0 serious or critical. Manual per release: NVDA+Firefox, VoiceOver iOS and macOS, TalkBack (lifecycle announcements, no per-token speech, focus return, targets); forced-colors and 200% zoom screenshots.

**Visual snapshots** from the dev-only state gallery (`NEXT_PUBLIC_DESIGN_GALLERY`): every launcher state and panel state (empty, thinking, streaming, answer+sources, answer+product, each error, expanded, confirm-reset, minimized) x theme (pf dark and light; pq single) x viewport (320, 390, 568 landscape, 768, 1024, 1440, 1920) x locale sample (pf EN/ES). Pinned container, `maxDiffPixelRatio` 0.01, animations frozen, fonts ready, canvas masked. M2 prunes the matrix using the flake policy.

**Performance gates (CI)**: bundle attribution (panel chunk at most 60 KB gz JS, 8 KB gz CSS; fail above, warn at 90%; launcher payload at most 2.5 KB gz); Lighthouse median of 5 enabled-closed vs disabled within section 9 deltas; INP and LoAF spec with the 1,500-token fixture; `PerformanceObserver` layout-shift check during open and streaming (CLS 0).

**Unit**: price renderer (null, present, prose spoof), URL policy, event validator, scroll-follow reducer, `--sticky-bar-h` contract.

**M2 scaffolding**: fixture server and pacing helper, gallery route stub, snapshot matrix, a11y runner, performance gate in warn mode, and red tests that M5 turns green.

## 12. Acceptance criteria (designer 95+)

Rubric weights: visual 20, motion 20, performance 15, accessibility 15, responsive 10, navigation 10, uniqueness 10; any accessibility blocker caps at 89. A 95 needs all of:

1. Launcher in SSR HTML, no network or panel JS before intent, intro after LCP, CLS 0.
2. No collision with the buy bar, offer card, consent banner, recruiter chip, back-to-top or any primary CTA across the scroll matrix (test 7 green).
3. Every launcher and panel state exists in the gallery and baselines, both themes on portfolio; none looks untreated.
4. Geometry matches sections 2 and 7; the keyboard never covers the composer in emulation.
5. Streaming: first delta paints within one frame, INP and LoAF gates green, no reflow of earlier messages, no automatic retry.
6. AI disclosure visible in the header and first message in every state; privacy link present; consent behaviour tested.
7. Pequeverso: every shown price has a validated source and date; no coral CTA in refusals; handoff one tap from every error; spoof fixture green.
8. axe 0 serious or critical in every state; manual screen reader pass; focus return; 44 px targets; 200% zoom and 320 px reflow; forced-colors and reduced-motion lanes green.
9. Contrast from tokens: text 7:1, components 3:1 in each theme.
10. Panel chunk at most 60 KB gz; Lighthouse deltas within gates; no new animation dependency.
11. Three signature details per site survive a screenshot test and the two skins differ visibly while behaving identically.
12. Analytics: no grant means zero events and requests; with a grant only the section 10 events, none with free text.
13. Owner sign-off on W-1 to W-5 recorded; designer-evaluator run with screenshots; any gap listed with its blocker.

## 13. Risks and unknowns

- Requests to API owners (not assumed): `limits.max_chars` in the session response; for pequeverso a feedback endpoint. Live-region strategy (5.3) is a judgment: verify with real screen readers. iOS Visual Viewport varies by version: one physical-device pass. The 60 KB budget is a plan target, not a measurement; foldable rules are untested on hardware; reference-product comparisons are unverified.

## 14. Rich blocks rendering

Applies when the session `capabilities.blocks` is true and the request sent `X-Assistant-Blocks: 1`; otherwise sections 3.2 to 3.5 apply unchanged. Contract: [assistant-experience.md](assistant-experience.md) section 4 (additive v1.x, closed block union, status: proposal).

- **Fail closed**: an unknown block `type`, an unknown `icon_id` or a URL that fails `domain/links.ts` renders nothing (icons fall back to a generic glyph). Never render HTML; never parse prose into a price, link or card. Blocks mount after `message.completed`, below the reader's anchor, in the server's order.
- **Text**: paragraph; citation markers derived from `claims` are links or buttons named "Fuente n: title, tipo" and open the source list entry.
- **Citations**: ordered list; local SVG sprite by `icon_id`, never a remote favicon; `origin: web` shows a "Web" text badge and the host (not colour alone) and `source_type: official_help` keeps the "Hotmart · procedimiento general" suffix; `rel="noopener noreferrer"`, `referrerpolicy="no-referrer"`, no UTM added.
- **Fundamentos**: native `details`, collapsed; shows the server-extracted quote and its source.
- **Cards**: `article` named by its title; `product_card` price only from validated `price` (null shows the existing "Consulta el precio" text); `project_card` shows stack icons with accessible names (text if the icon is missing); at most one coral CTA per answer (section 3.5 rules).
- **Chips and follow-ups**: chips are links (at most 3); follow-ups are buttons in a labelled group and send the full original text.
- **Notice, feedback, memory**: `notice` uses `role="note"`; `feedback` follows section 6 (hidden if `capabilities.feedback` is false); `memory_prompt` is a confirm-per-item control and the panel menu offers "Qué recuerdo" and "Olvídame" only when `capabilities.memory` is true, with a switch that is off by default.
- **Progress**: `run.progress` replaces the "Pensando…" label by phase when present; announced through the single polite live region at most once per 2 s; `prefers-reduced-motion` removes fades.
- **Tests**: fixtures for every type, unknown type, null price, web versus first-party source; axe; no third-party network request; reduced-motion emulation.
