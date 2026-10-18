# Real-model evaluation — 2026-10-18

## Scope and identities

The shopping assistant remains disabled in every publishable storefront build. This report
describes isolated local application evaluations, not an activated storefront or deployed VPS.
The only generation provider was OpenAI `gpt-6-luna`, reasoning `medium`, with
`text-embedding-3-small` for public catalogue indexing and query retrieval. No generation
fallback or automatic retry was enabled. Full synthetic questions, answers and evidence are
private local artifacts; no customer conversation or private prompt is published here.

The final complete229-turn run used API source
`c4c3340bd84734e4f71589154d5ab1a71b79c7a2`, tree
`c7ebb3d34fcb50707feb04118197ed786a7208b2`, prompt2026-10-18.2. Its frozen source manifest
SHA256 is `210b8dbd85b6c5723fba6d857f54bf2d4a960c0eb6820da17b2db15489b1b33a`;
the selected executable manifest hash is
`6add8eeeebe1ac12aef3b709f5e4cd86d90045f220f812cf04675d527831740f`.
The catalogue hash is
`a8a8e0d8e66ff83b7858d218bb70c9bacf43527ec75164ef1b9fba7c755452dd`,
generated2026-10-18T02:40:55Z from storefront
`fd2f150fe2e08955b3817c3b18ff14dea920d74e`. Its public corpus has43 chunks,47 entities and47
relations. None of the evaluation questions or conversations was indexed as knowledge.

The matrix contains213 cases/229 turns: original225 turns plus four explicitly post-adjustment
variants. It covers28 intent families, Spanish/English input, unsupported-language requests,
follow-ups, products, formats, comparisons, prices, policy, health boundaries, prompt injection,
private-data requests and unavailable actions. The storefront's Spanish-native reply policy
was applied. Independent questions, translations and development-exposed variants are not
reported as229 independent intentions or a blind holdout.

## Preserved runs and semantic review

| Phase | Source | Registered answers | Real generations / local replies | Agent review |
|---|---|---:|---:|---|
| Initial, interrupted |27a260c|208|201/7|28P2 and15P3|
| First targeted adjustments |6f33e87|32|32/0|0P1/P2;8P3|
| Complete fixed229 matrix |c4c3340|229|221/8|0P1;2P2;28P3;199 without notes|

The initial run also contains one fully streamed completion whose history/replay postconditions
were not checked and16 turns not started. It is not a completed225-answer evaluation. The
32-answer targeted run reached the exact1100-attempt guard before the final replay:32 histories
and31 replays matched, but the process exited1. Neither original failure was overwritten.

The first correction made current questions outrank incidental page context, retained both
products for comparisons, distinguished the course's actual video format from the kit's PDFs
and improved references and unknown-price handling. The final229 matrix deliberately used
`/grafismo-fonetico/` as weak page context for every query; this is not a varied-page benchmark.

All229 complete final responses were read by agents, not humans. One reviewer also authored
part of the prompt; review ownership is recorded. Root independently confirmed both remaining
P2 findings: an unsupported mandatory-separate-checkout condition when both products were
requested, and a claim that included bonuses were not sold individually when the FAQ only
confirmed their inclusion without extra payment. Appropriate uncertainty is preferable to
inventing either permission or prohibition. P3 notes include excessive clarification,
irrelevant commercial cards/citations, repetition and safe but generic support guidance.

A subsequent bounded domain guard and prompt2026-10-18.3 address those two P2 forms. The guard
checks both stream prefixes and final text, distinguishes assistant refusal/uncertainty from
merchant restrictions and requires explicit published wording. It preserves the actual included-
bonus FAQ. These finite recognizers do not establish arbitrary semantic entailment. Meaningful
regressions reproduce both defects before the fix and preserve legitimate responses. Literal
prompt/version mirror tests were removed. Subsequent real-model revalidation is recorded
separately once completed; the229 outcomes above retain their actual source and defects.

## Application, evidence and persistence

The complete run exercised loopback HTTP through the real FastAPI application, visitor
sessions, cookies, CSRF, Origin checks, HTTP/SSE, persistence and recovery. All229 final replies
matched stored history and replay. Replay created zero additional generation or embedding
requests. A separate visitor had empty history; invalid CSRF and Origin were rejected403.
These checks are local and do not establish public HTTPS, browser cookies or proxy SSE on a VPS.

Per-turn private records distinguish retrieved public passages, canonical catalogue evidence
actually supplied to generation, final source IDs, provider/local abstention and timings.
A valid source URL or supplied ID alone is not proof of claim entailment. Canonical product
facts remain available even when hybrid retrieval is narrow, so successful answers must not
be attributed solely to vector or graph search. Strategy traces exist, but the229 receipt
does not retain independent candidate rankings for each strategy. A separately preregistered
component audit is required before claiming per-strategy coverage or graph benefit.

The optional official-help reader can retrieve only three fixed server-owned Hotmart help
articles. It is not general internet search, a model-selected arbitrary URL tool, or authority
for product-specific promises. Fixture tests keep this external network disabled.

## Measured usage and local timing

The complete229 run started17:58:55.344582Z and finished18:23:53.386696Z with exit0. It used
221 generation requests and223 embeddings (two index batches plus221 query embeddings),
444 new SDK attempts. Every attempt settled with known usage and matched the conservative
ledger charge. The first1100 attempt rows and all other ledger tables remained unchanged.
The accumulated ledger is1544 attempts/US$1.623968 conservative, zero pending or uncertain
requests, against the explicitly authorized1600-attempt/US$6 accumulated cap. The monthly
US$10 limit was not changed. No unused attempt or aborted request was silently refunded.

Using provider-reported tokens and the official rates checked2026-10-18, this phase's
Standard-rate cost estimate isUS$0.127841525. It is an estimate, not a reconciled invoice.
The original208 phase estimate wasUS$0.116274110; the32 phaseUS$0.018501160. The conservative
guard deliberately reserves more and must not be described as billed spend.

Across all229 turns, including eight local replies, first visible content had median4.914s,
p95(nearest-rank)9.677s and maximum14.199s; total duration median5.527s, p9510.744s and
maximum14.973s. These are local loopback measurements, not browser/VPS capacity or sales uplift.

The services were isolated on new owned volumes with four non-owner login capabilities.
Before cleanup, a private PostgreSQL dump and role definitions were retained. Owned services
and roles were removed; loopback PostgreSQL/Neo4j ports subsequently refused connections.
Actual external backup recovery and capacity remain vps-ops gates. No image was published.

## Remaining acceptance

- Finish affected-case real-model revalidation and the new producer-copy catalogue checks,
  preserving the completed229 run and its hash.
- Run the component audit with one shared budget owner and no duplicate query encode or retry.
- Pass full checks and protected CI for the exact final source and independently review the diff.
- Resolve the API/Neo4j image security blockers and complete actual VPS HTTPS/CORS/cookies,
  proxy streaming, authorization, restore and capacity tests before deployment or activation.
- Obtain independent human/holdout review, physical-device/accessibility checks and real
  conversion evidence; no automated completion rate establishes those outcomes.
