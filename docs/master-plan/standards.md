# Standards — pequeverso-assistant-api

Style guide choice: **PEP 8 enforced by `ruff format`, plus the Google Python Style Guide docstring convention**, exactly as ecosystem 10.2 (`research/10-standards-dependencies.md` topic A, `research/02-python-architecture.md` section 5). Only deviations and enforcement are listed here.

## 1. Rules adopted

| Topic | Standard for this repo | Today |
|---|---|---|
| Formatter | `ruff format`, line length 100, double quotes | line 110, single quotes; 204 of 225 files would change |
| Lint families | `E W F I B C4 UP SIM RUF PERF PIE PT PTH TC ASYNC S T20 TRY ARG FAST LOG G DTZ ERA FURB N RET D ANN`, never `ALL`; ignore `E501 TRY003 D203 D213` | `I N UP B S SIM RUF ASYNC PT` |
| Types | `mypy --strict` serial gate; Pyrefly non-blocking second job; `ty` editor only; hints on every function | strict, 0 errors on 123 files |
| Python | `requires-python >= 3.14`, `uv sync --locked`, `exclude-newer = "7 days"`; 3.15 non-blocking CI job | `>=3.14,<3.15`, `--frozen` |
| Complexity | ≤ 10 per function, ratcheted (`ratchets/complexity.json`) | 19 functions above 10, max 36 |
| Dead code | vulture, empty allowlist target | not run |
| Errors and logs | problem responses (v1 envelope kept, PVA-D6); allowlist JSON logs; no `datetime.now()` outside the `Clock` port | 4 `datetime.now`, 3 outside bootstrap |
| Imports | absolute imports from `app.`; relative imports allowed inside a package (ecosystem deviation from Google) | all absolute (0 relative found) |
| Suppressions | `# noqa` or `# type: ignore` only with a rule code, a reason and an issue when not obviously local | 36 `noqa` (reasons mostly present), 0 `type: ignore`; 27 are now unused (RUF100) |
| Commits and PRs | Conventional Commits; PR title is a Conventional Commit (checked); merge commit into develop (no squash) | already Conventional |

## 2. Deviations from the ecosystem standard (justified)

| # | Deviation | Why | Enforcement |
|---|---|---|---|
| S1 | Flat `app/` package, no `src/` (PVA-D2) | deployable service; import churn across 225 Python files; Docker and `vps-ops` contract name `app.*` | ADR-0012; architecture guard |
| S2 | Docstring rules `D100` to `D107` enforced only for `app/application/ports.py`, `knowledge_ports.py`, `app/presentation` (public API) and `contracts/`; ignored elsewhere | 751 missing-docstring findings, mostly on small, typed, self-describing internals; Google's guide asks docstrings for public API, comments explain why | ruff per-file ignores; count ratchet for the enforced scope; D2xx and D4xx style rules always on |
| S3 | `scripts/**` ignore `T201`, `S603`, `S607`, `E402` | they are CLIs: `print` is the output channel; subprocess calls are fixed command lists; `sys.path` bootstrap for `python scripts/x.py` | per-file ignores with comment |
| S4 | Tests ignore `S101 ANN D ARG` (ecosystem) and also `S105 S106 PT018` (existing) | fixtures contain synthetic secrets; `assert` is the test idiom | per-file ignores |
| S5 | Line length 100 (Google says 80) | ecosystem-wide choice | formatter |
| S6 | Three TypeScript files (`tools/catalog/*`, one `tests/js` file) outside the Python toolchain; no Biome, no `package.json` | three files do not justify a second toolchain; the exporter imports storefront modules that do not exist here | `node --test` and Node type stripping in CI; listed in `target-state.md` section 7 |
| S7 | Keep the in-house allowlist log formatter instead of structlog | enforces per-logger event and field schemas (a stronger guarantee than structlog's processors) | `tests/test_observability.py`; ADR-0014 |
| S8 | Error envelope is not RFC 9457 in v1 | a wire change is breaking; mapping documented | contract tests; ADR-0013 |

## 3. Enforcement (ecosystem 10.3)

- One command equals the CI static job and the pre-commit hook: `just check` (new `justfile`) running `ruff check`, `ruff format --check`, `mypy`, `lint-imports`, `vulture`, the complexity ratchet, `pytest -m unit -q`, `python -m contracts.export --check` and `python -m scripts.validate_skills`. AGENTS.md lists exactly this command; a test greps the backticked commands in AGENTS.md against the `justfile`.
- Ratchet files in `ratchets/` (`complexity.json`, `coverage.json`, `mutation.json`, `retrieval.json`, `golden.json`, `image.json`, `ruff.json`, `docs.json`) only move in the tightening direction; loosening needs an ADR and the owner.
- Mechanical migration plan: one PR runs `ruff format` at 100 columns and double quotes and nothing else; its SHA goes into `.git-blame-ignore-revs`; no other PR is open during it. A second PR applies safe autofixes (48 fixable findings). A third fixes the remainder by family, smallest family first.
- New code must not add findings; legacy findings live in `ratchets/ruff.json` per rule code until each reaches zero.
