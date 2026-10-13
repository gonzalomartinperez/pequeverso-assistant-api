# Post-tool verification — 2026-10-13

This record separates deterministic commercial-boundary verification, exact local images and
post-change real-model evaluation. A completed request, approved CI or local screenshot does
not establish a correct commercial answer or production readiness. The storefront assistant
remains disabled. No image is published or deployed by these checks.

## Frozen application and commercial evidence

The protected integration of [PR50](https://github.com/gonzalomartinperez/pequeverso-assistant-api/pull/50)
is `bfb3588d5cf6313eedd675eb1e6db75398108ce5`. It includes optional bounded Hotmart evidence,
validated streaming prefixes and the merchant guarantee correction. The final fixture/image
candidate is its reviewed feature commit `6afb5f380303847b26cabfcf424e07ddc344e177`.
The original [303-query evidence](real-model-2026-10-12.md) predates this capability and retains
its original code, catalog, answers and costs; it cannot validate the later tools.

Catalog SHA256 `38b6fab76cb72f41a8284fcf51a11b716ddb82f87d72b0006beae84896234fe7` was
exported from storefront main `18b68692867ddd379a3e30130a473dcb7e8a355b`, generated at
2026-10-13T05:09:16+00:00. It contains one core product, nine resources,23 documents and six links.
Commercial fields are identical to the preceding kit snapshot; only provenance and verification
time changed. Git provenance is not checkout verification or live stock.

**Coverage:** Grafismo Fonético and approved general Hotmart procedures. The home affiliate
video course is absent because its registry is not exported, not because an exclusion was
approved. Its unknown price, video/PDF schema differences, producer policies and health claims
require a separate authorized increment. See [catalog coverage](../catalog.md#current-coverage-2026-10-13).

The frozen post-tool development matrix has 258 queries in 238 cases. Questions and expected
outcomes did not enter the public catalog or retrieval cache. Its metadata-only catalog refresh
preserves the original parent manifest. This is development revalidation, not an independent
holdout or 258 unique independent questions. Real-run outcome and semantic review are recorded
only after reviewed public evidence is available; no completion or correctness is asserted here.

## Defects and deterministic regressions

| Confirmed defect | Correction | Evidence and limits |
| --- | --- | --- |
| A false $999 price reached raw SSE deltas before final replacement | PR49: normalize and validate cumulative complete sentence/paragraph prefixes before emitting; terminal remainder only from the accepted canonical final | Character-split prices, decimals, markup, unsafe actions/outcomes, actual progressive HTTP/SSE, history and replay regressions. Earlier valid prefixes may still precede a later terminal replacement; these are bounded recognizers, not general semantic proof |
| The new terminal-tail suspension could lose known usage or accept completion after cancellation/deadline | PR49: settle known usage before that yield; check cancellation/deadline on both sides | Close/cancel/timeout regressions preserve accounting and prevent partial assistant persistence. Unknown usage retains its reservation |
| An unsupported 30-day guarantee passed when web evidence was absent | PR50: apply the same catalog policy guard in every source mode; distinguish positive reminders from denials | 24 HTTP/SSE cases exercise disabled/unavailable/selected evidence, false 30-day windows, genuine denials, published 7-day window and general procedures |

Final source 6afb passed 599 tests in 70.81 s, strict mypy, Ruff, formatting and unchanged contract
export. Canonical fixtures: 17 scenarios, 12 guards, zero safety/guard failures and seven synthetic
quality failures. Fixture quality scores do not measure GPT-6 Luna. The independent agent peer
review approved the frozen source; this is not human review. Original failure receipts remain
outside Git, including the original leaked-price/catalog-only gap and an unsuccessful unpublished
regex-escape draft. Gates and historical evaluation cases were not weakened or rewritten.

[PR50 CI run 38373077751](https://github.com/gonzalomartinperez/pequeverso-assistant-api/actions/runs/38373077751)
passed on exact head 6afb: lint/types/tests/contracts/evaluations 84 s, container build/smoke 34 s,
workflow lint 17 s, full-history secret scan 13 s and aggregate gate 2 s. Durations overlap; they
are job durations, not a claimed sum or a controlled performance comparison.

## Exact local image and security inventory

Image `sha256:76b5bcd440d43628276bb12efd1358a9ede4c7a2276cf38c394c8d402839141b` was built
from 6afb, not the squash integration bfb or a future release. Docker metadata size 56,831,248 bytes;
UID 65532:65532, read-only root. Session/CSRF/Origin/HTTP/SSE/private operations, backup restoration
with retained history and charged ledger, four concurrent fixture streams and graceful stop
passed. Cgroup peak 83,767,296 bytes under 256 MiB; core stop 1.954 s, no OOM. These are local
fixture measurements, not VPS capacity or live-provider container load.

The active-SSE/blocked-collector lifecycle probe used an earlier separately identified image;
its 7.508 s stop is not attributed to this digest. See the [deployment evidence](../deployment-contract.md#verified-commercial-guard-candidate-on-2026-10-13).

Offline Trivy 0.75.0, database updated 2026-10-12T19:08:28Z: 164 OS package rows / 71 unique CVEs,
44 HIGH, 0 critical and 0 Python findings; 126 CycloneDX components. No published fixed versions
were reported in that database. No production risk acceptance follows. The host and separately
selected PostgreSQL/shared services still need deployment-owner security review.

## Tool and budget boundaries

Only three server-selected public Hotmart procedure articles may be fetched. The model receives
bounded untrusted evidence, not a browsing capability, buyer-account access or transaction tool.
The reader is disabled by default and never instantiated for fixtures; it sends no visitor text,
credentials or arbitrary query. General platform procedures cannot change merchant facts.
The undocumented endpoint, source freshness and unpinned trusted fixed-host DNS residual remain
explicit [source/egress limits](../official-web-evidence.md).

The real evaluator retains the existing shared USD1 envelope and previous counts/costs.
Default attempt cap 400 remains; owner-authorized explicit 650 accumulated attempts is persisted
immutably for this later phase, with no increase to the USD cap or monthly authorization.
Unknown-cost attempts are never treated as free. One GPT-6 Luna medium generation per accepted
turn, no substitute model or automatic retry. Tokens include selected external evidence.

API `first_delta_ms` describes the first emitted checked fragment; final-only replacement can
legitimately report null. The evaluator preserves historical `first_content_seconds` as delta
receipt and separately measures `first_visible_content_seconds` from a nonempty delta or
`message.completed`. Neither is browser paint, provider-only timing or a production SLA.

## Remaining activation gates

Keep the storefront disabled until separate owner authorization after deployed-backend acceptance.
Required: exact selected release image/digest and compatible contract; HTTPS, host-only cookies,
CORS/CSRF and actual proxy SSE/cancel/disconnect; isolated OAuth/backoffice access; real VPS
resource/disk/headroom and source egress checks; encrypted backups and effective restore;
retention/physical erasure; provider failure/accounting and reviewed real-model commercial quality;
physical keyboard/screen-reader/mobile checks. No measured sales-conversion uplift is claimed.
