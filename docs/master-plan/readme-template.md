# Unified README template (ecosystem standard v1, 2026-11-09)

Same skeleton, order, headings and tone in all nine repositories (private repos use the PRIVATE variant). 80–180 lines. English (Spanish for pequeverso-marketing and dropshipping-ops, whose docs are in Spanish). Affirmative voice: state what the system does and how it is verified; limits go in one short "Scope and limits" section, never scattered caveats. No dated provenance in the README (it lives in CHANGELOG and docs/). Images: one hero capture (light and dark via `<picture>` with `prefers-color-scheme`) for UI repos; diagrams as Mermaid or committed light/dark SVG.

```markdown
<!-- Variant: PUBLIC | PRIVATE -->
<div align="center">
  <img src='docs/assets/<repo>-mark.svg' alt="" width="56" height="56">
  <h1><Product name></h1>
  <p><One-line value proposition, ≤ 120 characters.></p>
  <!-- At most three badges: CI gate, latest release, license -->
  <a href='.../actions/workflows/ci.yml'><img alt="CI" src='...'></a>
  <a href='.../releases'><img alt="Release" src='...'></a>
  <a href='LICENSE'><img alt="License" src='...'></a>
</div>

<picture> hero capture light/dark (UI repos) </picture>

## Why

Three to five sentences: the problem, who it serves, what makes it different.

## Highlights

- Three to six measured, verifiable bullets (numbers link to CI evidence or docs).

## Architecture

Mermaid C4 context or container diagram (≤ 15 nodes) + two sentences on the dependency rule. Link: docs/architecture.md.

## Quickstart

    # Quickstart commands (render as a bash code block in the real README)
    <one command setup>     # e.g. just setup | npm run setup
    <one command check>     # mirrors CI: npm run check | just check
    <one command run>
Requirements line (Node 26 LTS / Python 3.14, Docker if needed).

## Usage                       <!-- PUBLIC: Demo / live link · PRIVATE: Where it runs -->

Short task-oriented examples or links to how-to guides.

## Quality

Table: gate | tool | threshold, pointing to the scorecard (docs/master-plan/scorecard.md) and the latest CI run.

## Documentation

Diátaxis map: Tutorials · How-to · Reference · Explanation (ADRs) · Master plan.

## Ecosystem

Identical table in the seven ecosystem READMEs (six public product repos + `vps-ops`): one row per repo (name, role, link; `vps-ops` listed as private without link). The private business repos `pequeverso-marketing` and `dropshipping-ops` are never listed in public READMEs; their own READMEs list the repos they relate to.

## Contributing and security

Links to CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md (public repos).

## Scope and limits

Up to four bullets.

## License

One line.
```

Checks (docs profile in CI): markdownlint, lychee links, line count 80–180, required headings present in order, ≤ 3 badges, Ecosystem table identical to the standard (hash check), no `TODO`, images have alt text (decorative logo uses empty alt).
