# Real application evaluation — 2026-10-19

The storefront assistant remains disabled. These are isolated local HTTP application tests,
not a deployed VPS or a production activation. Generation used only OpenAI `gpt-6-luna`,
reasoning `medium`; public retrieval used `text-embedding-3-small`. No generation fallback
or automatic retry was enabled. Full synthetic responses remain in private local artifacts.

## Frozen evaluations and review

| Phase | API revision | Turns | Generations / local answers | Agent semantic review |
|---|---|---:|---:|---|
| Complete original matrix | `0a76456b96b0640363786a4dcea885cdeebc2141` |245|237 /8|195 acceptable,46 P3,4 P2,0 P1|
| Targeted development revalidation | `e7a0a193e287706b2e67df3db050a606d7f9434c` |20|12 /8|20 acceptable,0 P1/P2/P3|

The original matrix was fixed before execution. It includes independent questions,
translations and follow-up families;245 turns are not245 independent intentions. The20-turn
phase repeats the affected conversations and adds development variants. Neither phase is a
blind holdout or a human review. A successful terminal event does not establish correctness.
The original answers and findings were preserved rather than reclassified after corrections.

Both phases bind catalogue SHA256
`54a91da21c2ee941b604e0bdbc643cc1f799e613ee6423d335463d4f2af56b2b`, generated
2026-10-18T23:13:02Z from storefront `7dde2968783c809205bd6ba16ec4a4661b936ca0`.
The original executable manifest SHA256 is
`041c0e40fdc9623b9c5be1184b0e65fd4da205a06de51e44708c6d2ed43479f9`;
the targeted executable manifest is
`2840d110a36c7372d5945220c7d40fec10c0d6b982723051b6159d1ebc67b339`.
Evaluation questions and private conversations were never indexed as public knowledge.

## Defects, corrections and limits

The four P2 findings concerned an unknown course price being treated as unequal to the kit,
a singular reference after two products, video format being converted into a prohibition on
printable extras, and an ambiguous guide reference resolved to an unmentioned product.
Narrow domain guards now clarify ambiguous identities and preserve uncertainty about unknown
prices or extras. They use the immediate typed conversation and canonical product identities;
incidental page context cannot choose the answer.97 focused deterministic regressions and
independent source review cover these corrections. They do not prove arbitrary entailment.

The targeted run checked the actual retrieved passages, their hashes, citations, final text,
streamed deltas and history. All20 responses passed agent semantic review; this does not
recertify the entire original245 matrix on the later source. The46 original P3 notes remain
visible: chiefly unnecessary clarification, generic support guidance, repetitive presentation
or unnecessary commercial cards. No sales-conversion uplift was measured.

An initial targeted attempt produced one correct local answer and two index embeddings,
without a Luna generation. Its evaluator incorrectly marked a current local price unverified
because no model evidence existed. The fix reads the actual active catalogue and configured
clock before the request, retains stale/unknown-price rejection, and has22 regressions plus
independent review. An explicit append-only operator acknowledgement preserves the original
gate, attempts and costs. That failed attempt was not silently retried or overwritten.

## Transport, retrieval and persistence

The complete245 phase used real loopback Uvicorn HTTP/SSE, visitor sessions, cookies, CSRF,
Origin validation, PostgreSQL private persistence and public PostgreSQL/Neo4j GraphRAG.
All245 final answers matched recovered history and replay; replay dispatched no additional
generation, embedding or retrieval. The targeted20 phase retained all20 history/replay
matches. A separate visitor had empty history; invalid CSRF and Origin received403.

Twelve separately registered retrieval queries accompanied the original matrix. Per-query
artifacts retain lexical/vector/graph observations and the evidence actually supplied to
generation. Supplied evidence and a valid citation URL alone do not prove claim support or
that graph retrieval improves quality. Canonical product facts also inform generation.
The optional official-help reader remains restricted to three approved Hotmart articles;
this is not unrestricted browsing or authority for product-specific promises.

One original streamed response was replaced by a safe final answer under answer policy.
Final/history equality therefore does not mean every original streamed delta equalled the
persisted final response. No purchase, reservation, refund or support submission was executed.

## Measured timing and accounting

The original245 phase began01:08:14.459110Z. Median first streamed content was5.168s
(229 turns with a first-content measurement); median total duration5.809s, p9511.977s, maximum18.532s.
It used488 SDK attempts:237 generations,239 embeddings including two index batches, and
12 additional component queries. Its conservative ledger delta wasUS$0.403505.

The targeted20 supervisor began03:05:33.721067Z and finished03:08:16.513711Z.
Median first streamed content was5.755s (12 streaming replies); median first visible content
including local replies4.673s; median total5.228s, maximum10.952s. It used26 SDK attempts:
12 generations and14 embeddings. Its conservative delta wasUS$0.021152.

Final accumulated accounting is2060/2100 attempts andUS$2.048751 against the authorized
US$6 accumulated ceiling, with no pending or uncertain paid requests. The monthlyUS$10 limit
was unchanged. These conservative charges are not an invoice; per-response billed USD is
unavailable and is not reported as zero. Earlier costs and interrupted runs remain included.

## Cleanup, reproduction and production gates

The original evaluator and holder completed successfully, but its wrapper failed a final
Docker absence check. A separate typed readback confirmed its owned resources absent; the
original failure is retained. The targeted20 wrapper completed with exit0, all five owned
resources absent, no live owned groups and no automatic retry. PostgreSQL dumps, role backups,
nonempty TOCs and hash-bound operator cleanup acknowledgements were preserved. Those checks
are not a full-system restoration demonstration.

Use [the evaluation procedures](../evaluation.md) and the immutable revisions/manifests above.
Deterministic fixture regressions run without a key; paid reproduction needs separate explicit
owner authorization, private credentials and an unchanged audited budget. Do not reset the
ledger or increase attempts merely to reproduce a result.

Public HTTPS, proxy SSE, cookie/CORS policy, deployed source identity, backups/restoration,
capacity, alert routing and final model behaviour on the VPS remain activation gates for
vps-ops. Neither local model tests nor screenshots establish production readiness.
