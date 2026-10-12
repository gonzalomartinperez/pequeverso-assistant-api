# Real-model evaluation — 2026-10-12

The owner authorized OpenAI GPT-6 Luna with reasoning medium, within a USD10 monthly project
maximum. All executions below used one stricter immutable USD1 /400-attempt evaluation ledger,
Standard tier, no fallback and no automatic generation retries. The key and complete answers
remain private outside Git. This record does not authorize production, deployment or activation.

## Frozen inputs and execution

| Evidence | Original baseline | Spanish post-adjustment run |
|---|---|---|
| Application commit | `8286861fe093d0ca978c2c437e563b5976552061` | `82f83c40b90364e5812d3dd56133f549ac85ce30` |
| Prompt | `2026-10-05.1` | `2026-10-12.1` |
| Python | 3.13.15 | 3.14.8 |
| Matrix | `evals/end_to_end_postfix.json` | `evals/end_to_end_spanish_native_revalidation.json` |
| Manifest SHA256 | `dd6b16308b2a67a2bf51f258d2d38a04ff4278cdd168af5065758af274f617ad` | `77e0dd9b1778d4ea6b449ee4bdbd03008eec519de032922691e038a35355f9be` |
| Queries / actual model generations / local notices | 236 /221 /15 | 53 /46 /7 |
| HTTP histories / exact replays | 235 /219 final turns | 53 /53 every turn |
| Usage-derived USD estimate, not invoice | 0.126675 | 0.023532275 |
| Conservative shared accounting, USD | 0.280707 | 0.351214 cumulative |

Both runs used catalog SHA256
`ddddf3d05182fc4f77fd1f26e5bbd621bb09f2fe1f4425ee82f536fd77559a76`, exported at
2026-10-12T17:18:06Z from storefront main `eb68a041b4515d71a734626fdaee0ef06d8693c3`.
This proves Git provenance and configured freshness, not current merchant approval, stock or
the final checkout total. One product, nine included resources and23 documents fit the evidence
bound; the model received the whole catalog. Lexical ranking is recorded separately. There is
no vector/graph search or indexing of evaluation questions.

The initial harness was interrupted after111 checkpoints and a112th completed terminal turn.
The cause of SIGTERM is unknown. The112th final content matched SQLite offline, but HTTP history
and replay were not exercised for it. A reviewed continuation resumed the remaining124 queries
without repeating any completed generation, using unchanged application, prompt, catalog and
shared budget. Initial files and hashes remain intact. Its full SDK receipt was lost; settled
application usage/cost exists, but cache-write token count cannot be reconstructed for that turn.

## What was actually checked

Every generation entered the isolated application through session cookies, Origin, CSRF,
HTTP/SSE, evidence preparation, final validation and SQLite persistence. Invalid Origin and
CSRF returned403; a separate visitor had empty history. Replays produced no new provider calls.
There were no structural/history failures or unsettled paid attempts in either completed run.
The baseline had one known historical language annotation error, retained unchanged.

The53-query development revalidation repeats25 unchanged cases and adds20 variant cases.
Native-policy expectations are declared outside original case annotations. Seven local Spanish
notices validate the changed language policy, not improved model tone. This is not an independent
holdout and must not be presented as such.

An independent coding agent reviewed all236 baseline finals,221 drafts and suggested questions;
then all53 later finals,46 drafts and chips. It reconstructed220 initial and46 later evidence
receipts against the frozen catalog hashes. One interrupted receipt is unavailable. A recording
bug duplicated resource-id prefixes in initial metadata; the actual sent payload hashes matched.
The runner now records canonical ids, with a deterministic regression. Initial files were not
rewritten.

The baseline review found10 improvements, including budget echoes that triggered strict price
replacement, an unsupported comparison promise, unnatural wording, missing known facts and
weak source entailment. Prompt adjustments retained every commercial guard. The later review
observed improvements in eight affected historical cases and six remaining quality issues:
placeholder support destination, incomplete bracketed label, omitted catalog listing,
local-currency uncertainty, correction acknowledgement and redundant support wording.
The last two are minor copy issues. No executed purchase/refund or guaranteed learning outcome
was observed in this finite set; that is not universal safety certification or human review.

These remaining issues motivate prompt `2026-10-12.2`, exact Markdown destination validation,
readable plain-text labels and deterministic guard/history regressions. Subsequent results must
be recorded as another post-adjustment run; the53-query results above remain unchanged.

## Cost and timing limits

Official Standard rates were checked before dispatch: USD0.10 uncached input,0.01 cached input,
0.125 cache-write input and0.50 output per million tokens. Compute cache-write separately instead
of charging it twice as uncached input. See the [official model page](https://developers.openai.com/api/docs/models/gpt-6-luna).
The baseline reported826,574 input /48,450 output /7,443 cached /25,905 reasoning tokens;
220 SDK receipts reported814,746 cache-write tokens. The lost terminal receipt uses its settled,
rounded application cost rather than an invented cache-write count.

The53-query run reported203,454 input /13,213 output /73,935 cached /129,381 cache-write /
7,702 reasoning tokens. Its application ledger rounds each call to microUSD (23,555 total),
which differs slightly from the unrounded SDK estimate. At that stage the usage-derived estimate for both
runs was about USD0.150207; conservative shared accounting was USD0.351214 across267 attempts.
Neither is an invoice. The key could not read account costs (`api.usage.read` missing), so prior
external monthly spend and the administrative project limit remain unverified.

Baseline first-content latency:220 samples, median2.859s, p955.018s. Later provider-only
first-content latency:46 samples, median4.053s, p957.674s. Later total query duration:53 samples,
median5.697s, p9516.313s. These are application HTTP/SSE timings on shared local WSL, not
provider-only latency, VPS capacity or a production SLA; no controlled speed comparison is claimed.

## Reproduction and activation gates

Follow [the socket procedures](../evaluation.md), exact commits/manifests and a new private output
directory. Paid reproduction needs explicit authorization and the existing shared ledger; it is
not part of CI. Never reset the ledger or overwrite an earlier run. Fixture tests remain default.

The storefront remains disabled. Still required: staged native real-model chats; exact deployed
contract>=1.4; HTTPS/CORS/host-only cookies/CSRF; actual proxy SSE/disconnect handling; provider
failure and interruption accounting; physical mobile keyboard/screen-reader checks; backup/restore
and retention/physical erasure; VPS load/headroom/disk; private observability receiver and access
controls; owner acceptance and separate activation. No measured sales-conversion uplift is claimed.


## Final targeted revalidation after normalization fix

Application `05ecae7a6b41cbf4445f0514c0e1d05eb11eb344`, prompt `2026-10-12.2`, uses
`evals/end_to_end_final_quality_revalidation.json`, SHA256
`dc8d90a3f4862e9a051a0874c868f845ba1b4d5a7cbc1bb0717fc1989cda3e96`. The matrix was fixed
before dispatch: six prior cases plus four new variants,14 turns. Thirteen generations and one
local Spanish notice completed; all14 histories and exact per-turn replays matched, with no
additional provider calls, structural/heuristic failures or unknown paid usage.

An independent agent reviewed all14 finals,13 drafts, chips and13 exact evidence receipts. The
six prior observations were resolved in the affected turns: authorized support references without
placeholder Markdown; known listing separated from current checkout; local-currency budget not
promised as sufficient; neutral correction acknowledgement; natural support-time qualifier.
A minor repetition of true format/language information remains a stylistic variation rather than
a reason to purchase another evaluation. No claim of perfect future consistency or conversion
uplift follows from this finite development set.

Before paid execution, root review found that formatting normalization could expose an unchecked
price/action/outcome claim. Commit05ecae7 preserves raw destination checks and rechecks final
normalized content and follow-ups; negative controls cover all three claim types and follow-up
prices. Independent approval of the previous candidate was superseded explicitly. No real call
ran on that intermediate candidate. Its original full check447pass/1subprocess readiness failure
remains recorded; the unchanged readiness gate was not relaxed. Final452tests passed94.46s,
with strict types, Ruff, contract drift, retrieval and fixture safety/guard suites green.

This last run reported60,175 input /4,063 output /21,828 cached /38,308 cache-write /2,310
reasoning tokens; Standard usage estimateUSD0.00704218. Across the three runs:303 HTTP query
turns,280 real generations and23 local notices. Repeated development cases are not counted as
unique independent questions. Estimated totalUSD0.157249; conservative shared accounting
USD0.372239, within the unchanged USD1/400 envelope. Billing and previous external spend remain
unverified. First-content latency13 provider samples: median4.502s, p955.939s; total14 samples:
median5.531s, p959.236s, shared local WSL only.

Exact local image of05ecae7: `sha256:ba395b5cbbb0dead33ea0573b61f2754c3c94c3488795192d1792509c6a45ed6`,
56,671,567bytes, Python3.14.8, UID65532/read-only. Core/backup/restore/private OTLP smokes passed;
active stream with blocked collector stopped17.244s without OOM and retained canceled run plus
unknown-cost reservation before restart. That interruption test used fixtures, not the real
provider. Trivy0.75.0 with vulnerability DB updated2026-10-12T19:08:28Z found71 unique OS CVEs
(164 package rows), including44 high rows and no critical/Python findings; none had a published
fixed version in that database. This is not risk acceptance or production readiness. Application
image and shared infrastructure still require the deployment owner's security review.
