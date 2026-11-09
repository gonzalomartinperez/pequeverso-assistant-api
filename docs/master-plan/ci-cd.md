# CI/CD — pequeverso-assistant-api

Applies ecosystem sections 5 (Dependabot), 6 (CI), 7 (supply chain), 8 (containers), 3.2 (release). Research: `research/05-cicd-supply-chain.md`, `research/11-containers-dynamic-ci.md`. Draft path map: `ci-profile.json`.

## 1. Where the repo stands

| Item | Today | Evidence |
|---|---|---|
| Workflows | `quality.yml` (jobs `workflows`, `secrets`, `static`, `database`, `container`, aggregate `checks`) and `dependency-policy.yml` (`pull_request_target` read-only classifier with a zizmor ignore) | `.github/workflows/` |
| Hardening already in place | `permissions: {}` at top, per-job grants; every action pinned by SHA with version comment; actionlint and zizmor; gitleaks on full history; `scripts/ci_identity.py` binds source and config; concurrency group; timeouts | `quality.yml` |
| Gaps against ecosystem | not dynamic (every PR runs everything); no coverage, diff coverage, mutation, contract diff, fuzz, load; no CodeQL, Scorecard, dependency-review, SBOM, provenance; required check named `checks` not `ci-gate`; no release automation; no weekly guard; Dependabot rule violated | `audit.md` P1-2, P1-5 |

## 2. Profiles and path map (ecosystem 6.0)

`ci.yml` is the single entry point. A `classify` job (≤ 30 s, stdlib script from `engineering-standards`, no third-party action) reads changed files, branch and labels, matches them against `ci-profile.json` and emits the profile; downstream jobs are conditional on it. `ci-gate` (`if: always()`, needs every job) passes only if all results are `success` or `skipped`-by-profile and fails on failure or cancellation. Unknown files and diff errors run everything.

| Profile | This repo's trigger | Runs | Budget p50 |
|---|---|---|---|
| `docs` | only Markdown, `docs/**`, skills, templates | markdownlint, lychee, skills validator, README heading check, secret scan | ≤ 2 min |
| `code` (default) | `app`, `tests`, `scripts`, `evals`, `tools`, `catalog`, `migrations`, lock files | static (ruff, mypy, import-linter, vulture, complexity ratchet), unit with xdist and coverage, `database` if adapters, migrations or contracts of persistence changed, incremental mutmut on changed files, security | ≤ 5 min (p95 ≤ 10) |
| `contract` | `contracts/**` | code plus oasdiff, Schemathesis (50 examples), consumer-compile job; breaking change needs label `contract-major` | code + 2 min |
| `assistant-quality` | prompts, answer policy, language, evidence, catalog, evals, graders | code plus golden replay at 100%, red-team pack, full set (fixture lane) against the committed baseline; live run is a manual dispatch | code + 3 min |
| `workflow` | `.github/**` | actionlint, zizmor (regular persona, online audits), SHA-pin policy, dry-run of a changed reusable workflow | ≤ 3 min |
| `deps-weekly` | head branch `dependabot/**` | full code profile, dependency-review, licence check, SBOM diff, lockfile lint, image rebuild and Grype scan | full + 3 min |
| `release` | PR `develop` to `main` | everything, full mutation or a green nightly ≤ 24 h old, Schemathesis 500, short load run, image build with SBOM and provenance and verification, changelog check, a committed golden live report for the release SHA | ≤ 45 min |
| `hotfix` | `hotfix/*` to `main` with owner label | code plus image verification; auto back-merge PR to develop | ≤ code |

Optimizations: concurrency per ref with cancel for PRs only; `setup-uv` cache keyed on `uv.lock`; `pytest-xdist` first (serial suite is 249 s), sharding only if still over budget; Docker buildx with `type=gha` cache scoped per image (small repo; three images: app, postgres, neo4j fixtures); PostgreSQL and Neo4j fixture images rebuilt only when `infra/docker/**` changes; artifacts handed between jobs (coverage data, built image tar for scan and smoke in the same run). Path map lives in one `ci-profile.json` guarded by `tests/test_ci_profile.py` (no tracked file may fall outside every group).

## 3. Job graph

```
classify ─┬─> static ─────────────┐
          ├─> unit (xdist, cov) ──┼─> coverage-combine ─> diff-cover
          ├─> database (PG18+pgvector, Neo4j 5.26) ─┘
          ├─> contract (oasdiff, schemathesis)
          ├─> assistant-quality (golden replay, red team, full vs baseline)
          ├─> security (zizmor, gitleaks, osv, dependency-review, CodeQL)
          └─> container (build once, structure test, smoke, Grype, SBOM) ─> attest (release only)
                                                             all ─> ci-gate
```

Mapping from today: `workflows` becomes the `workflow` profile jobs; `secrets` joins `security`; `static` splits into `static` and `unit`; `database` and `container` keep their logic (their probes are product-specific and stay in this repo, `docs/ci.md`); `checks` becomes `ci-gate`.

## 4. Rulesets and the rename of the required check

Rulesets are applied by the idempotent `engineering-standards/scripts/apply-rulesets.sh` (user namespace has no org rulesets): PR required, strict `ci-gate`, no force push or deletion, no bypass actors, tag ruleset for `v*`. Transition without `--admin` and without weakening protection: (1) merge the PR that adds a `ci-gate` job beside `checks`; (2) after one green run on develop, owner runs the ruleset script that requires `ci-gate`; (3) a follow-up PR removes the `checks` job. Both branches (`main`, `develop`) stay protected throughout (decision PVA-D11).

## 5. Dependabot: weekly single PR (ecosystem 5)

Target `.github/dependabot.yml`:

```yaml
version: 2
multi-ecosystem-groups:
  weekly:
    schedule:
      interval: weekly
      day: monday
      time: "09:00"
      timezone: America/Argentina/Buenos_Aires
    target-branch: develop
    labels: [dependencies]
    commit-message:
      prefix: "build(deps)"
updates:
  - package-ecosystem: uv
    directory: /
    multi-ecosystem-group: weekly
    patterns: ["*"]
    open-pull-requests-limit: 1
    cooldown: {default-days: 7, semver-major-days: 14, semver-patch-days: 3}
  - package-ecosystem: github-actions
    directory: /
    multi-ecosystem-group: weekly
    patterns: ["*"]
    open-pull-requests-limit: 1
    cooldown: {default-days: 7}
  - package-ecosystem: docker
    directories: [/infra/docker/app, /infra/docker/postgres, /infra/docker/neo4j]
    multi-ecosystem-group: weekly
    patterns: ["*"]
    open-pull-requests-limit: 1
    cooldown: {default-days: 7}
    ignore:
      - dependency-name: python
        update-types: ["version-update:semver-major", "version-update:semver-minor"]
```

The `ignore` on the Python image keeps 3.14.x until the fleet policy moves (ecosystem 8.1: adopt 3.15 around 3.15.3 to 3.15.4); today a stale branch proposes `python-3.15.0-slim-trixie`. Unverified points 5.4 (grouped PR updates in place, day and timezone honoured, uv and Actions accepted, cooldown inside groups) are proven first on the sandbox repo in M1; the repo-specific proof is that the first real run opens exactly one PR. Repository setting: Dependabot security updates **off**, alerts **on** (owner action, PVA-D9).

`deps-weekly-guard` (shared workflow, Monday 10:30 ART and on Dependabot PR events): at most one open Dependabot PR; older ones closed with a pointer; survivor rebased or recreated; red CI opens a tracking issue and labels `needs-fix`; also fails if a pinned base-image digest is older than 30 days.

Retirement: `dependency-policy.yml`, `scripts/dependabot_policy.py`, `.github/dependabot-policy.json`, `tests/test_dependabot_policy.py` and the eligibility text of `docs/dependency-updates.md` are deleted in the same PR (750 lines: 47 + 379 + 8 + 316); the owner merges the one weekly PR manually, so a per-PR classifier adds no decision and removes a `pull_request_target` workflow (PVA-D9).

### P0 path (certifi)

| Step | Date | Rule |
|---|---|---|
| Advisory read and reachability noted | M1 first task | GHSA-6q48-6c7w-9gw2, CRITICAL; fixed in certifi 2026.10.18; nothing deployed |
| New `dependabot.yml` merged | before Monday 2026-11-16 | the 8 old `dependabot/*` branches are closed with a comment pointing to the weekly PR |
| Default: manual PR `fix/deps-certifi` bumping only certifi to `2026.10.18` | opened by 2026-11-11, merged by 2026-11-13 | SLA: critical, internet-facing API: 7 days from 2026-11-09 (ends 2026-11-16); does not create a Dependabot PR (ecosystem 5.5 manual path) |
| First weekly PR | Monday 2026-11-16 09:00 ART | exactly one PR; if the manual PR slipped, certifi rides it and the SLA ends the same day |

## 6. Vulnerability policy applied to the measured findings

| Finding | Class | Policy (ecosystem 5.5) | Action |
|---|---|---|---|
| certifi CRITICAL | Python dependency | critical: 7 days | section 5 |
| 47 base-OS HIGH without fixed version | base image | High, base image: next rebuild | Grype config ignores with expiry 90 days and an issue each; the weekly base-digest bump re-evaluates |
| 4 base-OS findings with a fix | base image | High, fixable: 30 days | picked by the weekly digest bump; the hand-pinned `liblzma5=5.8.1-1+deb13u2` line is removed as soon as the base digest contains it (CI check: apt line must still be needed) |
| Owner note of 2026-10-19 (image CVEs advisory, non-blocking for deployment) | policy conflict | ecosystem SLA is stricter | ADR-0016 records that the ecosystem SLA governs; the note is superseded (owner confirms, PVA-D9) |

Daily `osv-scanner` job and Dependabot alerts notify through an issue labelled `vuln`; no PR is opened by the job. Weekly Grype on the digests in `releases/production.lock` (owned by `vps-ops`) once images exist.

## 7. Security hardening and supply chain

Already met: SHA-pinned actions, least-privilege tokens, zizmor, gitleaks, persist-credentials false. Added:

| Control | Standard | Milestone |
|---|---|---|
| CodeQL | default setup for `python` and `actions` (public repo, free) | M1 |
| Scorecard | weekly with SARIF; fail if the score drops by more than 1 point | M1 |
| Dependency review | `dependency-review-action` on PRs | M1 |
| osv-scanner | daily scheduled, plus PR mode | M1 |
| Secret scanning and push protection | GitHub settings verified on; secret-serialization audit of `repr`, `model_dump`, logs and spans (`SecretStr` already used) | M1 |
| harden-runner | audit then block with allowlist on the publish job only | M7 |
| SBOM | CycloneDX via Syft on the built image, attached as attestation and release asset | M1 (CI artifact), M7 (published) |
| Provenance | `attest-build-provenance` in the shared `attest-image.yml`; Build L2 now, L3 through the isolated workflow; claim no more | M7 |
| Verify before deploy | `gh attestation verify oci://ghcr.io/gonzalomartinperez/pequeverso-assistant-api@sha256:... --signer-workflow gonzalomartinperez/engineering-standards/.github/workflows/attest-image.yml` in the release job and in `vps-ops` | M7, MV |
| Immutable releases | switched on before the first release; tag ruleset `v*` | M7 |
| Image scan | Grype (fail on fixable High or Critical); Trivy only as a SHA-pinned binary at or after v0.35.0 (decision E8) | M1 |

Images are never pushed from PR runs: `docker build` without publication stays (as today). Only the release workflow on `main` pushes `ghcr.io/gonzalomartinperez/pequeverso-assistant-api:vX.Y.Z` and `sha-<short>`, attests it, and records the digest.

## 8. Containers (ecosystem 8)

Services built here: `infra/docker/app` (the API), plus two fixture-grade database images used by the `database` job and the local profile: `infra/docker/postgres` and `infra/docker/neo4j`. Production databases are `vps-ops`' responsibility; these Dockerfiles must stay consistent with the fleet choice (PostgreSQL 18 on trixie with the `pg18` pgvector build, Neo4j 5.26 LTS digest-pinned).

LTS matrix applied (data as of 2026-11-09, ecosystem 8.1): Python 3.14.8 slim-trixie (fleet: 3.14.x; 3.15 only as a non-blocking CI job), Debian 13 trixie, PostgreSQL 18.6 with pgvector 0.8.7 (fleet: 18.x), Neo4j Community 5.26.32 (fleet names 5.26.33; the weekly digest PR picks it up), uv 0.13.1 digest-pinned (a branch proposes 0.13.7, picked by the weekly PR), Node for the three TypeScript tool files: the CI pin today is 24.22.0; the fleet moves to Node 26 after the two-week matrix (E10).

Canonical `infra/docker/app/Dockerfile` (target):

```dockerfile
# syntax=docker/dockerfile:1@sha256:4edf897a3ffa55b89f906fc8cc78afdb3f1834cc9c7083565e611a8a7d5fe99e
FROM ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336 AS uv

FROM python:3.14.8-slim-trixie@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0 UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,id=pva-uv-py314,target=/root/.cache/uv,sharing=locked \
    uv sync --locked --no-editable --no-dev --no-install-project

FROM python:3.14.8-slim-trixie@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS runtime
ARG SERVICE_REVISION=
ARG SOURCE_DATE_EPOCH
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/assistant.sqlite3 SERVICE_REVISION=${SERVICE_REVISION}
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY app ./app
COPY migrations ./migrations
COPY catalog ./catalog
COPY LICENSE NOTICE.md ./
# Runtime installs nothing: drop the global installer.
RUN rm -rf /usr/local/lib/python3.14/ensurepip/_bundled /usr/local/lib/python3.14/site-packages/pip* \
        /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.14 \
    && mkdir -p /data && chown 65532:65532 /data
LABEL org.opencontainers.image.title="pequeverso-assistant-api" \
      org.opencontainers.image.description="Advisory, read-only shopping assistant backend for Pequeverso" \
      org.opencontainers.image.source="https://github.com/gonzalomartinperez/pequeverso-assistant-api" \
      org.opencontainers.image.documentation="https://github.com/gonzalomartinperez/pequeverso-assistant-api/tree/main/docs" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.revision="${SERVICE_REVISION}"
USER 65532:65532
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=4).status == 200 else 1)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--no-proxy-headers", "--no-access-log", "--no-server-header", \
     "--timeout-graceful-shutdown", "15", "--timeout-keep-alive", "5", "--limit-concurrency", "200"]
```

Differences from today, with reasons: `--locked --no-editable` (ecosystem 8.2) instead of `--frozen`; OCI labels and `SOURCE_DATE_EPOCH` for reproducibility; the apt `liblzma5` patch layer removed once the base digest includes the fix (it needs network at build and a hand-maintained version string); cache id renamed (it said `vps-ops`); `UV_PYTHON_DOWNLOADS=0` spelling per the standard; health stays on `/health/live` from PVA-M1.7 and switches to `/healthz` in the same PR that adds the alias (PVA-M3.3 acceptance; the old paths stay served until `vps-ops` moves). Kept: one worker (in-process run registry and the private runtime ownership lease, `docs/deployment-contract.md`), UID 65532, no shell tooling added, no `ARG` secrets. Dependabot cannot resolve ARG-substituted `FROM` reliably (unverified), so `FROM` lines stay literal.

Runtime hardening (compose or Coolify custom options, enforced in `scripts/smoke_container.sh`): `read_only: true`, `tmpfs: /tmp`, `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, `pids_limit`, `mem_limit` with equal `memswap_limit`, `restart: unless-stopped`, `stop_grace_period` ≥ 20 s (uvicorn drain is 15 s). `/data` stays a writable mounted volume only for the SQLite fixture and import profile.

Gates on the image in CI: hadolint (`.hadolint.yaml`), dockle (CIS-DI), container-structure-test (user, labels, entrypoint, no pip, no shell tools beyond the base), Grype, then attest on release. Image size and vulnerability counts by severity are ratchet entries in `ratchets/image.json`.

## 9. Release automation (ecosystem 3.2)

release-please (manifest mode) on `develop`, starting at version 1.0.0 (the current hand-written `CHANGELOG.md` is kept as history), `changelog-sections` mapped to Added, Changed, Fixed, Removed, Security. It needs a GitHub App token or fine-grained PAT stored in an environment-scoped secret (owner-only grant). The owner merges the release PR when a release is wanted, then promotes `develop` to `main`; a workflow on `main` tags `vX.Y.Z`, creates an immutable GitHub Release (assets: SBOM, provenance), builds the image once, scans, attests and records the digest for the `vps-ops` pin PR. Open point E5: validate release-please-on-develop in a sandbox; fallback is release-please on `main` with a back-merge workflow. A weekly report prints "develop is N commits ahead of main".

## 10. Duration budgets (ecosystem 6.2, Assistant API)

| Path | p50 / p95 |
|---|---|
| PR critical path, cassette lane, no network | 5 min / 10 min |
| Nightly (live evaluation lane excluded, under a spend cap and owner authorization) | ≤ 60 min |
| Release | ≤ 45 min |

Baseline to be measured in M1 (no run history was pulled in this audit; unit suite alone is 249 s serial). A weekly job prints p50 and p95 of the last 30 runs with `gh run list --json`; alert when p95 exceeds the 4-week baseline by more than 25%. Order of remedies: cache hit rate, xdist, split jobs, shard, last paid runners.
