# 11 - Containers (Topic A) and dynamic CI in GitHub Actions (Topic B)

Date: 2026-11-09. Scope: 7 solo-engineer repos (2 FastAPI, 2 Postgres+pgvector, 1 Neo4j, 2 Next.js), Coolify on one VPS, deploy by digest.

**Method and honesty note.** The WebSearch budget of the session was exhausted at the start, so no open-ended search was possible. Everything below comes from direct fetches of ~55 primary pages (vendor docs, GitHub READMEs, advisories, endoflife.date API, Docker Hub tag pages). WebFetch returns a small-model summary of each page, so a few details are flagged "unverified" where the summary was thin. Items marked **[$]** have commercial interest. The 35+ source target is met by primary sources, but breadth of third-party opinion (blogs, benchmarks) is thinner than requested; see "Contested/uncertain".

---

## 1. Version / LTS matrix with EOL dates

All data fetched 2026-11-09 (sources S1-S12).

| Component | Version in repos now | Latest in line | Status today | EOL / end of support | Verdict |
|---|---|---|---|---|---|
| Node.js 24 "Krypton" | 24.22.0 | 24.22.2 | LTS since 2025-10-28; **Maintenance since 2026-10-20** | 2028-04-30 | Valid, but security/bugfix-only |
| Node.js 26 | - | 26.13.0 | **Active LTS since 2026-10-28** (Docker `lts`/`latest` tags now point here) | 2029-04-30 (maintenance from 2027-10-20) | Target for new/refreshed work once Next.js is validated on it |
| Node.js 25 | - | 25.9.0 | Non-LTS, EOL 2026-06-01 | 2026-06-01 | Never use |
| Node.js 22 | - | 22.23.4 | Maintenance LTS | 2027-04-30 | Only as fallback |
| Python 3.14 | 3.14.8 (stale; 3.14.10 is current) | 3.14.10 | Bugfix phase (2 years from 2025-10-07, i.e. to ~Oct 2027), then security | 2030-10-31 | **Keep as the fleet default** |
| Python 3.15 | - | 3.15.2 (GA 2026-10-09) | Bugfix. Docker `python:latest` = 3.15 | 2031-10-31 | Adopt around 3.15.3-3.15.4 once wheels exist (my judgement) |
| Python 3.13 | - | 3.13.18 | Security-only since Oct 2026 (no more binaries) | 2029-10-31 | Do not start on it |
| PostgreSQL 18 | 18.6 | 18.6 | Current major (GA 2025-09-25) | 2030-11-14 | **Fleet standard** |
| PostgreSQL 17 | - | 17.11 | Supported | 2029-11-08 | Only if an extension blocks 18 |
| pgvector | - | 0.8.7; images for PG 13-18 | Active | n/a (no formal EOL) | Use `pg18` build |
| Neo4j 5.26 LTS | 5.26.32-community | 5.26.33 (2026-11-04) | LTS, hotfixes continue | **2028-06-06** | Keep; bump to .33 |
| Neo4j 2026.x | - | 2026.10.x (monthly; each cycle supported ~3-6 weeks) | Non-LTS, `latest` Docker tag | next release | Avoid in production unless an LTS 2026.x is announced (not found in data) |
| Debian 13 trixie | base of all images | - | Released 2025-08-09 | 2030-06-30 (ELTS to 2035-06-30, third-party) | Fleet OS |
| Debian 12 bookworm | - | - | Oldstable | 2028-06-30 | Avoid for new work |
| Alpine 3.24 | postgres alpine | - | Released 2026-06-09 | 2028-06-01 | Not recommended for Postgres/Python (section 3) |

Key observations:
1. **Node 26 became LTS 12 days ago.** Our two backoffices are on 24, which entered Maintenance on 2026-10-20. Both are still supported until 2028-04-30, so there is no emergency, but a "best of the best, LTS" policy points at 26 after a CI pass. `gcr.io/distroless/nodejs26-debian13` exists (S19), and `node:26-trixie-slim` exists (S45).
2. Python docs list 3.14 in "bugfix" and 3.13 in "security" (S2). The 3.13 binary-release stop matters for anyone relying on python.org installers, less for Docker images, but it is a reason not to downgrade.
3. Image drift is already visible: python 3.14.8 vs 3.14.10, node 24.22.0 vs 24.22.2, neo4j 5.26.32 vs .33. Digest pinning without a working bump pipeline means we are pinning stale images (section 5).
4. Neo4j's own support page contradicts itself on 5.26 (summary says end of support, table says hotfixes to 2028-06-06). endoflife.date agrees with the table (S6, S7).

---

## 2. Base image choice

| Option | Pros | Cons | Fit |
|---|---|---|---|
| **Debian slim (trixie) official images** | glibc, manylinux wheels just work, ICU/locales sane, huge ecosystem, apt for pgvector, Dependabot/Renovate understand tags | Larger CVE surface than distroless; scanners show "unfixed low" Debian CVEs | **Default build and runtime base for Python and Postgres** |
| **Google distroless (`-debian13`, `nonroot`)** | No shell/package manager, signed with keyless cosign (S19), Node 22/24/26 and python3 variants; free, no account | `python3-debian13` pins Debian's system Python, not our 3.14 (unverified exact version; so unsuitable for 3.14), no HEALTHCHECK tooling (no curl/sh) | **Runtime for Next.js (already used)**; not for Python |
| **Docker Hardened Images (DHI)** **[$ Docker]** | Free tier Apache 2.0 since 2025-12-17, 1000+ images, SBOM, SLSA Build L3 provenance, Debian and Alpine, dev/runtime variants (S13-S16) | Community tier: no CVE SLA, no FIPS; pulled from `dhi.io` requiring `docker login` (OAT in CI) which complicates Dependabot/Coolify pulls; python/node entries flagged "Extended Lifecycle Support" in catalog (paid add-on); version coverage for Python 3.14/Node 26/PG 18/Neo4j not verified | **Pilot on one Python API and one backoffice** behind a build arg; do not adopt fleet-wide until Dependabot digest bumps and Coolify pulls from `dhi.io` are proven |
| **Chainguard / Wolfi** **[$ Chainguard]** | Minimal, rapid CVE fixes, apko/melange | Free tier restricted to `latest` tags only (per page stub; unverified), versioned/pinned tags are paid; Wolfi is glibc but non-Debian (apk, not Alpine-compatible) | Poor fit for "LTS-versioned, digest-pinned, free" |
| **Alpine** | Smallest, Postgres alpine supports ICU from PG 15 | musl: Python needs musllinux wheels (PEP 656) or compiles; historic perf and DNS/thread-stack issues (S36, author sells courses **[$]**, article updated Jan 2026 conceding wheels improved); Postgres docker docs: libc locales unsupported on musl images, ICU only (S25) | Drop for Python; drop for Postgres (collation differences, see recommendations) |

**Recommendation on base:** one OS family, Debian 13, everywhere (python slim-trixie, postgres trixie, neo4j trixie, node build trixie-slim, distroless debian13 runtime). That gives one CVE vocabulary, one glibc, one patch cadence. Treat DHI as an upgrade path, not a prerequisite.

---

## 3. Alpine vs Debian specifics for Postgres (relevant to the inconsistency)

- Postgres Docker docs: Alpine images "use musl libc"; PG 14 and earlier have no locale support; PG 15+ support ICU via `POSTGRES_INITDB_ARGS="--locale-provider=icu --icu-locale=..."` (S25).
- A cluster initialised on Alpine (musl libc collation or ICU) and one on Debian (glibc collation) sort text differently. Moving a data directory between them risks silently corrupt btree indexes on text columns; use `pg_dump | pg_restore` (or logical replication) and `REINDEX`, never a raw volume swap. (General Postgres knowledge; Postgres docs cover glibc collation index risk. Not re-fetched.)
- PG 18 image changes: default `PGDATA` is `/var/lib/postgresql/18/docker`, volume declared at `/var/lib/postgresql` (not `/data`); this enables `pg_upgrade --link` (S25). Check the Coolify volume mounts in both repos.
- pgvector ships Docker images `pgvector/pgvector:pg18-trixie` (S31). Official `postgres` images do not include pgvector. HNSW parallel builds need `--shm-size >= maintenance_work_mem` (S31).

---

## 4. Lifecycle and policy proposal (the "same config" rule)

1. **Tier 1 pin (digest):** every `FROM`/`image:` is `name:<full-version>-<variant>@sha256:...`. The tag stays for humans; the digest is what deploys.
2. **Version policy:** Node = newest **Active LTS** (26 now, move when it hits Active; fall back to Maintenance LTS only within 12 months). Python = newest minor that is in bugfix phase and where all lockfile deps have wheels (3.14 now). Postgres = newest major with >= 6 months age (18). Neo4j = latest LTS (5.26). OS = Debian stable (13).
3. **Bump cadence:** Dependabot/Renovate weekly grouped PR; security bumps immediate. Dependabot applies a default 3-day cooldown to version (not security) updates (S33), which is a free supply-chain buffer.
4. **One shared policy repo** (e.g. `gonzalomartinperez/.github` or `platform-ci`) owns Dockerfile templates, hadolint config, `docker-bake.hcl` fragments, compose hardening snippet, reusable workflows. Repos copy-sync templates (or use Renovate `customManagers` regex on a version file). There is no native Dockerfile include mechanism; a sync script or template repo is the pragmatic route.

---

## 5. Canonical templates

### 5.1 Python (FastAPI, uv, multi-stage, non-root, read-only-rootfs ready)

Rationale from uv docs (S10): pin uv by version and digest, `UV_PYTHON_DOWNLOADS=0` so both stages share the system interpreter, `uv sync --locked`, cache mount, `UV_LINK_MODE=copy`, `UV_COMPILE_BYTECODE=1`, non-editable install and copy only `.venv`.

```dockerfile
# syntax=docker/dockerfile:1
ARG PYTHON_IMAGE=python:3.14.10-slim-trixie@sha256:REPLACE
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.7@sha256:REPLACE

FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE} AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0 UV_NO_DEV=1
COPY --from=uv /uv /uvx /bin/
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-editable
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable

FROM ${PYTHON_IMAGE} AS runtime
ARG VERSION=dev REVISION=unknown CREATED=1970-01-01T00:00:00Z
LABEL org.opencontainers.image.title="api" \
      org.opencontainers.image.source="https://github.com/OWNER/REPO" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.created="${CREATED}" \
      org.opencontainers.image.licenses="UNLICENSED"
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONFAULTHANDLER=1
RUN groupadd --system --gid 65532 app \
 && useradd  --system --uid 65532 --gid 65532 --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=builder --chown=65532:65532 /app/.venv /app/.venv
USER 65532:65532
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD ["python","-c","import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=2).status==200 else 1)"]
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--proxy-headers"]
```

Notes:
- **Bytecode at build + `PYTHONDONTWRITEBYTECODE=1`** makes a read-only root filesystem work; provide `tmpfs: /tmp` for anything else.
- **No curl in slim**, so the healthcheck uses stdlib `urllib` (also works for distroless-like images).
- **tini / dumb-init:** needed only if the app spawns subprocesses that can orphan (zombie reaping) or if signals are not handled. Uvicorn handles SIGTERM when it is PID 1 and shows no children. Prefer runtime `init: true` / `docker run --init` (Docker bundles tini since 1.13, S43) over baking a binary into the image. Whether Coolify exposes `init` for compose services should be verified (unverified).
- **Reproducibility:** pass `SOURCE_DATE_EPOCH=$(git log -1 --pretty=%ct)` as env on the build step; Docker docs show this for `build-push-action@v7` and `bake-action@v7` (S41). Full bit-for-bit reproducibility also needs pinned base digests and a locked dependency set; both are present.
- Run `uv lock --check`/`--locked` in CI so a stale `uv.lock` fails the build.

### 5.2 Next.js standalone (build trixie-slim, run distroless nonroot)

Next.js docs: `output: 'standalone'` emits `.next/standalone` with a minimal `server.js`; `public` and `.next/static` must be copied manually; `PORT`/`HOSTNAME` env configure it; `outputFileTracingRoot` for monorepos (S20).

```dockerfile
# syntax=docker/dockerfile:1
ARG NODE_IMAGE=node:26.13.0-trixie-slim@sha256:REPLACE
ARG RUNTIME_IMAGE=gcr.io/distroless/nodejs26-debian13:nonroot@sha256:REPLACE

FROM ${NODE_IMAGE} AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --ignore-scripts

FROM ${NODE_IMAGE} AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1 NODE_ENV=production
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN --mount=type=cache,target=/app/.next/cache npm run build

FROM ${RUNTIME_IMAGE} AS runtime
ARG VERSION=dev REVISION=unknown
LABEL org.opencontainers.image.source="https://github.com/OWNER/REPO" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build --chown=65532:65532 /app/.next/standalone ./
COPY --from=build --chown=65532:65532 /app/.next/static ./.next/static
COPY --from=build --chown=65532:65532 /app/public ./public
USER 65532:65532
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
  CMD ["/nodejs/bin/node","-e","fetch('http://127.0.0.1:3000/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
CMD ["server.js"]
```

Notes: the distroless Node entrypoint is `node`, so `CMD ["server.js"]` works; no shell, so no `HEALTHCHECK CMD curl`. The `nonroot` user is UID 65532 (distroless convention; the fetched page did not state it, unverified). Add `sharp` includes via `outputFileTracingIncludes` if image optimisation is used (S20). Node 24 variant: swap the two ARGs.

### 5.3 Postgres + pgvector (one image, both repos)

```dockerfile
ARG PG_IMAGE=postgres:18.6-trixie@sha256:REPLACE
FROM ${PG_IMAGE}
# PGDG apt repo is preconfigured in the official Debian-based image
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-${PG_MAJOR}-pgvector \
 && rm -rf /var/lib/apt/lists/*
```

Alternative: `pgvector/pgvector:pg18-trixie@sha256:...` (maintained by the pgvector author, S31). Pick one for both repos. The apt package route is from my general knowledge, not fetched. Mount data at `/var/lib/postgresql` (PG 18 layout).

### 5.4 Neo4j

`neo4j:5.26.33-community-trixie@sha256:...` (Docker Hub lists `-trixie` and `-ubi10` suffixes, S47). No custom Dockerfile unless plugins (APOC) are needed; mount `/data` and `/logs`, set `NEO4J_AUTH` from a secret, limit heap/pagecache explicitly.

### 5.5 Tooling stack (build, scan, attest)

- **BuildKit cache mounts** as above; **buildx bake** (`docker-bake.hcl`, groups/targets, one invocation builds several images concurrently, S39) as the single build entry point, same file locally and in CI.
- **Multi-arch:** only if the VPS or a dev machine is arm64. distroless nodejs24/26 do not publish `arm` (32-bit) but do publish arm64 (S19). Default: amd64 only; avoid QEMU cost without a need.
- **Lint:** hadolint (failure-threshold, `trustedRegistries`, DL3006/3007 tag rules; S32) on Dockerfiles; **dockle** on built image (CIS-DI checks: non-root, HEALTHCHECK, setuid files; SARIF output; license text inconsistent AGPL/Apache, check before bundling; S34); **container-structure-test** for asserting USER, labels, entrypoint, absence of shell (the project is in maintenance mode and "not an officially supported Google project", S35; acceptable for ~20 lines of YAML but low expectation of new features).
- **Scan:** Trivy or Grype (Apache-2.0, EPSS/KEV, OpenVEX, S37, **[$ Anchore sponsors]**). **Trivy caution:** on 2026-03-19..23 the Trivy ecosystem was compromised (GHSA-69fq-xp46-6x23 / CVE-2026-33634): malicious v0.69.4 binaries/images, trivy-action tags 0.0.1-0.34.2 and setup-trivy tags v0.2.0-v0.2.6 hijacked; safe: Trivy v0.69.2/.3, trivy-action v0.35.0, setup-trivy v0.2.6; "images referenced by digest" were not affected (S28 advisory). Lesson: pin by SHA, never `version: latest`. trivy-action docs now show `@v0.36.0` and default Trivy v0.76.2 (S27). Cache the vuln DB and keep the scheduled cache refresh to avoid rate limiting.
- **SBOM + provenance:** `docker/build-push-action@v7` inputs `provenance` and `sbom` (S38). Defaults: public repos `mode=max`, private repos `mode=min`; `mode=max` embeds build-arg values and the Dockerfile, so move any secret to `--mount=type=secret` (S9, S29). Attestations require `push: true` (no `load`).
- **Signing:** two options. (a) GitHub native: `actions/attest@v4` with `subject-digest` from build-push-action output, `push-to-registry: true`, perms `id-token: write, attestations: write, packages: write`, verify with `gh attestation verify oci://...` (S37b). (b) cosign keyless (Fulcio+Rekor, identity-bound, S26), verify with `--certificate-identity` and OIDC issuer. For one VPS and solo owner, (a) is simpler; use (b) only if the verifier must be outside GitHub. Plan availability of attestations for private repos is not stated in the docs fetched (unverified).
- **SLSA:** DHI claims Build L3 for its own images (S13). For our builds on GitHub-hosted runners with attestations we are realistically at L2-L3 depending on isolation; SLSA spec page fetched is the retired v1.1, current is v1.2 (S50).

### 5.6 Runtime hardening block (compose / Coolify "custom docker options")

```yaml
services:
  api:
    image: ghcr.io/OWNER/api@sha256:...
    init: true                      # tini via Docker; verify Coolify honours it
    read_only: true
    tmpfs: [ "/tmp:size=64m,mode=1777" ]
    cap_drop: [ ALL ]
    security_opt: [ "no-new-privileges:true" ]
    user: "65532:65532"
    pids_limit: 256
    mem_limit: 512m
    cpus: 1.0
    restart: unless-stopped
    healthcheck: { test: ["CMD","python","-c","..."], interval: 30s, timeout: 3s, retries: 3, start_period: 20s }
```

Docker's docs: containers already drop all but an allowlist of capabilities; removing more tends to improve security (S24). Coolify custom Docker options list `--cap-drop`, `--read-only`, `--security-opt` (with a seccomp example needing the profile file on the host path) as supported and ignore unlisted flags with a warning (S30). So set the hardening via Coolify options if not using compose. Postgres and Neo4j need writable data volumes and cannot always be `read_only` without tmpfs for `/var/run/postgresql` and `/tmp`; test before enforcing, and they need `CHOWN/SETUID/SETGID/DAC_OVERRIDE`-type caps at init (Postgres entrypoint drops privileges via gosu; use `cap_drop: ALL` plus `cap_add: [CHOWN, SETUID, SETGID, DAC_OVERRIDE, FOWNER]` as a starting point, validated empirically, my judgement).

### 5.7 Dev containers

`devcontainer.json` supports image-based, Dockerfile-based and compose-based configs, Features, `securityOpt`/`capAdd` merges, `remoteUser`, and `updateRemoteUserUID` on Linux to avoid bind-mount permission issues (S40). Proposal: each repo ships `.devcontainer/devcontainer.json` using the **same** `PYTHON_IMAGE`/`NODE_IMAGE` ARGs via a Dockerfile (`target: builder`) plus Features for `uv`, `gh`, and a `postgres` compose service identical to prod image. This gives "local equals CI equals prod" parity. Owner works in WSL on the Linux filesystem, so no `/mnt/c` mounts.

---

## 6. Topic B: dynamic CI

### 6.1 Path-based execution and the required-checks problem

- Native `paths:`/`paths-ignore:` filter at workflow level. **GitHub docs: a workflow skipped by path/branch filtering leaves its checks "Pending", and a PR requiring them is blocked** (S21, workflow-syntax). Skipped by job-level `if:` reports "skipped", which satisfies a required check (S22, protected-branches says required checks need "successful, skipped, or neutral"). Therefore: **never use workflow-level `paths:` on a workflow that provides a required check.** Use a job-level change detector and a gate job.
- **dorny/paths-filter** v4 (Node 24 runtime), supports `merge_group` (base/ref from the event), outputs per-filter booleans plus a `changes` JSON array usable as a matrix; needs checkout for git-based diff, `pull-requests: read`; file-list outputs may carry attacker-controlled filenames, pass via `env:` (S17). It is third-party, so pin by SHA and let Renovate bump it.
- **tj-actions/changed-files** was compromised 2025-03-12..15 (CVE-2025-30066; reviewdog/action-setup CVE-2025-30154 was the entry point), leaked secrets from logs, added to CISA KEV (S18). Avoid; and the lesson generalises: any third-party action that sees secrets is a trust decision.
- **Zero-dependency alternative (recommended):** a 15-line `git diff --name-only $BASE...$HEAD | grep` script in the shared repo, emitting `GITHUB_OUTPUT` booleans. No supply chain, trivial on 7 repos, handles `merge_group` via `github.event.merge_group.base_sha`.
- Caveat on native filters: pushes over 1,000 commits or diffs over 3,000 files may always/never run (S21).

### 6.2 Aggregate gate job

Mark only one check required, named e.g. `ci-gate`, with `if: always()` and `needs: [all jobs]`; fail if any `needs.*.result` is `failure` or `cancelled`; treat `skipped` as OK. Because the gate itself always runs, the Pending trap disappears, and renaming matrix jobs never breaks branch protection.

### 6.3 Dynamic matrices and impact analysis

- Job 1 emits JSON (`echo "matrix=$(jq -c ...)" >> $GITHUB_OUTPUT`), job 2 uses `strategy.matrix: ${{ fromJSON(needs.plan.outputs.matrix) }}`. Matrix limit 256 jobs (from my knowledge; page not retrieved). Keep `fail-fast: false` for visibility.
- **Playwright:** `--only-changed[=ref]` runs only test files changed vs ref (docs: git only; S23). It operates on test files, so a change in app source does not trigger relevant specs unless Playwright's dependency tracking catches it (docs summary does not claim source-to-test mapping; treat it as a PR fast-path, keep a full run on `merge_group` and nightly). Also `--last-failed`, `--shard i/n`, `--fail-on-flaky-tests`, `-x` (S23).
- **Stryker incremental:** `--incremental` diffs mutated and test files against `reports/stryker-incremental.json`; **does not detect changes outside mutated and test files** (deps, env, snapshots); you must persist the file between runs via `actions/cache` or artifacts; `--force` for full (S42). Use: PR runs incremental on changed files, nightly full.
- Test impact analysis for Python: `pytest --testmon` or path-to-suite mapping via the change detector (not researched in depth; unverified). For 7 small repos, the path map to {lint, unit, e2e, docker} gives most of the value.

### 6.4 Docker layer caching

- `type=gha` works only inside workflows, and only Cache API v2 is supported since 2025-04-15 (needs Buildx >= 0.21, BuildKit >= 0.20); `pull_request_target`/`issue_comment` often get read-only cache (S29b).
- `type=registry,mode=max` stores cache in a registry tag, portable, no 10 GB repo cache eviction pressure. With several images and an `actions/cache` budget shared per repo, **registry cache on GHCR (`:buildcache`) is the safer default**, `type=gha` is fine for the smallest repos. Inline cache only supports `min`.
- Trivy DB: cache enabled by default, refresh via scheduled default-branch job (S27).

### 6.5 Shared reusable workflows and composite actions

- Call `owner/repo/.github/workflows/x.yml@ref` with tag, branch or **SHA (safest)**; nesting up to 10 levels, up to 50 unique reusable workflows per file; `GITHUB_TOKEN` permissions in nested calls can only stay equal or shrink; secrets pass only to the directly called workflow, `secrets: inherit` within the same org (S22, S44). Cross-repo use of **private** workflows requires the host repo's Actions access setting to allow the caller (S44).
- Pattern: central repo `gonzalomartinperez/ci-templates` with `python-ci.yml`, `node-ci.yml`, `docker-build.yml`, `gate`. Consumers pin `@v1.4.2` (full SHA via Renovate `helpers:pinGitHubActionDigestsToSemver`, S46). Rename tags with semver; keep `v1` moving tag only for first-party repos you trust; **Reusable workflows are called at job level, not step level** so a composite action is needed for step-sized reuse (setup-uv, setup-node, harden-runner).
- Caution: since the central repo becomes a single point of compromise for 7 repos, enable branch/tag protection and signed tags there; use CODEOWNERS on `.github/workflows` (S8).

### 6.6 Workflow security hardening

From GitHub's secure-use guide (S8): pin actions to full SHAs (verify not a fork commit); default read-only `GITHUB_TOKEN` and elevate per job; avoid script injection by putting `${{ github.event.* }}` into `env:`; OIDC instead of long-lived cloud secrets; dependency-review on PRs; CODEOWNERS for workflows. The same page mentions **workflow dependency lockfiles** as a stronger control that "supersede SHA pinning" where available (a docs page for it returned 404 when fetched, so rollout status is unverified).
- `permissions: {}` at workflow top, then job-level grants (S21).
- `actions/checkout@v7` with `persist-credentials: false` (default is `true`; since v6 the token lives in a file under `$RUNNER_TEMP`; v7 refuses fork PR checkout in `pull_request_target`/`workflow_run` without `allow-unsafe-pr-checkout`; S47b). Use `fetch-depth: 0` only for the change detector job, or `fetch-depth: 2` plus merge-base fetch.
- **zizmor** (MIT, static analysis of workflows, Dependabot and pre-commit configs: template injection, credential persistence, excess permissions, impostor commits; personas regular/pedantic/auditor; SARIF output with exit 0; online audits with a token; `zizmor.yml` ignores; S15, S16). Run in CI on any PR touching `.github/**`.
- **step-security/harden-runner** **[$ StepSecurity]**: free Community tier only for **public** repos on GitHub-hosted runners; private repos need paid Enterprise; `egress-policy: audit` first, then `block` with allowlist; Windows/macOS audit only (S19b). Our repos are likely private, so harden-runner is not free for us; the alternative is egress rules by design (few external hosts) and zizmor + SHA pinning. Treat as optional.
- OIDC: for deploys use environments with required reviewers and `id-token: write` only in the deploy job; Coolify itself is triggered by webhook and token (stored as secrets, S30b), which cannot use OIDC; keep those two secrets in an `environment: production` with branch restriction.
- Dependabot ecosystems `github-actions`, `docker`, plus `uv`/`npm`; cooldown default 3 days for version updates, not for security updates; group by ecosystem to cut PR noise (S33).

### 6.7 Concurrency, timeouts, merge queue

- `concurrency: { group: ci-${{ github.workflow }}-${{ github.ref }}, cancel-in-progress: ${{ github.event_name == 'pull_request' }} }`; include `github.workflow` to avoid cancelling other workflows; `queue: max` cannot combine with cancel-in-progress (S21). Never cancel deploy/release runs.
- `timeout-minutes` on every job (default is 360; page truncated, from knowledge): suggest 10-15 for lint/unit, 25 for e2e, 30 for image build.
- **Merge queue:** workflows must also trigger on `merge_group`, else the required check never reports and merges stall; protection rule cannot use wildcard branch patterns; settings: build concurrency 1-100, group size 1-100, check timeout (S23b). For a solo engineer with Dependabot PRs, a queue is optional but it makes "merge only with green CI on the real merge commit" mechanical; availability for private repos on the owner's plan is not stated in the doc fetched (unverified).

### 6.8 CI observability

Not covered by fetched sources in depth (gap). Practical minimum: job summaries (build-push-action emits them, S38), `timeout-minutes` as hard duration budget, Playwright `--fail-on-flaky-tests` plus retries reporting for flake tracking (S23), and a weekly `gh run list --json` aggregation for p50/p95 duration per workflow. Dedicated tools (Datadog CI Visibility, BuildPulse, etc.) are **[$]** and unevaluated here.

### 6.9 Canonical CI skeleton (caller in each repo)

```yaml
# .github/workflows/ci.yml
name: ci
on:
  pull_request:
  merge_group:
  push: { branches: [develop] }
permissions: {}
concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

jobs:
  changes:
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    permissions: { contents: read }
    outputs:
      app:    ${{ steps.f.outputs.app }}
      docker: ${{ steps.f.outputs.docker }}
      ci:     ${{ steps.f.outputs.ci }}
    steps:
      - uses: actions/checkout@<SHA> # v7
        with: { fetch-depth: 0, persist-credentials: false }
      - id: f
        env:
          BASE: ${{ github.event.pull_request.base.sha || github.event.merge_group.base_sha || github.event.before }}
          HEAD: ${{ github.sha }}
        run: |
          files=$(git diff --name-only "$BASE" "$HEAD" || echo ALL)
          has(){ [ "$files" = ALL ] || echo "$files" | grep -Eq "$1" && echo true || echo false; }
          echo "app=$(has '^(src|app|tests|pyproject|uv\.lock|package(-lock)?\.json)')" >> "$GITHUB_OUTPUT"
          echo "docker=$(has '^(Dockerfile|docker-bake|\.dockerignore|uv\.lock|package-lock)')" >> "$GITHUB_OUTPUT"
          echo "ci=$(has '^\.github/')" >> "$GITHUB_OUTPUT"

  lint-workflows:
    needs: changes
    if: needs.changes.outputs.ci == 'true'
    uses: gonzalomartinperez/ci-templates/.github/workflows/zizmor.yml@<SHA> # v1.x
    permissions: { contents: read, security-events: write }

  test:
    needs: changes
    if: needs.changes.outputs.app == 'true'
    uses: gonzalomartinperez/ci-templates/.github/workflows/python-ci.yml@<SHA> # or node-ci.yml
    permissions: { contents: read }

  image:
    needs: changes
    if: needs.changes.outputs.docker == 'true' || needs.changes.outputs.app == 'true'
    uses: gonzalomartinperez/ci-templates/.github/workflows/docker-build.yml@<SHA>
    permissions: { contents: read, packages: write, id-token: write, attestations: write }
    with: { push: ${{ github.event_name == 'push' }} }   # PRs: build + scan, no push

  gate:                       # the ONLY required status check
    if: always()
    needs: [changes, lint-workflows, test, image]
    runs-on: ubuntu-24.04
    timeout-minutes: 2
    steps:
      - env: { NEEDS: "${{ toJSON(needs) }}" }
        run: |
          echo "$NEEDS" | jq -e '[.[].result] | all(. == "success" or . == "skipped")'
```

`docker-build.yml` (central): setup-buildx, login to GHCR, hadolint, `docker/bake-action` with `SOURCE_DATE_EPOCH`, `provenance: mode=max` + `sbom: true` (secrets only via secret mounts), cache registry `:buildcache`, Trivy/Grype scan with fail on HIGH/CRITICAL fixed, dockle, container-structure-test, `actions/attest` on the digest, output the digest for Coolify. Deploy job: `environment: production`, `needs: image`, only on `push` to main (release-only per repo rule), updates Coolify to `image@sha256:<digest>`; no auto-merge without green CI.

---

## 7. Recommendations for our 7 repos

1. **Unify Postgres on `postgres:18.6-trixie` + pgvector** in both repos (kills the alpine/trixie split). Alpine to trixie needs `pg_dump`/restore (collation change, section 3), not a volume reuse; schedule it with a backup and a restore drill. Pick one pgvector method (apt package or `pgvector/pgvector:pg18-trixie`).
2. **Python APIs:** bump to `python:3.14.10-slim-trixie` and a current uv tag (docs show 0.13.7; repo has 0.13.1), both with digests; adopt template 5.1; keep UID 65532. Move 3.15 to a trial branch after 3.15.3+.
3. **Next.js backoffices:** run CI matrix on Node 24 and 26 for two weeks, then flip both to 26 (`node:26.x-trixie-slim` and `nodejs26-debian13:nonroot`). Add `--ignore-scripts` and cache mounts. Fall back to staying on 24 (supported to 2028-04-30) if a dependency lags.
4. **Neo4j:** stay `5.26.33-community` (+ `-trixie` if the tag exists for the exact version, the Hub page lists suffix variants), digest-pinned. Do not adopt monthly 2026.x. Re-check whether Neo4j announces a 2026 LTS.
5. **Shared repo `ci-templates`** with reusable workflows, composite actions, Dockerfile templates, `.hadolint.yaml`, `docker-bake.hcl` fragments, Renovate/Dependabot configs; SHA-pin all external actions; enable zizmor on all 7 repos immediately (quick win, MIT, no cost).
6. **Branch protection:** one required check `ci-gate` per repo; enable `merge_group` triggers now even if the queue is enabled later. Fits the owner's rule "merge only with green CI" (`gh pr checks --watch && gh pr merge`).
7. **Supply chain:** build with provenance+SBOM, sign with `actions/attest`, verify digest at deploy; remove `tj-actions/*` if present; confirm no `aquasecurity/trivy-action` older than 0.35.0 or `setup-trivy` unpinned; rotate secrets if a workflow ran Trivy on 2026-03-19..23.
8. **Runtime:** apply 5.6 flags via Coolify custom Docker options for the APIs and backoffices first; stateful DBs after empirical tests.
9. **DHI pilot:** one API on `dhi.io/python:3.14-...` behind a build ARG; evaluate Dependabot digest PRs, Coolify pull auth (OAT), and image diff vs slim. Decide after 30 days.
10. **Dependabot:** keep default cooldown, group `docker` and `github-actions` updates weekly, security updates immediate; add a repo-level check that fails if base digests are older than 30 days.

---

## 8. Contested / uncertain

- **Distroless vs DHI vs slim for Python:** distroless `python3-debian13` uses the Debian system Python (not 3.14), so it conflicts with a 3.14 policy. DHI looks attractive but the free tier has no CVE SLA and version coverage for Python 3.14/Node 26/PG 18 was not verified from the catalog page (only 24/790 entries visible).
- **Tini:** many guides bake it in; Docker's own `--init` makes it unnecessary in the image. Both are valid; policy choice, not a security difference unless subprocesses exist.
- **Provenance `mode=max` on public repos** leaks build-arg values; some teams standardise on `min`. If any repo is public, audit build args first.
- **cosign vs GitHub attestations:** cosign has broader tooling; GitHub attestations are simpler inside GitHub. Cosign v3 bundle-format changes were not confirmed from the fetched page.
- **Playwright `--only-changed`:** documented as changed test files; whether it follows source dependencies was not confirmed. Keep full runs on merge.
- **Neo4j 5.26 vs 2026.x:** no 2026 LTS appeared in endoflife.date or the support page; this can change. Neo4j Community lacks some Enterprise features (clustering, online backup, RBAC granularity: general knowledge, not fetched).
- **Node 26 readiness for Next.js** (installed Next version, native deps like sharp) not verified.
- **Workflow dependency lockfiles** are mentioned in GitHub docs as superior to SHA pinning but the dedicated page was 404; do not plan around it yet.
- **harden-runner** value for private repos is gated behind a paid tier; evidence of its effectiveness is vendor-supplied **[$]**.
- Third-party opinion pieces and benchmarks were not gathered (search budget), so claims such as "Alpine slower for Python" rest on one vendor-adjacent blog **[$]** with a note that it is partly outdated.
- Chainguard free-tier policy came from a placeholder page; confirm before dismissing it.
- Unverified details: exact distroless nonroot UID, matrix 256-job cap, Actions `timeout-minutes` default, merge queue availability by plan, Coolify support for `init`.

---

## 9. Sources

Dates/versioning data:
- S1 Node release schedule JSON: https://raw.githubusercontent.com/nodejs/Release/main/schedule.json
- S2 Python devguide versions: https://devguide.python.org/versions/
- S3 Python 3.15.0 release: https://www.python.org/downloads/release/python-3150/
- S4 endoflife.date Debian: https://endoflife.date/api/debian.json
- S5 endoflife.date PostgreSQL: https://endoflife.date/api/postgresql.json
- S6 endoflife.date Neo4j: https://endoflife.date/api/neo4j.json
- S7 Neo4j supported versions: https://support.neo4j.com/s/article/115013134648-Neo4j-Supported-Versions/
- S9a endoflife.date Alpine: https://endoflife.date/api/alpine-linux.json
- S9b endoflife.date Node: https://endoflife.date/api/nodejs.json
- S9c endoflife.date Python: https://endoflife.date/api/python.json
- S45 Docker Hub node: https://hub.docker.com/_/node ; python: https://hub.docker.com/_/python ; postgres: https://hub.docker.com/_/postgres ; neo4j: https://hub.docker.com/_/neo4j

Containers:
- S10 uv Docker guide: https://docs.astral.sh/uv/guides/integration/docker/
- S13 Docker Hardened Images announcement (Docker, **[$]**): https://www.docker.com/blog/docker-hardened-images-for-every-developer/
- S14 DHI docs **[$]**: https://docs.docker.com/dhi/
- S15b DHI usage **[$]**: https://docs.docker.com/dhi/how-to/use/
- S16 DHI catalog **[$]**: https://hub.docker.com/hardened-images/catalog
- S19 Google distroless: https://github.com/GoogleContainerTools/distroless
- Chainguard free-tier page (stub, **[$]**): https://www.chainguard.dev/unchained/chainguard-containers-free-tier-changes
- Wolfi **[$ Chainguard]**: https://github.com/wolfi-dev/os
- S20 Next.js standalone output: https://nextjs.org/docs/app/api-reference/config/next-config-js/output
- S25 Postgres Docker image docs: https://github.com/docker-library/docs/blob/master/postgres/README.md
- S31 pgvector: https://github.com/pgvector/pgvector
- S36 Alpine for Python (pythonspeed, **[$]**): https://pythonspeed.com/articles/alpine-docker-python/
- S43 tini: https://github.com/krallin/tini
- S24 Docker Engine security: https://docs.docker.com/engine/security/
- S32 hadolint: https://github.com/hadolint/hadolint
- S34 dockle: https://github.com/goodwithtech/dockle
- S35 container-structure-test: https://github.com/GoogleContainerTools/container-structure-test
- S27 trivy-action: https://github.com/aquasecurity/trivy-action
- S28 Trivy advisory: https://github.com/aquasecurity/trivy/security/advisories/GHSA-69fq-xp46-6x23 (list: https://github.com/aquasecurity/trivy/security/advisories)
- S37 Grype **[$ Anchore]**: https://github.com/anchore/grype
- S9 Docker SLSA provenance modes: https://docs.docker.com/build/metadata/attestations/slsa-provenance/
- S29 Docker GHA attestations: https://docs.docker.com/build/ci/github-actions/attestations/
- S29b Docker GHA cache: https://docs.docker.com/build/ci/github-actions/cache/
- S39 Bake: https://docs.docker.com/build/bake/
- S41 Reproducible builds: https://docs.docker.com/build/ci/github-actions/reproducible-builds/
- S38 build-push-action: https://github.com/docker/build-push-action
- S37b GitHub artifact attestations: https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations
- S26 Sigstore/cosign keyless: https://docs.sigstore.dev/cosign/signing/overview/
- S50 SLSA levels (v1.1, retired): https://slsa.dev/spec/v1.1/levels
- S40 Dev container spec: https://containers.dev/implementors/spec/
- S15c Renovate Docker: https://docs.renovatebot.com/docker/
- S46 Renovate helper presets: https://docs.renovatebot.com/presets-helpers/
- S33 Dependabot options: https://docs.github.com/en/code-security/dependabot/working-with-dependabot/dependabot-options-reference
- S30 Coolify custom Docker options: https://coolify.io/docs/knowledge-base/docker/custom-commands
- S30b Coolify GitHub Actions deploy: https://coolify.io/docs/applications/ci-cd/github/actions

CI:
- S8 GitHub secure use: https://docs.github.com/en/actions/reference/security/secure-use
- S21 Workflow syntax: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
- S22 Protected branches: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
- S44 Reusing workflows: https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows ; https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations
- S23b Merge queue: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue
- S17 dorny/paths-filter: https://github.com/dorny/paths-filter
- S18 CISA tj-actions alert: https://www.cisa.gov/news-events/alerts/2025/03/18/supply-chain-compromise-third-party-github-action-cve-2025-30066
- S15 zizmor: https://github.com/zizmorcore/zizmor ; S16 usage: https://docs.zizmor.sh/usage/
- S19b harden-runner **[$ StepSecurity]**: https://github.com/step-security/harden-runner
- S47b actions/checkout: https://github.com/actions/checkout
- S23 Playwright CLI: https://playwright.dev/docs/test-cli
- S42 Stryker incremental: https://stryker-mutator.io/docs/stryker-js/incremental/

Pages that failed (no data used): GitHub troubleshooting-required-checks, concurrency how-to, dependency lockfiles, Chainguard pricing, OWASP Docker cheat sheet, SLSA v1.2, Postgres versioning page (socket error).
