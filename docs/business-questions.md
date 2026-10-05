# Open business questions

| # | Question | Default applied until answered |
|---|---|---|
| 1 | Confirm that storefront copy and media (© Pequeverso, all rights reserved) may be republished in this public repository (catalog snapshot, contract examples). The same text is already public in the storefront repository | Used only to answer about Pequeverso's own product |
| 1b | Choose a license for this public repository, or keep "no license, all rights reserved" (the current state) | No license |
| 2 | Privacy-policy text for the assistant (drafted scope in docs/security.md) and its legal review | Assistant must stay disabled in production until the text is live |
| 3 | School or classroom licensing ("licencia para tu centro" appears in the support copy but no terms exist) | Assistant says it has no licensing details and offers support |
| 4 | ~~Should the assistant answer in Portuguese or English, or always Spanish?~~ **Answered 2026-10-05:** Spanish and English; other languages get a short bilingual note | Implemented (ADR-0004) |
| 5 | Re-sync cadence owner for prices and content (weekly minimum) | Price withheld after 168 h without a re-sync |
| 6 | Paid use authorization: create the separate OpenAI project, key and hard limit; approve the live evaluation (≤ USD 0.25) | Fixture only; production refuses fixture answers |
| 7 | Final hostnames (`assistant.pequeverso.com` for the API, a separate host for the backoffice) and DNS | Proposed only; nothing is routed |
