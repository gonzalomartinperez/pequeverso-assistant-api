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

Exact candidate results and image measurements are recorded below after execution. Public
contract 1.5 and private ops 1.2/telemetry 1.0 must remain byte-identical to the source revision;
all 19 manifest/artifact blobs, including the four private schema/example blobs, are checked.
No regenerated contract drift is accepted silently.

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
- [pydantic-settings 2.16.0](https://github.com/pydantic/pydantic-settings/releases/tag/v2.16.0).
- [Official Python image recipe](https://github.com/docker-library/python/tree/ce73ea7cebf01824125c30c20cd1acbde9b364ec/3.15/slim-trixie).

Portfolio commit `b6ed7577ee65a4e6533b48f8379b00a442e70eae` was read with `git show` for review
patterns only. Its package/runtime tests are not presented as Pequeverso results.
