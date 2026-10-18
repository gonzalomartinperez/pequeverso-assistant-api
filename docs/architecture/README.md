# API architecture diagrams

The README uses authored native SVGs with Pequeverso colors and explicit public/private trust
boundaries. They contain local text and shapes, no scripts, HTML foreignObject, remote resources
or fonts. Matching Mermaid files preserve the semantic relationships; they do not generate the
same presentation. Open either original SVG for readable detail at narrow viewport widths.

The production profile uses separate public/private PostgreSQL schemas and a public-only Neo4j
projection. SQLite remains the isolated fixture/import profile. The native storefront assistant
stays disabled; deployment and shared observability belong to vps-ops. Images describe application
boundaries, not a deployed topology, VPS capacity or security approval.

See [operator capabilities and gates](../knowledge-operations.md),
[the semantic and fixture distinction](../graph-retrieval.md) and
[resource ownership](../architecture.md). The manifest retains exact asset hashes and visual
review status. Earlier Mermaid-rendered baseline diagrams remain in Git history.
