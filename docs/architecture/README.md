# Editable API context diagrams

The light/dark Mermaid sources and committed SVGs provide the README context view. They
contain native text and local styles, with no scripts, foreignObject, remote fonts or runtime
dependencies. The existing request sequence and [architecture](../architecture.md) preserve
the detailed order of checks, data ownership and dependency direction.

Solid arrows identify implemented relationships. Dashed arrows identify optional, disabled or
infrastructure-owned relationships; read their labels. The store assistant remains disabled.
The default provider is fixture; actual OpenAI use requires authorization and bounded accounting.
API-owned SQLite stores catalog, conversations and the ledger. Backoffice PostgreSQL stores
identity, sessions and invitations. vps-ops owns deployment and shared observability.

Renderer: Mermaid 12.2.0 browser bundle from the local locked distribution installed with
Mermaid CLI 12.0.0; Playwright 1.64.1 / Chromium 156.0.8078.4, strict security, HTML labels off.
No CLI subprocess or GitHub-native rendering is claimed. Implementing and independent root
agents inspected both themes at original size and 896/390 pixels; this is not human review.
The earlier tall/low-contrast candidates were rejected and preserved externally. At narrow
widths, read the adjacent prose or open the original SVG rather than relying on scaled labels.
