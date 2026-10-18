# Native assistant · final reading polish, 2026-10-17

**Local fixture preview. Production remains disabled.** These photographs show the actual
Pequeverso interface, not a generated mockup. The compact panel is 408 × 560 CSS px; its
native element photographs are 816 × 1120 pixels (DPR 2), with no bitmap edits or stitching.
The mobile and expanded views retain their original viewport and scroll position.

The [manifest](manifest.json) records exact UI/API commits, genuine build metadata, dimensions
and hashes. The UI source is `61ca8b0`, verified in PR113 at `39063e4`; fixture API is `8ba99fe`.
The enabled local export still correctly identifies its build base `1eb6d76`; this is not a
claim that the entire screenshot depicts a later release or API version.

| Welcome and suggested questions | Completed answer and sources |
| --- | --- |
| [![Actual compact welcome](desktop-welcome.png)](desktop-welcome.png) | [![Actual fixture guarantee answer and two source links](desktop-answer-sources.png)](desktop-answer-sources.png) |

[Mobile conversation and input](mobile-conversation.png) ·
[Expanded desktop, with product details below the answer](desktop-expanded.png).
Each file opens at original resolution. Long content remains scrollable; the mobile photograph
is a real scroll position and does not claim to show the complete product card.

The final reading change removes a reserved empty column and places the latest-answer action
in the header. The discrete privacy link leads to the actual treatment policy. No language or
theme selector is added. The implementing and independent root agents inspected these images;
this is agent review, not human review.

The verification run for PR113 passed 211 native cases with 47 explicit configuration skips,
without retries or flakes. The local affected matrix passed 46 cases with 14 configuration skips.
Original failed format and preview attempts remain recorded in the release evidence; they are
not relabeled as successes. No provider call was made for this gallery.

These photographs do not validate answer correctness with the real model, purchases, physical
phone keyboards, field performance, production cookies/proxy settings or deployment to the VPS.
The dated [2026-10-12 gallery](../native-assistant-2026-10-12/README.md) retains its earlier states and provenance.
See the [assistant activation checklist](../../handoffs/storefront-transition.md) before any future activation.

The original storefront gallery is pinned at [c9aaa991](https://github.com/gonzalomartinperez/pequeverso/tree/c9aaa99169f3db16dcea354734aea866f3a86bef/docs/verification/assistant/2026-10-17).
These files were copied into the API documentation without bitmap changes; repository-relative
links below are adapted for this documentation location.

## Reproduce

Use the **storefront repository** fixture photography harness and an isolated checkout at the exact API
revision recorded by the test configuration. Run `npm run build:assistant-fixture` and the
assistant Playwright suite with `ASSISTANT_API_DIR` pointing to that checkout. For matching this
historical gallery exactly, use the UI and API commits above and DPR 2; current fixtures may have
changed. Capture the real panel with `locator.screenshot()`, preserving viewport/scroll metadata,
and inspect each image before copying it. Never publish the enabled fixture export.

For the compact closeups, use Chromium at a 1440 × 1000 CSS px viewport and DPR 2. Open
`/soporte/`, explicitly open the launcher, and wait for `assistant-panel[data-phase="ready"]`.
Take the first photograph with `page.getByTestId('assistant-panel').screenshot()`.
Submit **¿Cómo funciona la garantía de Grafismo Fonético?**, wait for `data-phase="completed"`,
expand the two-source disclosure, and scroll the conversation container to its beginning.
Before the second photograph, assert the original question, seven-day answer, both source
links and input are in the viewport. Use `animations: "disabled"` for both native screenshots.
The capture uses the normal fixture configuration with marketing and analytics consent off,
blocked Facebook requests and zero retries; it does not replace the behavioral test suite.
