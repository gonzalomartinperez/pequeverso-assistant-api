# Runtime compatibility — 2026-10-17, 17:35 UTC cohort

This increment starts from API `8ba99fe0846e238109cd58a90eeff8ffe79c5789` (release PR69).
It updates application artifacts only. No paid provider request, real credential access,
image publication, VPS deployment or storefront activation is part of this work.
Historical fixture/model reports remain unchanged and describe their original revisions.

## Selected versions and compatibility review

Python uses regular GIL CPython 3.15.0, released stable on 2026-10-09, on official Debian
Trixie slim. The earlier 2026-10-12 missing-tag observation no longer blocks this candidate.
Pequeverso does not depend on Lingua; the portfolio wheel restriction does not apply.
All 52 locked third-party packages had candidate compatible Linux amd64 wheels; frozen
installation, rather than filenames alone, is the acceptance proof. Python and most of these
libraries are supported stable releases, not an invented LTS distribution.

| Component | Previous | Selected | Reviewed effect |
| --- | --- | --- | --- |
| Python | 3.14.8 | 3.15.0 | UTF-8 default, SQLite signature cleanup and removals require independent application regression |
| uv | 0.13.0 | 0.13.1 | Atomic lock/version writes, environment serialization and cache/uninstall fixes |
| Ruff | 0.17.0 | 0.17.1 | Lint/formatter fixes; existing rules remain enabled |
| FastAPI | 0.143.0 | 0.143.3 | Included-route context fix; fallback-file and built-in JSONL/SSE fixes |
| OpenAI SDK | 3.29.0 | 3.33.0 | HTTP/1.1 completion-body draining and generated optional API additions |
| pydantic-settings | 2.15.0 | 2.16.0 | Alias/config loading fixes, dotenv floor and optional settings-source features |

Only the four application/dev package versions shown above change in `uv.lock`. Existing
compatible transitives are retained, including python-dotenv 1.2.3 (already satisfies the new
>=1.2.2 floor). This update does not claim an existing dotenv vulnerability. No graph, vector,
LangChain, language detector or fallback model dependency is introduced.

The SDK already used httpx2 in 3.29; this is not a new transport migration. The public client
configuration and close implementations are unchanged. The relevant streaming change drains
remaining raw HTTP/1.1 bytes after `[DONE]`, bounded by 100 ms, then closes with cancellation
shielding. HTTP/2 closes the stream without draining. The adapter keeps the exact wire
`service_tier="default"`, `store=false`, strict output schema, model `gpt-6-luna`, reasoning
`medium`, token limits, and zero SDK/runtime retries. No new generated tool API is enabled.

The settings adapter uses explicit `.env.local`, canonical field names and no CLI/cloud secret
source. New parent-directory search has depth zero by default. Synthetic regressions verify
UTF-8, environment/file/default precedence, disabled file loading, no parent search, invalid
input redaction and paid-provider opt-in. Existing production/telemetry fail-closed tests remain.

## Verification

The new regressions use the **installed SDK** with `httpx2.MockTransport`, synthetic keys and
synthetic bytes. They exercise request serialization, HTTP/1.1 buffered/indefinite tails,
HTTP/2, cancellation, early EOF, read timeout, caller close and borrowed client ownership.
Additional app-level cases exercise session, CSRF, SSE, persisted history and charged or
conservatively unreported ledger entries. Session restoration does not dispatch another call.
These checks validate transport/application behavior; they do not measure model quality,
conversion, real-provider availability or live token costs.

Clean checkout `0cb9ddcaf24f31b71505cf0cddbc65d7d83aa8f5` passed **754 tests in 86.40 s**
(88.549 s command wall time), including 13 new regressions. Frozen `--no-build` installation
used wheels only; Ruff/format passed all 153 files, strict mypy passed 70 source files, and
lock/export checks passed. Docker also forbids implicit sdist builds with `--no-build`.
Image measurements are recorded separately below after execution. Public
contract 1.5 and private ops 1.2/telemetry 1.0 must remain byte-identical to the source revision;
all 19 manifest/artifact blobs, including the four private schema/example blobs, are checked.
No regenerated contract drift is accepted silently.

## Local candidate image and measured limits

Source `3a2e4da6779da4960d754f61440e25abc7a65b39` built in 39.831 s as local image
`sha256:15dbee1899cbd89984a4ee255b8ccb83c27944674c82dd2116c7c789859c4fb5`
(58,020,026 reported image bytes). It reports Python 3.15.0, UID/GID 65532, GIL enabled,
JIT disabled and normal imports. This is a local identity, not a published registry digest.
Later documentation-only commits have different `SERVICE_REVISION`; their exact-head image
verification must be recorded separately rather than relabelling this image.

The standard smoke passed in 21.963 s: read-only root, health/readiness, session/CSRF/SSE,
private ops authorization, migration version 2, backup/restore of two messages and a charged
ledger. Stop took 1.222 s. Four concurrent fixture turns took 402.54–518.70 ms with a 0.5 CPU
cgroup ceiling; idle memory was 70.01 MiB, cgroup peak 87,961,600 bytes under 256 MiB, no OOM.
These measurements include their fixture workload/shared local host effects. They establish
neither real-model latency, CPU demand nor VPS capacity, and are not directly comparable with
older runs taken under different conditions.

A separate delayed-fixture probe stopped the container while SSE remained open after a delta.
It exited 0 in 5.298 s without OOM, delivered `run.completed` and retained two messages plus a
settled ledger. Its first inspection harness failed because a SQLite WAL reader mounted the
data volume read-only. A same-volume control reproduced that failure; inspection succeeded
with the contractual writable `/data`, read-only root and SQL `mode=ro`. The original harness
and failure were preserved separately; no application code or security gate changed.

Gitleaks 8.30.1 scanned 48 full-history commits / approximately 2.05 MB in 1.89 s with zero
leaks (redacted output). Trivy 0.76.0 downloaded its database on 2026-10-17 at 18:50 UTC;
the database itself is dated **2026-10-16 01:13 UTC**, not an assertion of up-to-the-minute
advisory coverage. The image scan reports zero CRITICAL and zero Python findings, with **164
OS package/advisory rows: 44 HIGH, 58 MEDIUM, 61 LOW and 1 UNKNOWN**. The HIGH rows represent
8 distinct CVE ids, not 44 different CVEs. All findings lack a fixed version in that database.
The CycloneDX SBOM contains 127 components (88 OS + 38 Python packages + image root).
Trivy also warns that third-party SBOM data can be inaccurate; no scan is a complete security
proof. No unfixed findings were filtered and no required library was stripped to lower counts.

The HIGH ids remain explicit deployment-risk review items: CVE-2026-76642,
CVE-2026-78408, CVE-2026-78409, CVE-2026-78410, CVE-2026-54369, CVE-2025-69720,
CVE-2026-16742 and CVE-2026-9538. Recheck the selected release image against current
[Debian security status](https://security-tracker.debian.org/tracker/) and preserve the full
report before publication/activation. This compatibility PR does not silently accept their risk
or claim production readiness.

A later **separate exact-source verification** used commit
`fa99046ad8256e6be13ce9c8de07b521bbd72d07`, local image
`sha256:a0633939339b5a4d8eddf052843a5ac186701e641d76bc45ec32930feff952ba`.
Its cached build took 1.944 s; the hardened smoke/restore passed in 43.416 s, idle stop
1.456 s, active-SSE stop 6.039 s, exit 0/no OOM. Idle memory was 75.64 MiB and cgroup peak
89,296,896 bytes / 256 MiB. Fixture turn durations 586.88–762.31 ms were recorded while local
scan/probes also ran; these are functional smoke observations, not a controlled benchmark.
The full-history redacted scan covered 49 commits / 2.05 MB in 3.85 s, no leaks.

An origin-manifest comparison found the default GCR vulnerability-DB mirror lagging behind
GHCR. The follow-up fetched the **official GHCR origin by immutable digest**
`sha256:10584ede500597f516f0d5f4ab750c125999dc0359995a4494ab6cb12e700730`
into a new isolated cache. That DB is dated **2026-10-17 18:34:28 UTC**, downloaded at 18:54 UTC.
The 9.433-second image scan and 127-component SBOM preserve the same findings: zero CRITICAL,
zero Python, 164 OS package/advisory rows including the same 8 unique HIGH ids, no fixed
versions listed. The earlier mirror report and its timestamp remain preserved, not overwritten.
No scan identifies every possible risk or accepts these findings for production. Exact images
built from subsequent documentation/ancestry commits have their own identities and require
current-head CI; neither local image above is relabelled as a future release artifact.

The fixture conversation evaluation ran 19 scenarios with zero safety failures and 16 guards
with zero failures; its 11 quality flags remain visible and are not live-model quality results.
Retrieval measured recall@3 0.9565 / MRR 0.899 for 23 baseline cases; the 190-case corpus
measured recall@3 **0.689** / MRR **0.603**. These imperfect results are not hidden by passing
process exits. Retrieval code, catalog and evaluation questions are unchanged in this cohort;
this increment does not claim to fix their semantic coverage or run a new paid evaluation.

## Reproduce and operational limits

Use a clean checkout with `.python-version`, uv 0.13.1 and no real `.env.local`:

```sh
uv sync --frozen
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -q
uv run python -m contracts.export --check
uv run python scripts/evaluate_retrieval.py
uv run python scripts/evaluate_conversations.py
scripts/smoke_container.sh
```

The container recipe pins Python and uv manifests listed in the [runtime baseline](../runtime-baseline.md).
Builds/scans happen off-VPS. The exact selected image requires its own scan/SBOM and immutable
release identity; an older image scan is not evidence for this candidate. Health/readiness and
SIGTERM smoke do not demonstrate crash/OOM autorestart or reboot recovery. Capacity, private
routing, secrets delivery, backups and coordinated catalog/history-compatible rollback remain
vps-ops gates. Never restore an old whole SQLite database over intervening messages or ledger
writes. This PR does not deploy, authorize paid calls or enable the storefront assistant.

## Primary sources

- [Python release](https://www.python.org/downloads/release/python-3150/) and [porting notes](https://docs.python.org/3.15/whatsnew/3.15.html#porting-to-python-3-15).
- [uv 0.13.1](https://github.com/astral-sh/uv/releases/tag/0.13.1) and [Ruff 0.17.1](https://github.com/astral-sh/ruff/releases/tag/0.17.1).
- [FastAPI 0.143.1](https://github.com/fastapi/fastapi/releases/tag/0.143.1), [0.143.2](https://github.com/fastapi/fastapi/releases/tag/0.143.2), [0.143.3](https://github.com/fastapi/fastapi/releases/tag/0.143.3).
- [OpenAI cumulative SDK diff](https://github.com/openai/openai-python/compare/v3.29.0...v3.33.0) and [bounded cleanup source](https://github.com/openai/openai-python/blob/v3.33.0/src/openai/_streaming_cleanup.py).
- [OpenAI Responses request reference](https://developers.openai.com/api/reference/resources/responses/methods/create) and [reasoning guide](https://developers.openai.com/api/docs/guides/reasoning). The request explicitly preserves `store=false`; omitting it would use the provider default rather than our policy.
- [pydantic-settings 2.16.0](https://github.com/pydantic/pydantic-settings/releases/tag/v2.16.0).
- [Official Python image recipe](https://github.com/docker-library/python/tree/ce73ea7cebf01824125c30c20cd1acbde9b364ec/3.15/slim-trixie).

Portfolio commit `b6ed7577ee65a4e6533b48f8379b00a442e70eae` was read with `git show` for review
patterns only. Its package/runtime tests are not presented as Pequeverso results.
