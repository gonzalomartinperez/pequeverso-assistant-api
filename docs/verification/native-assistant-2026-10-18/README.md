# Native assistant · local fixture preview, 2026-10-18

**The enabled fixture export is not publishable. Production remains OFF.** These seven PNGs
are actual unedited captures, not generated mockups or real-model answers. They were copied
byte-for-byte from Store commit `87c2e443`, whose gallery records the capture provenance.

| State | Original PNG |
| --- | --- |
| Desktop launcher | [Launcher](01-Desktop-Boton.png) |
| Desktop welcome | [Welcome and suggested questions](02-Desktop-Bienvenida.png) |
| Desktop conversation | [Fixture answer and expanded sources](03-Desktop-Conversacion.png) |
| Desktop waiting | [Held local HTTP request and cancellation control](04-Desktop-Espera.png) |
| Mobile welcome | [Welcome and input](05-Mobile-Bienvenida.png) |
| Mobile conversation | [Scrollable answer and fixed composer](06-Mobile-Conversacion.png) |
| Expanded desktop | [Additional product/source detail](07-Desktop-Conversacion-Ampliada.png) |

The capture used Store `755d541a86389703665e65c2b762aacfb6e345ad` with fixture producer
`2f22f24b30de7ee6a797d6397bef7422eb8e31cc`. The [manifest](manifest.json) records all seven
original hashes and the copying commit. Desktop image dimensions are1440×1000; mobile
images are1082×2202. These are image pixels, not inferred CSS viewports. Mobile cards scroll;
the screenshot does not claim to display their complete contents.

The original local fixture build took53.700s and two native Chromium preview cases took28.461s,
with zero skips/retries/flakes. The waiting capture held the real local HTTP request. Root's
capture review covered all seven images; a separate Ops agent reviewed the exact first six.
This documentation author additionally inspected the two README images. All are agent reviews,
not human review or accessibility certification. No key or paid provider was used for this UI run.

Reproduction uses those two isolated source revisions, Store's documented
`build:assistant-fixture` and `tests/assistant/preview.spec.ts`, and the locked fixture API.
Never publish `out-assistant-fixture/`. See [the dated evidence report](../api-evidence-2026-10-18.md)
for PostgreSQL/CI scope and the separate real-model limitations. Earlier galleries remain intact.
