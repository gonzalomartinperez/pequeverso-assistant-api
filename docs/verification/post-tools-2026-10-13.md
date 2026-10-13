# Post-tool verification — 2026-10-13

This record separates deterministic commercial-boundary verification, exact local images and
post-change real-model evaluation. A completed request, approved CI or local screenshot does
not establish a correct commercial answer or production readiness. The storefront assistant
remains disabled. No image is published or deployed by these checks.

## Frozen application and commercial evidence

The protected integration of [PR50](https://github.com/gonzalomartinperez/pequeverso-assistant-api/pull/50)
is `bfb3588d5cf6313eedd675eb1e6db75398108ce5`. It includes optional bounded Hotmart evidence,
validated streaming prefixes and the merchant guarantee correction. Its first reviewed fixture/image
candidate was feature commit `6afb5f380303847b26cabfcf424e07ddc344e177`; subsequent candidates
are identified separately below.
The original [303-query evidence](real-model-2026-10-12.md) predates this capability and retains
its original code, catalog, answers and costs; it cannot validate the later tools.

Catalog SHA256 `38b6fab76cb72f41a8284fcf51a11b716ddb82f87d72b0006beae84896234fe7` was
exported from storefront main `18b68692867ddd379a3e30130a473dcb7e8a355b`, generated at
2026-10-13T05:09:16+00:00. It contains one core product, nine resources, 23 documents and six links.
Commercial fields are identical to the preceding kit snapshot; only provenance and verification
time changed. Git provenance is not checkout verification or live stock.

**Coverage:** Grafismo Fonético and approved general Hotmart procedures. The home affiliate
video course is absent because its registry is not exported, not because an exclusion was
approved. Its unknown price, video/PDF schema differences, producer policies and health claims
require a separate authorized increment. See [catalog coverage](../catalog.md#current-coverage-2026-10-13).

The frozen post-tool development matrix has 258 queries in 238 cases. Questions and expected
outcomes did not enter the public catalog or retrieval cache. Its metadata-only catalog refresh
preserves the original parent manifest. This is development revalidation, not an independent
holdout or 258 unique independent questions. The initial phase stopped after 203 requests; 55 original requests remained unattempted.
The original answers, manifest, gate failure and accounting remain immutable. Later phases are
identified as development revalidation after corrections, not independent holdouts.

## Defects and deterministic regressions

| Confirmed defect | Correction | Evidence and limits |
| --- | --- | --- |
| A false $999 price reached raw SSE deltas before final replacement | PR49: normalize and validate cumulative complete sentence/paragraph prefixes before emitting; terminal remainder only from the accepted canonical final | Character-split prices, decimals, markup, unsafe actions/outcomes, actual progressive HTTP/SSE, history and replay regressions. Earlier valid prefixes may still precede a later terminal replacement; these are bounded recognizers, not general semantic proof |
| The new terminal-tail suspension could lose known usage or accept completion after cancellation/deadline | PR49: settle known usage before that yield; check cancellation/deadline on both sides | Close/cancel/timeout regressions preserve accounting and prevent partial assistant persistence. Unknown usage retains its reservation |
| An unsupported 30-day guarantee passed when web evidence was absent | PR50: apply the same catalog policy guard in every source mode; distinguish positive reminders from denials | 24 HTTP/SSE cases exercise disabled/unavailable/selected evidence, false 30-day windows, genuine denials, published 7-day window and general procedures |

Historical source 6afb passed 599 tests in 70.81 s, strict mypy, Ruff, formatting and unchanged contract
export. Canonical fixtures: 17 scenarios, 12 guards, zero safety/guard failures and seven synthetic
quality failures. Fixture quality scores do not measure GPT-6 Luna. The independent agent peer
review approved the frozen source; this is not human review. Original failure receipts remain
outside Git, including the original leaked-price/catalog-only gap and an unsuccessful unpublished
regex-escape draft. Gates and historical evaluation cases were not weakened or rewritten.

[PR50 CI run 38373077751](https://github.com/gonzalomartinperez/pequeverso-assistant-api/actions/runs/38373077751)
passed on exact head 6afb: lint/types/tests/contracts/evaluations 84 s, container build/smoke 34 s,
workflow lint 17 s, full-history secret scan 13 s and aggregate gate 2 s. Durations overlap; they
are job durations, not a claimed sum or a controlled performance comparison.

## Real-model phases and observed limits

| Phase | Frozen source | Requests and provider use | Outcome |
| --- | --- | --- | --- |
| Initial post-tool matrix | `bfb3588d5cf6313eedd675eb1e6db75398108ce5`, prompt 13.1 | 203 attempted: 194 provider answers, eight local answers, one pre-provider HTTP422 | Legitimate third-turn follow-up exceeded the unchanged 24KB input bound; execution stopped at the case gate. No external article actually reached a generation |
| Post-adjustment development phase | `110535fcdca009df4b63be4cd30eacfde20d8a4c`, prompt 13.2 | 74 requests: 62 provider, 12 local | All HTTP/SSE/history/replay checks passed. Independent agent semantic review: 66 supported, five minor issues, one low-utility safe abstention, one visible citation marker and one unnecessary language-generation dispatch |
| Final targeted phase | `47bcf309a85f823d389f5b777e9b33e31b34b937`, prompt 13.2 | Seven requests: four provider, three local | Zero HTTP/history/replay/structural/behavior flags. Independent agent review: six supported, one supported with a material-language inference observation; no new proven false commercial fact or serious defect |

The 74 cases include the 55 unattempted initial requests and 19 affected/new development
variants. Original comparison counts, maximum-delay wording, explicit French request and
follow-up HTTP422 were corrected in these cases. The remaining switch-command and citation
marker findings motivated the finite final patch. The seven targeted regressions then confirmed
three local foreign-language refusals without provider dispatch and four useful Spanish responses
without visible citation-control markers. They do not prove all stochastic future responses. None of these runs establishes a perfect
commercial assistant, a human review or measured conversion improvement.

Twelve post-adjustment turns actually included official external evidence. Effective article
excerpts were introductory prefixes of 130/170/199 characters, not complete articles or complete
refund/access procedures. Retrieval availability, citation validity and full claim support are
separate concerns. One refund/guarantee response abstained safely with limited usefulness. The final seven retain
one observation: Spanish material language is inferred because the catalog lacks an explicit
PDF-language field. A 130-character external refund introduction supports the window
prerequisite, not a full procedural article. Independent coding-agent review read answers and
recorded evidence; it did not perform human review or independent HTTP history requests.

Initial-phase Standard-price estimate: USD0.094784335; post-adjustment estimate:
USD0.032125560. These token-based estimates are not invoices. The final seven cost an estimated USD0.002265685 at Standard token prices. The accumulated
Standard estimate across the shared evaluation work is USD0.288041380, not an invoice. The
conservative ledger after the final phase retains 542 attempts, 792,292 microUSD and zero
unknown-cost attempts, under the unchanged USD1/650-attempt authorization. It includes earlier
development work; phase estimates must not be presented as the whole accumulated ledger.

The final phase manifest SHA256 is
`fbb6d26cfd045156bf90aeb9de203b2d9a0ac1420b1735d9ac75b99c5aaafc72`;
its reviewed response-pack SHA256 is
`2620115eddaab7d98159112695ac035cea9c4c60a1c37178282fb4faed11010d`.
The preceding 74-case manifest remains
`4e22a82d82b84b887e8363724498f97aa2c5962092dd7e16776e7a05015f3ee1`.
Private complete answers, prompts and keys are not published. Local reviewed receipts retain
per-case terminal, provider/local use, latency, selected evidence, citations, history/replay and
usage metadata; the public record publishes only reviewed non-personal summaries.

Initial-source local HTTP timing remains historical, not a speed comparison with corrected code:

| Receipt metric | Samples | Median | Nearest-rank p95 |
| --- | ---: | ---: | ---: |
| First received checked delta | 194 | 3.248 s | 5.881 s |
| First visible delta or authoritative final | 202 | 3.202 s | 5.692 s |
| Total request duration, including the pre-provider failure | 203 | 3.989 s | 7.187 s |

These shared-WSL client measurements are neither browser paint nor provider-only timing or a
production SLA. The initial phase recorded 921,990 input tokens and 48,191 output tokens;
27,618 reasoning tokens are included in provider usage, not added as a separate generation.

## Later corrections and exact combined validation

[PR51](https://github.com/gonzalomartinperez/pequeverso-assistant-api/pull/51) adds bounded explicit resource page-count checks, exact-budget context packing and the
French/max-delay corrections. All structured resources/products and mandatory commercial
policies remain present. Only low-ranked optional passages and old model-context text are
pruned; persisted history remains intact. Optional external evidence uses complete paragraph
prefixes with effective text hashes. Only actually selected evidence IDs may become citations.
The unchanged 24KB input limit and protocol margin still fail safely when mandatory content
cannot fit; no second generation, fallback or retry was added.

[PR53](https://github.com/gonzalomartinperez/pequeverso-assistant-api/pull/53) recognizes anchored "switch to" language requests and removes bounded complete provider
citation syntax after raw validation, preserving whitespace and structured sources. Malformed
citation residue stops provisional output and safely replaces the answer. Raw and normalized
commercial/URL/page checks remain active. Quotes, negation, material-language questions and
legacy ES/EN compatibility remain covered. These are finite recognizers, not general semantic
or language-policy proof.

After a normal merge of independently reviewed runtime/dependency PR52, exact combined
candidate `cf19c3beac8e51bcb4ed805af7d92a99c42f8ce6` passed 667 tests in 113.98 s, Ruff,
formatting of 148 files, strict mypy of 70 source files and unchanged contract export.
Canonical fixtures: 19 scenarios and 14 guard cases, zero safety/guard failures and eight
synthetic quality flags. Fixture quality flags do not measure GPT-6 Luna. Historical negative
controls, images and paid results remain separate and unchanged. Its protected squash integration
is `47bcf309a85f823d389f5b777e9b33e31b34b937`, the source of the final real-model phase;
FastAPI 0.143.0, OpenAI SDK 3.29.0 and Pydantic 2.14.1 were actually used there.

[PR53 CI run 38385929510](https://github.com/gonzalomartinperez/pequeverso-assistant-api/actions/runs/38385929510)
passed on the combined head: lint/types/tests/contracts/evaluations 82 s, container 39 s,
workflow lint 21 s, full-history secret scan 11 s and aggregate gate 2 s. Job durations overlap;
they are not a sum or a controlled performance comparison.

## Exact local image and security inventory

Combined candidate image
`sha256:0691367b0a86087d2fc0904f7507e16aa77d8599d6bcd8b953343fc5472cde8d`
was built locally with verified official Buildx 0.38.0 and the existing Docker driver, without
publishing an image, creating a builder or copying credentials. Docker metadata size:
57,024,366 bytes. Inspected SERVICE_REVISION equals the combined cf19 source; UID 65532:65532.
Read-only root, health/readiness, session/CSRF/Origin/HTTP/SSE/private operations, backup/restore
retaining two messages and the charged ledger, four concurrent fixture streams and graceful
stop passed. Cgroup peak 89,403,392 bytes under 256 MiB; core stop 2.02 s; no OOM. These local
fixtures do not prove VPS capacity, real-provider container load or proxy behavior.

Earlier images 76/e783/872 correspond to their earlier source commits and are not relabeled
as this candidate. The active-SSE/blocked-collector probe used its separately identified earlier
image; its 7.508 s stop is not attributed to this digest. See the deployment evidence.
The exact combined image offline Trivy scan used the database updated 2026-10-12T19:08:28Z:
164 OS rows, 71 unique CVEs, 44 HIGH, zero critical and zero Python findings; 126 CycloneDX
components. No published fixes were reported in that database. Historical candidate scans remain
separate. No production risk acceptance follows.
The host and PostgreSQL/shared services still require deployment-owner security review.

## Tool and budget boundaries

Only three server-selected public Hotmart procedure articles may be fetched. The model receives
bounded untrusted evidence, not browsing, buyer-account access or a transaction tool. The reader
is disabled by default and never instantiated for fixtures; it sends no visitor text, credentials
or arbitrary query. General platform procedures cannot change merchant facts. The undocumented
endpoint, source freshness and unpinned trusted fixed-host DNS residual remain explicit
[source/egress limits](../official-web-evidence.md).

The evaluator preserves the existing shared USD1 envelope and previous counts/costs. Default
attempt cap 400 remains; explicit owner-authorized 650 is immutable for this later phase, without
increasing the USD cap or monthly authorization. The repaired case gate is acknowledged only
through a separate audited manual action; original status, rows and accounting remain intact.
Unknown-cost, provider, authentication and budget stops remain blocking. No automatic retry.
One GPT-6 Luna medium generation per accepted turn; selected evidence counts toward input.

API `first_delta_ms` measures the first emitted checked fragment; final-only replacement may
legitimately report null. The evaluator retains historical `first_content_seconds` as delta
receipt and separately measures `first_visible_content_seconds` from a nonempty delta or
`message.completed`. Neither is browser paint, provider-only timing or a production SLA.

## Remaining activation gates

Keep the storefront disabled until separate owner authorization after deployed-backend acceptance.
Required: exact release image/digest and compatible contract; HTTPS, host-only cookies, CORS/CSRF
and actual proxy SSE/cancel/disconnect; isolated backoffice access; real VPS resource/disk/headroom
and source egress checks; encrypted backups and effective restore; retention/physical erasure;
provider failure/accounting and reviewed real-model commercial quality; physical keyboard,
screen-reader and mobile checks. Affiliate catalog coverage remains a separately scoped gap.
