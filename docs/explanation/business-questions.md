# Open business questions

| # | Question | Default applied until answered |
|---|---|---|
| 1 | Confirm that storefront copy and media (© Pequeverso, all rights reserved) may be republished in this public repository (catalog snapshot, contract examples). The same text is already public in the storefront repository | Used only to answer about Pequeverso's own product |
| 1b | **Answered 2026-10-17:** owner-authorized MIT for software only; brand, commercial content, media, data and third-party material excluded | [MIT](../../LICENSE), [scope](../../NOTICE.md); existing content rights unchanged |
| 2 | Privacy-policy text for the assistant (drafted scope in docs/explanation/security.md) and its legal review | Assistant must stay disabled in production until the text is live |
| 3 | School or classroom licensing ("licencia para tu centro" appears in the support copy but no terms exist) | Assistant says it has no licensing details and offers support |
| 4 | ~~Should the assistant answer in Portuguese or English, or always Spanish?~~ **Answered 2026-10-05:** Spanish and English; other languages get a short bilingual note | Implemented (ADR-0004) |
| 5 | Re-sync cadence owner for prices and content (weekly minimum) | Price withheld after 168 h without a re-sync |
| 6 | Paid use authorization: create the separate OpenAI project, key and hard limit; approve the live evaluation (≤ USD 0.25) | Fixture only; production refuses fixture answers |
| 7 | Final hostnames (`assistant.pequeverso.com` for the API, a separate host for the backoffice) and DNS | Proposed only; nothing is routed |

## Catalog content gaps (PVA-M3.5, 2026-11-21)

Visitors ask these questions in the evaluation set (`evals/full/`), and the catalog has no text to
answer them. Until the owner adds storefront copy, the assistant must say it has no information and
offer the support route. It never guesses. Each row names the evaluation items that show the gap.

| # | Question for the owner | What the catalog says today | Items |
|---|---|---|---|
| 8 | Support availability: which days and hours, in which time zone? Is there any channel besides e-mail (WhatsApp, phone)? | Only e-mail support, "normalmente en 48 horas hábiles"; no hours, time zone or other channel | `sup-002`, `sup-012`, `sup-013` |
| 9 | Purchase steps: which button on the storefront starts the purchase, and what does the buyer see next (Hotmart checkout, thank-you page)? | Payment happens on Hotmart's secure page; access arrives by e-mail. The click path and the thank-you page are not described | `buy-001`, `buy-010`, `buy-019` |
| 10 | Invoices: can a buyer get an invoice (for example a company invoice), and who issues it? | Nothing | `buy-006` |
| 11 | Gifts: can the kit be bought for another person, and how does that person get access? | Access goes to the purchase e-mail; gifting is not covered | `buy-007` |
| 12 | Hotmart account: does buying require creating an account? | Access is through consumer.hotmart.com with the purchase e-mail; account creation is not stated | `buy-009` |
| 13 | Pending or unwanted orders: how does a buyer cancel a pending payment (boleto, transfer, cash) that was never paid? | Refund and withdrawal routes exist for paid orders only | `buy-014` |
| 14 | Other languages: is there a Portuguese (or other) edition? | Nothing; the material is in Spanish | `oos-010` |
| 15 | Other products: are more kits planned (for example early maths), or physical products? | Only the current products and a digital-only delivery policy | `oos-011`, `oos-009`, `oos-018` |

Already listed above and still open: school or classroom licensing (#3).

### Behavior found while measuring (fixture lane)

In fixture mode, decline and no-information answers do not always attach the support link. The
corpus grader reports "offers no support route" on most `out-of-scope` items. The fixture provider
is not a real model, so this is a recommendation and not a measured live defect. The answer policy
could attach the support link in code whenever an answer cites no catalog evidence. That belongs
with the final-answer validators of PVA-M4-X (`validate_final`), and the live lane should confirm it
first.
