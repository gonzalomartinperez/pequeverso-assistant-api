# Best-in-class single-VPS operations in 2026 (research for vps-ops)

Date: 2026-11-09. Scope: one Hostinger KVM VPS running 2 FastAPI assistant APIs, 2 Next.js backoffices, Postgres+pgvector, Neo4j. Images built in CI, deployed by GHCR digest. Solo engineer, tight budget, LLM spend caps.

Method note: roughly 35 sources. Primary data (GitHub API for advisories, releases and licences, vendor docs) is preferred over SEO blogs. The WebSearch budget ran out mid-research, so the sections on infra testing, Ansible vs pyinfra, GlitchTip vs Sentry, SigNoz vs LGTM and Komodo rest on vendor docs plus my own prior knowledge. Those are flagged "[lower confidence]". Items marked **[$]** come from a source with a commercial interest.

---

## 1. Bottom line

1. **Do not run a web-UI control plane (Coolify or Dokploy) on the same host as Postgres and Neo4j.** Both have had a very large, mostly authenticated-RCE-as-root advisory stream in 2026 (section 2). The control plane holds SSH keys and every secret. For a solo operator with a static, five-service topology, the PaaS adds attack surface and RAM and removes little work.
2. **Best fit: declarative Docker Compose, deployed by digest from a Python deploy script or CLI, behind Caddy (or Traefik), with Ansible or pyinfra for host convergence.** Kamal 2 is the closest off-the-shelf equivalent, and its security record is clean (zero GitHub advisories). Its main gaps are digest pinning and non-Rails ergonomics.
3. **Backups decide whether this is serious ops.** Postgres needs base backups plus WAL archiving to object storage (WAL-G or pgBackRest), and Neo4j Community needs an offline dump. Restic or borg should cover everything else. A scheduled restore drill matters more than the tool choice.
4. **Observability: Beszel + Uptime Kuma + GlitchTip (or Sentry SaaS free tier) + structured logs, plus Langfuse only if it earns its resources.** Skip a full LGTM or SigNoz stack on this box. OpenTelemetry instrumentation in the apps keeps the later move cheap.
5. **Secrets: SOPS + age in git for deploy-time secrets**, one age key held offline plus one on the server. Use a hosted manager (Infisical Cloud or 1Password) only if rotation and audit become real needs.

---

## 2. Platform choice: Coolify vs Dokploy vs Kamal 2 vs Compose+Caddy/Traefik vs k3s

### 2.1 Coolify: security record is the deciding fact

Primary data from the GitHub security-advisories API for `coollabsio/coolify` (pulled 2026-11-09, first five pages): **70 published advisories** (21 critical, 26 high, 15 medium, 8 low). By publication month: 9 in Jan 2025, 16 in Jan 2026, 11 in Jun 2026, 34 in Jul 2026. Typical classes are OS command injection reaching host root, cross-team IDOR exposing SSH keys, WebSocket terminal authorization bypass, webhook HMAC bypass with a null secret, and Sentinel-token injection. Examples include CVE-2026-57498 (critical cross-team IDOR), CVE-2026-34048 and CVE-2026-34047 (critical terminal WebSocket flaws), and CVE-2026-42204 (authenticated RCE via a regression of the shell-safety pattern, which is a repeat of a bug class).

Secondary reporting: Belgium's CCB warned in January 2026 to patch critical Coolify flaws, including CVE-2025-64419 (CVSS 9.6). Hostzero's summary reports 11 critical CVEs on 2026-01-08 and about 52,890 publicly reachable dashboards (a Censys figure) ([CCB](https://ccb.belgium.be/advisories/warning-critical-coolify-vulnerabilities-patch-immediately), [Hostzero](https://hostzero.com/articles/is-coolify-safe-2026-cves), [Censys](https://censys.com/advisory/cve-2025-64424-cve-2025-64420-cve-2025-64419)). I treat Hostzero's later CVE IDs and dates as unverified, because the article has internal date inconsistencies. As of its writing it found no confirmed in-the-wild exploitation and no CISA KEV entry.

Maintenance is very active (v4.0.0 stable on 2026-04-27 per Hostzero; v4.7.1 released 2026-11-09 per the GitHub API; Apache-2.0; about 65.8k stars). The pace of fixes is a strength. The pace and class of vulnerabilities is the risk: the "authenticated user becomes host root" pattern means any Coolify account, or any stolen API token (CVE-2026-42172: Sanctum tokens never expire), is root on every managed server.

Operational facts from Coolify's own docs ([firewall](https://coolify.io/docs/knowledge-base/server/firewall), [backups](https://coolify.io/docs/databases/backups)):

- Docker-published ports bypass UFW. Coolify recommends a provider network firewall, or the community `ufw-docker` tool as a fallback.
- Scheduled DB backups cover Postgres, MySQL, MariaDB, MongoDB, ClickHouse and SQLite as dumps. There is no Neo4j, no WAL/PITR, and Redis-family stores are excluded. Coolify states that a successful backup only proves a file was created, and it does not cover backing up the Coolify instance itself.
- Ports 8000/6001/6002 can be bound to localhost via `docker-compose.custom.yml`.

### 2.2 Dokploy

Same pattern, arguably worse in the data. `Dokploy/dokploy` advisories (GitHub API): **60 published** (34 critical, 17 high), with **42 on 2026-07 alone** (for example CVE-2026-72864, WebSocket terminal member-to-root, and CVE-2026-72737, cross-organisation S3 credential exposure) and several "incomplete fix / fix bypass" entries. Licence is NOASSERTION in the API: Apache-2.0 plus a `/proprietary` directory under a separate licence whose terms I could not read ([LICENSE.MD](https://github.com/Dokploy/dokploy/blob/canary/LICENSE.MD)). Some features (SSO, audit logs, custom roles) are Enterprise-only per Coolify's comparison page (**[$]**, a competitor). Lighter on RAM than Coolify per third-party blogs (about 300-400 MB vs 0.5-1.2 GB idle, unverified) ([getdeploying](https://getdeploying.com/guides/coolify-vs-dokploy), [coolify.io compare](https://coolify.io/compare/coolify-vs-dokploy) **[$]**).

### 2.3 Kamal 2

MIT, v2.12.0 (2026-06-18), about 14.7k stars, **zero published security advisories** (GitHub API). It deploys over SSH from your machine or CI, with no control plane on the server. Its `kamal-proxy` gives gapless deploys, a configurable health check (default `/up`, 1 s interval), automatic Let's Encrypt on single-host setups, and host-based routing for multiple apps on one server ([proxy docs](https://kamal-deploy.org/docs/configuration/proxy/)). Rollback is `kamal rollback <version>` using containers already on the host, pruned after 3 days by default ([rollback docs](https://kamal-deploy.org/docs/commands/rollback/)). The docs do not say that rollback works by digest, so you would pin digests through the image tag or reference yourself. Accessories (Postgres, Neo4j) are supported but are basic: no backup or PITR story. Rails-centric docs, but it works for any container. Community guides cover multi-app single-server setups ([Cory Zue](https://coryzue.com/writing/kamal-django), [honest take](https://www.ivanturkovic.com/2026/02/06/honest-take-kamal-rails-deployment/)).

### 2.4 Plain Compose + Caddy/Traefik

Caddy (v2.11.9) gives automatic TLS with a tiny config, and Traefik (v3.7.17) gives Docker-label routing. For five services, Caddy with a static Caddyfile is the smallest moving part. Compose natively provides health checks, `depends_on: condition: service_healthy`, resource limits and restart policies. You write the deploy script yourself (pull by digest, `compose up -d --wait`, smoke test, rollback to the previous digest file). That is about 100 lines of Python, which is fully testable and fits a Python repo.

### 2.5 k3s

k3s needs 2 CPU/2 GB RAM for the control plane alone ([docs](https://docs.k3s.io/installation/requirements)), before workloads. With Neo4j (JVM) and pgvector on a single KVM, that overhead buys nothing: no HA, no scheduling benefit. Pick it only if learning Kubernetes is an explicit goal or you expect to go multi-node soon.

### 2.6 Recommendation matrix

| Option | Attack surface | RAM overhead | Solo toil | Fit |
|---|---|---|---|---|
| Coolify | High (70 advisories) | High | Low initially | Only if isolated and VPN-only |
| Dokploy | High (60 advisories) | Medium | Low initially | Same |
| Kamal 2 | Low | None on host | Medium | Good, with a digest tweak |
| Compose + Caddy + script | Lowest | None | Medium | **Best for this topology** |
| k3s | Medium | 2 GB+ | High | Poor |

If the owner insists on a UI: Coolify, with dashboard ports bound to localhost, reached over WireGuard or Tailscale, latest release, a dedicated host separate from the data stores, and token and SSH-key rotation after every advisory wave (Hostzero's own hardening list says the same).

Also worth knowing: Komodo (moghtech, GPL-3.0, v2.3.4) is a Compose-first, git-synced deployment manager, a middle path. [lower confidence: not evaluated for advisories.]

---

## 3. GitOps and declarative config

A "pull GitOps" controller (Argo/Flux) is overkill without Kubernetes. The single-VPS equivalent is:

- **Desired state in git**: `compose.yaml` per stack, `Caddyfile`, a `releases/<env>.lock` file with image digests (`ghcr.io/org/api@sha256:...`), and SOPS-encrypted env files.
- **Deploy = a reviewed commit that changes a digest.** CI in each app repo opens a PR (or dispatches an event) to vps-ops with the new digest. Merging triggers a deploy job (push model over SSH, or a systemd timer that runs `git pull && deploy --check`). Rollback is `git revert` followed by redeploy.
- **Verify provenance before deploy.** GitHub artifact attestations on the build (`actions/attest`, `subject-digest`) can be verified with `gh attestation verify oci://ghcr.io/... -R owner/repo` ([GitHub docs](https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations/using-artifact-attestations-to-establish-provenance-for-builds)). The page does not claim a SLSA level, so do not claim one either.
- **Drift detection**: a scheduled job (daily) runs `pyinfra --dry` or `ansible --check --diff` for host state, and compares `docker inspect` image digests and compose config hashes against the lock file. It alerts on any difference. Docker daemon settings, sysctl, UFW rules, the sshd config and unit files are the usual drifters.

---

## 4. Host hardening

**Baseline (do in order):**

1. **SSH**: key-only, `PasswordAuthentication no`, `PermitRootLogin no`, `AllowUsers deploy`, modern ciphers by default on current OpenSSH. Admin SSH reachable only via VPN (WireGuard/Tailscale), or an IP allowlist at the Hostinger network firewall. `MaxAuthTries 3`.
2. **Firewall layering.** Docker published ports skip UFW's INPUT chain: Docker's own docs say traffic is diverted in the `nat` table "effectively ignoring your firewall configuration" ([Docker docs](https://docs.docker.com/engine/network/packet-filtering-firewalls/)). Remedies:
   - Publish nothing except Caddy's 80/443. Bind everything else to `127.0.0.1` or private Compose networks (Postgres and Neo4j never publish on `0.0.0.0`).
   - Add the Hostinger-level firewall as the outer layer (Coolify's guidance prefers a provider firewall too).
   - Use the `DOCKER-USER` chain for custom filtering. Docker 29 adds experimental nftables support (`firewall-backend: nftables`), but under it Docker no longer enables IP forwarding or sets a default-drop policy, so validate before adopting ([release notes](https://docs.docker.com/engine/release-notes/29/)).
   - Verify with an external port scan after every change (nmap from outside), and make it a scheduled check.
3. **Intrusion response**: fail2ban is enough for SSH-only exposure. CrowdSec adds crowd-sourced blocklists and HTTP/AppSec scenarios ([docs](https://docs.crowdsec.net/docs/intro)). For Docker, its firewall bouncer must be told to cover `DOCKER-USER`, because the default chain list is INPUT only (a vendor tutorial **[$]**, [LumaDock](https://lumadock.com/tutorials/crowdsec-complete-guide)). Practical pick: fail2ban for sshd now, or CrowdSec with the Caddy bouncer if HTTP abuse shows up in logs. Do not run both banning the same SSH port without thinking through the interaction.
4. **Patching**: `unattended-upgrades` with security origins only (Ubuntu default), `Automatic-Reboot` set to a maintenance window time, mail or webhook report, and `needrestart` configured to not blindly restart Postgres or Neo4j (24.04 restarts services automatically by default) ([Ubuntu docs](https://ubuntu.com/server/docs/how-to/software/automatic-updates/)). Pin Docker via its apt repo and watch release notes: Docker 29 changed the containerd default ulimit (1024), removed Content Trust and deprecated cgroup v1.
5. **CIS**: the CIS Docker Benchmark is at v1.9.0 per CIS (free PDF for non-commercial use) ([CIS](https://www.cisecurity.org/benchmark/docker)). Use `docker-bench-security` or Lynis as a quarterly audit rather than trying to hit 100%. [lower confidence on tool versions]
6. **Container hardening**: non-root `USER`, `read_only: true`, `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, memory and CPU limits on every service. Docker's docs recommend `--memory` with `--memory-swap` equal to it, and warn that containers, not the daemon, get OOM-killed first ([resource constraints](https://docs.docker.com/engine/containers/resource_constraints/)). On 8-16 GB, limits stop Neo4j or an LLM-calling API from starving Postgres.

**Rootless vs userns-remap.** Rootless runs both daemon and containers unprivileged, needs `newuidmap`/`newgidmap` and 65,536 subuids, and has networking and storage constraints ([rootless docs](https://docs.docker.com/engine/security/rootless/)). userns-remap leaves the daemon as root, breaks `--network=host`, `--privileged` and external volume drivers, needs pre-chowned bind mounts, and the doc recommends enabling it on a fresh install ([userns-remap docs](https://docs.docker.com/engine/security/userns-remap/)). The strongest, cheapest measure is running every process as a non-root user with dropped capabilities. For this repo, I would adopt rootless only if a tested spike passes: Caddy on 80/443 (needs `net.ipv4.ip_unprivileged_port_start`), Postgres volume ownership, Neo4j volumes and backups. Otherwise keep rootful Docker with the non-root containers described above. The Docker socket must never be mounted into any app container.

---

## 5. Secrets management

| Option | Model | Self-host | Notes |
|---|---|---|---|
| SOPS + age | Encrypted files in git | None needed | CNCF sandbox since 2023, MPL-2.0, v3.13.3 (2026-07), age v1.3.2 ([SOPS](https://github.com/getsops/sops)) |
| Infisical | Secrets platform | Yes (Compose; MIT core, enterprise features **[$]**) | Another stateful service to patch and back up on the same box |
| Doppler | SaaS | Enterprise only | **[$]** |
| 1Password (service accounts / Connect) | SaaS vault | Connect is self-hosted | **[$]** good if already a user |

Comparison articles agree on the pattern: SOPS for git-centric small teams, Infisical for self-hosting, Doppler or 1Password for zero-ops ([dev.to roundup](https://dev.to/_6638a39c349d7e9c85ee20/best-secrets-management-tools-2026-infisical-vs-doppler-vs-vault-vs-sops-vs-1password-2g39), [Infisical blog](https://infisical.com/blog/hashicorp-vault-alternatives) **[$]**). Pricing figures conflict across sources, so check pricing pages.

Recommended: SOPS+age with `.sops.yaml` creation rules, a recipient list of (a) the engineer's offline key and (b) the server's key. The deploy step decrypts to a `tmpfs` file or `docker compose --env-file` pipe and never writes plaintext to the repo, CI logs or images. Use separate keys for staging and production. Rotation is manual (`sops updatekeys` and `sops rotate`). LLM provider keys should be per-service with provider-side spend caps and a monthly budget alert (see section 9), so a leak is bounded. Run the `secret-serialization` style check on logs and traces (repr leaks), since LLM apps often log whole request objects.

---

## 6. Backups and restore drills

**Rule: 3-2-1 with an off-provider, off-host copy.** The Hostinger snapshot or backup feature is not a backup strategy (same provider, same account). I could not retrieve Hostinger's current snapshot docs (404), so treat their retention as unverified and check in hPanel.

### Postgres (+ pgvector)

- Logical `pg_dump` nightly is a useful second layer: pgvector data restores as normal rows plus an index rebuild, and the dump stays portable across major versions.
- For RPO of minutes, use base backups plus continuous WAL archiving to S3-compatible storage (Backblaze B2, Cloudflare R2, Hetzner Object Storage, or Hostinger-independent).
- **pgBackRest status is contested but resolved by primary evidence.** In April 2026 the maintainer (David Steele, previously sponsored by Crunchy Data, acquired by Snowflake) announced the project unmaintained with 2.58.0 as final ([Notice of Obsolescence](https://thebuild.com/blog/notice-of-obsolescence/), [After pgBackRest](https://thebuild.com/blog/after-pgbackrest/)). However, the GitHub API shows releases 2.59.0 (2026-07-20) through 2.60.0 (2026-10-18), all by the same maintainer, with commits as recent as 2026-11-06 (`pgbackrest` repo, GitHub API). It is maintained again as of today, but the funding and governance behind that are not documented in what I read. 2.59.3 also fixed a weak-encryption-subkey bug affecting encrypted repos if `getrandom()` failed; existing stanzas keep weak subkeys until they expire ([pgBackRest news](https://pgbackrest.org/news.html)).
- **WAL-G** (v3.0.9, 2026-08-20) is object-storage-native with libsodium or PGP encryption, delta backups and WAL push/fetch ([README](https://github.com/wal-g/wal-g)). Encryption is off by default. Barman (EDB) 3.17 is the on-prem-flavoured alternative. [secondary source]
- Pick: WAL-G if you want simplicity with object storage on a single node, pgBackRest if you want its verify and block-incremental features and accept the governance uncertainty. Either way: encryption on, a tested restore.

### Neo4j

Community Edition cannot back up online. `neo4j-admin database dump` works only on an offline database (can stream to stdout or write to S3/GCS/Azure URIs; does not cover users and roles metadata; no TLS) ([Neo4j docs](https://neo4j.com/docs/operations-manual/current/backup-restore/offline-backup/)). Online `neo4j-admin database backup` is Enterprise-only ([planning](https://neo4j.com/docs/operations-manual/current/backup/planning/)). Practical plan for a small graph: nightly stop container, dump to a volume, start container (downtime of seconds to minutes, scheduled in a low-traffic window), then ship with restic. If the graph is derivable from Postgres or source documents, document the rebuild path and measure its time: that is your real RTO. Test that the dump loads into a fresh container of the same Neo4j version. Check whether you are actually on Community: if the license is Enterprise, use online backup.

### Files, configs, volumes

restic (v0.19.1) or borg (1.4.5) to object storage, encrypted client-side, with `restic check --read-data-subset` weekly and a `forget --prune` retention policy. Make the repository append-only or use object-lock/versioned buckets so a compromised host cannot delete history. [lower confidence on immutability specifics; restic's docs TOC did not show an immutability section]

### Restore drills

- **Monthly automated drill** in CI or on a throwaway VM: restore the latest Postgres base+WAL to a target time, run row-count and checksum assertions, `SELECT` a pgvector similarity query, load the Neo4j dump into a temp container and run a sanity Cypher count, and record the elapsed time. Fail loudly and push the result to the status channel.
- Coolify's docs make the point themselves: a successful backup only proves a file exists.
- Store the **age private key and object-store credentials** outside the VPS (password manager and printed offline copy), since the restore procedure depends on them.

---

## 7. Observability on a budget

**Resource tier (recommended):**

- **Beszel** (MIT, v0.21.1, about 27k stars): PocketBase-based hub plus tiny Go agent, host and per-container CPU/memory/network, alerts, OAuth, backups to S3. Vendor-blog claims of about 10 MB agent RAM are unverified ([repo](https://github.com/henrygd/beszel), [comparison](https://futurepicker.com/en/beszel-vs-netdata-vs-uptime-kuma-lightweight-server-monitoring-2026-en/)).
- **Uptime Kuma** (MIT, 2.5.9): external HTTP, TCP and keyword checks of the `/health` and `/ready` endpoints, TLS expiry, push monitors for backup jobs (dead-man's switch). Run it on a different host or provider, or use a free hosted ping (Better Stack, healthchecks.io **[$]**), because monitoring from inside the monitored box cannot see a dead host.
- **Netdata**: more detail, but reported 200-500 MB RAM per agent (third-party) and a SaaS-centred multi-host view. Skip unless you need per-second diagnostics.

**Errors:** GlitchTip is Sentry-SDK compatible and needs Postgres 14+, optional Valkey, and 256-512 MB RAM in all-in-one mode ([install docs](https://glitchtip.com/documentation/install)). Self-hosted Sentry is far heavier (multi-GB, many containers) [lower confidence; I could not fetch their requirements page]. Alternative: Sentry SaaS free tier **[$]** with PII scrubbing and no self-hosted RAM cost.

**Traces and metrics pipeline:** instrument the FastAPI and Next.js apps with OpenTelemetry and export OTLP to a collector. Grafana Alloy is an OTel Collector distribution with built-in Prometheus pipelines and Loki support ([docs](https://grafana.com/docs/alloy/latest/introduction/), v1.21.3, **[$]** Grafana Labs). The official OTel Collector (v0.165.0) is vendor-neutral. SigNoz needs at least 4 GB for Docker alone, runs ClickHouse + Keeper + Postgres, and its Compose install path is deprecated in favour of "Foundry" as of v0.130.0 ([SigNoz docs](https://signoz.io/docs/install/docker/), **[$]**). A Grafana+Prometheus+Loki stack was reported at 20-35% of a 2 GB VPS RAM (vendor claim, **[$]**). Verdict: on a shared single VPS, ship telemetry to a free-tier SaaS (Grafana Cloud free **[$]**, Sentry free **[$]**) or keep it to logs plus metrics via Beszel, and only self-host a backend if you get its resource cost under control with a separate small VM.

**Logs:** JSON logs, `docker logging` driver `local` or `json-file` with `max-size`/`max-file` (prevents disk fill), shipped via Alloy to Loki Cloud if you want search. Add request IDs and propagate trace IDs to LLM calls.

### LLM observability

- **Langfuse** (v4.77.0 as of 2026-11-09): requires Postgres, ClickHouse, Redis/Valkey and S3-compatible blob storage, plus web and worker containers. Langfuse's own docs describe Docker Compose as "local use and testing", a single VM "without high availability, scaling, or backups" ([self-hosting](https://langfuse.com/self-hosting)). Sizing docs list ClickHouse at 2 CPU/8 GiB, web/worker 2 CPU/4 GiB each ([scaling](https://langfuse.com/self-hosting/scaling)). That does not fit beside Postgres + Neo4j on one budget VPS. Use Langfuse Cloud **[$]** (free/hobby tier) or LangSmith **[$]** for traces, or log token usage and cost per request to your own Postgres plus a simple dashboard.
- Minimum LLM ops regardless of tool: per-request token/cost counters, per-tenant and global daily spend caps enforced in the app (hard stop and alert), provider-side budget limits, timeout and retry budgets, a kill-switch env flag, and PII redaction before export.

---

## 8. SLOs, alerting, runbooks, DR

**SLOs (few, honest):**

- API availability: 99.5% monthly (about 3.6 h/month of budget) for a single VPS. 99.9% is not credible with one host and provider maintenance.
- API latency: p95 for non-LLM endpoints, plus a separate time-to-first-token SLO for LLM endpoints.
- Freshness SLO for backups: last successful base backup under 26 h, WAL archive lag under 5 min.

**Alerting:** Google's SRE workbook gives multi-window multi-burn-rate rules for a 99.9% SLO: page at burn 14.4 over 1 h/5 min (2% budget), page at burn 6 over 6 h/30 min (5%), ticket at burn 1 over 3 days/6 h (10%), with the short window about 1/12 of the long one ([SRE Workbook](https://sre.google/workbook/alerting-on-slos/)). For low-traffic services, a single failed request can look like a 1000x burn, so the book recommends synthetic traffic, grouping related services, or longer windows. Solo-dev translation: send only 4-5 alerts to the phone (host down or 5xx burn, backup stale, disk above 85%, certificate under 7 days, LLM spend above 80% of cap), and everything else to a daily digest. Pager channel: ntfy, Telegram or Pushover, with Uptime Kuma as an out-of-band prober.

**Runbooks (markdown in vps-ops, one file per alert, linked from the alert text):** host unreachable, disk full, Postgres down or corrupt, restore-from-backup (Postgres PITR, Neo4j dump), bad deploy rollback, expired cert, leaked secret (rotation order: provider key, then SOPS recipients, then redeploy), LLM runaway spend, Docker daemon upgrade failure. Every runbook has a "last tested" date, tied to the drills.

**DR targets (proposal, to be confirmed with the owner):**

- Postgres: RPO 5-15 min (WAL), RTO 2 h to a fresh VPS.
- Neo4j: RPO 24 h (nightly dump) unless rebuildable, RTO 2-4 h.
- Everything else: RPO 0 (git and registry), RTO under 1 h by re-converging a new VPS with Ansible or pyinfra, `restic restore`, `compose up` by digest.
- A **fresh-VPS rebuild drill** twice a year is the real test. Keep a cold-standby DNS TTL of 300 s.

**Cost (indicative; check current prices):** a Hostinger KVM 4 or 8 plan plus object storage (B2/R2 is a few dollars per month for tens of GB) plus free tiers for monitoring and errors keeps infra low double digits per month, excluding LLM spend. Money saved by skipping Langfuse, SigNoz and Coolify's RAM (several GB) can instead buy one smaller second VM for monitoring and the off-host dead-man's switch.

---

## 9. Infra testing, automation tools, drift

[lower confidence section: relies on tool docs and prior knowledge, not fresh searches]

- **Ansible (v2.22.0) vs pyinfra (v3.11.0, MIT):** pyinfra writes deploys as plain Python, is agentless over SSH, idempotent, has `--dry` per-host diffs, and claims 6x speed over Ansible (vendor claim) ([pyinfra.com](https://pyinfra.com/)). Ansible has the larger ecosystem, `community.docker`, Molecule integration, and hardening roles (for example the dev-sec collection). For a Python-first single-host repo where the engineer prefers code over YAML, pyinfra is attractive. If you want ready-made roles (CIS-style hardening, fail2ban, unattended-upgrades), Ansible saves time. Both work. Pick one, not both. My lean: Ansible for host convergence because hardening roles exist and Molecule can test them, and a small Python CLI for app deploys.
- **Tests:** testinfra (pytest-based; last release 10.2.2 in March 2025, so slow-moving), Goss (v0.4.10, YAML specs, fast, `goss serve` for health endpoints), InSpec, and Molecule (v26.11.0, active) to run converge/verify cycles in containers or a throwaway VM. For one host, a pragmatic stack is: pytest + testinfra for post-converge assertions (sshd config, UFW state, docker daemon.json, no public ports other than 80/443/22 via a scan, unattended-upgrades enabled), and Molecule or a Hetzner/Multipass VM in CI for converge tests. Add a post-deploy smoke test suite hitting `/health`, `/ready` and one authenticated end-to-end path per app.
- **Drift detection:** scheduled `--check` run plus digest comparison (section 3). Alert, do not auto-fix, unless the drift is on an allowlisted item.

---

## 10. vps-ops repository structure

```
vps-ops/
  inventory/            host vars (non-secret); secrets/ as SOPS-encrypted files
  host/                 Ansible (or pyinfra) roles: base, ssh, firewall, docker, caddy, backups, monitoring
  stacks/
    edge/               Caddyfile, compose (Caddy only publishes 80/443)
    data/               postgres, neo4j (internal network only), backup sidecars
    apps/               compose per app, referencing ${IMAGE_DIGEST}
  releases/
    production.lock     name -> ghcr.io/...@sha256:...  (the only file CI bots edit)
  deploy/               Python CLI: plan, apply, rollback, smoke (pytest-tested)
  tests/                testinfra, smoke, backup-restore drill
  runbooks/             one file per alert
  docs/adr/             decisions (platform choice, DR targets)
  .github/workflows/    lint, test, drift-check (scheduled), restore-drill (scheduled), deploy (manual approval)
  .sops.yaml  Makefile  pyproject.toml (uv, ruff, ty)
```

Conventions: pin all third-party images by digest as well (Renovate or Dependabot opens bump PRs); pre-commit with `sops` check, secret scanning and `compose config`; GitHub environment protection with required reviewer on `deploy`; OIDC or a deploy-only SSH key with a forced command (`command="..."` in `authorized_keys`), never a root key in CI.

---

## 11. Release coordination with app repos (deploy contract)

**Contract each app repo must satisfy** (documented in `vps-ops/docs/deploy-contract.md`):

1. Image is built once in CI, pushed to GHCR, attested, and referenced by `@sha256` digest. Tags are informational only.
2. `GET /health` (liveness, no dependencies) and `GET /ready` (checks Postgres/Neo4j and migrations state). The returned body includes `version` (git SHA) and `schema_version`.
3. Env var schema published as a file (names, required, secret or not) so vps-ops can validate before deploy.
4. DB migrations are backward-compatible for at least one release (expand/contract). Migrations run as an explicit pre-deploy job, not at container start, and are gated by a fresh backup or PITR marker.
5. Graceful shutdown on SIGTERM, with a `stop_grace_period` matching drain time.

**Deploy flow:** app CI builds and attests, then opens a PR to `releases/production.lock`. vps-ops CI verifies attestation, runs compose config lint and the smoke suite against the target. Approval, then `deploy apply`: record the previous lock, pull by digest, run the migration job, `compose up -d --wait` (health-check gated), then smoke tests. On failure it auto-reverts to the previous digests (and does **not** auto-revert migrations: hence expand/contract). After success, write a deploy marker event to monitoring and the git tag.

**Rollback:** previous digest set is always stored in git and kept in the local image cache (do not `docker image prune -a` immediately, because Kamal-style 3-day retention is a sensible model). A rollback drill occurs with every restore drill.

**Compose vs Kamal on this point:** kamal-proxy gives a built-in gapless switchover, while plain Compose has a brief restart window unless you run blue/green behind Caddy yourself. For two internal-ish backoffices and two assistant APIs, a few seconds of restart is usually acceptable. If not, use Kamal's proxy or a two-slot Caddy upstream pattern.

---

## 12. Recommendations for vps-ops (prioritised)

**Now (week 1-2)**

1. Decide: **no Coolify/Dokploy on the data host.** If Coolify is already installed: update to latest, bind 8000/6001/6002 to localhost, put the dashboard behind WireGuard/Tailscale, rotate SSH keys, API tokens and DB credentials (especially if it ever ran at or below the January 2026 vulnerable versions), disable unused OAuth providers, and plan migration to Compose.
2. Verify exposure from outside: `nmap` the VPS. Only 22 (restricted), 80 and 443 should answer. Databases bound to localhost or internal networks only.
3. Turn on the Hostinger network firewall as the outer layer, SSH key-only, `unattended-upgrades` with reboot window, `fail2ban` for sshd.
4. Set per-service memory/CPU limits, `no-new-privileges`, `cap_drop: ALL`, non-root users. Log rotation limits.
5. Implement **off-host encrypted backups** (restic to B2/R2) plus Postgres WAL archiving (WAL-G, or pgBackRest if you accept the governance note). Neo4j nightly offline dump. Add dead-man's-switch pings to Uptime Kuma or healthchecks.io.

**Next (week 3-6)**
6. Do a first **restore drill** (fresh VM or container) and record real RPO/RTO. Automate monthly.
7. Move deploy state into `releases/production.lock` with digests plus attestation verification. Write the deploy-contract doc and apply it to the four app repos.
8. SOPS+age for all secrets, with two recipients. Remove plaintext `.env` from the server except tmpfs-rendered copies.
9. Install Beszel + Uptime Kuma, GlitchTip (all-in-one) or Sentry SaaS, 5-alert paging policy, runbooks per alert.
10. App-side LLM cost telemetry, spend caps and a kill switch. Use a hosted Langfuse/LangSmith tier or Postgres tables rather than self-hosting Langfuse on this box.

**Later**
11. Drift-check job (daily), testinfra assertions, Molecule or VM converge test for host roles. Quarterly CIS/Lynis review.
12. Evaluate rootless Docker in a spike. Evaluate Docker 29 nftables backend in staging first.
13. Second small VM (cheap) for monitoring and Uptime Kuma, and as a warm DR target.
14. Reassess Kamal 2 or Komodo if the number of services grows or zero-downtime switchover becomes a requirement.

---

## 13. Contested / uncertain

- **pgBackRest**: announced unmaintained 2026-04-26; yet 2.59.0-2.60.0 shipped Jul-Oct 2026 from the same maintainer. Funding and long-term status unknown. Several 2026 blog posts still say "archived" or "unmaintained", and they are stale. The pull request history, not blog posts, is the evidence to track.
- **Coolify CVE counts**: my primary count (70 advisories on the GitHub API, including draft-to-published batches, with only first five pages read) differs from Hostzero's 20 and aggregator counts of 28. Counting differences come from batching, low-severity items and republished advisories. The qualitative conclusion (authenticated-to-root bug class, recurring) is solid. Hostzero's later CVE IDs and dates look inconsistent, so I do not rely on them. No confirmed in-the-wild exploitation was found as of its writing, but that is an absence-of-evidence claim.
- **Dokploy licence**: Apache-2.0 plus a proprietary directory whose terms I did not read. Competitor comparison (Coolify **[$]**) says production use may need an agreement, which I could not confirm.
- **RAM figures** for Beszel, Netdata, Coolify, Dokploy and Grafana stacks come from third-party or vendor blogs and are unverified. Benchmark yourself on the VPS.
- **Rootless Docker for this stack**: the compatibility of Caddy low ports, Neo4j/Postgres volume ownership and backup tooling is untested here. Treat it as a spike, not a recommendation.
- **Ansible vs pyinfra**, testinfra vs Goss, GlitchTip vs Sentry sizing, and Komodo's security record: lower confidence because the search budget ran out. Verify before committing.
- **Langfuse sizing**: official sizing is for production-scale, and a small-volume instance might run in less, but the Compose path is explicitly not production-grade per Langfuse. I found nothing verifying a rumoured 2026 ClickHouse acquisition of Langfuse; do not rely on it.
- **Hostinger specifics** (snapshot/backup retention, network firewall availability on your plan): could not fetch; check hPanel.
- **SLO numbers** are proposals for one non-redundant VPS, not measured baselines.

---

## 14. Sources

Security, platforms

1. Coolify security advisories via GitHub API, `coollabsio/coolify` (primary, pulled 2026-11-09). https://github.com/coollabsio/coolify/security/advisories
2. Dokploy security advisories via GitHub API (primary). https://github.com/Dokploy/dokploy/security/advisories
3. Kamal advisories (none found) and releases via GitHub API. https://github.com/basecamp/kamal
4. Belgium CCB advisory on Coolify. https://ccb.belgium.be/advisories/warning-critical-coolify-vulnerabilities-patch-immediately
5. Hostzero, "Is Coolify safe" (hosting vendor **[$]**). https://hostzero.com/articles/is-coolify-safe-2026-cves
6. Censys advisory on CVE-2025-64424/64420/64419 (security vendor **[$]**). https://censys.com/advisory/cve-2025-64424-cve-2025-64420-cve-2025-64419
7. Coolify docs, firewall. https://coolify.io/docs/knowledge-base/server/firewall
8. Coolify docs, database backups. https://coolify.io/docs/databases/backups
9. Coolify vs Dokploy (competitor **[$]**). https://coolify.io/compare/coolify-vs-dokploy
10. getdeploying, Coolify vs Dokploy. https://getdeploying.com/guides/coolify-vs-dokploy
11. Dokploy LICENSE.MD. https://github.com/Dokploy/dokploy/blob/canary/LICENSE.MD
12. Kamal proxy docs. https://kamal-deploy.org/docs/configuration/proxy/
13. Kamal rollback docs. https://kamal-deploy.org/docs/commands/rollback/
14. Cory Zue, Kamal multi-app Django. https://coryzue.com/writing/kamal-django
15. Ivan Turkovic, honest take on Kamal. https://www.ivanturkovic.com/2026/02/06/honest-take-kamal-rails-deployment/
16. k3s requirements. https://docs.k3s.io/installation/requirements
17. Komodo repo (GitHub API: GPL-3.0, v2.3.4). https://github.com/moghtech/komodo

Host hardening
18. Docker, packet filtering and firewalls. https://docs.docker.com/engine/network/packet-filtering-firewalls/
19. Docker Engine 29 release notes. https://docs.docker.com/engine/release-notes/29/
20. Docker rootless mode. https://docs.docker.com/engine/security/rootless/
21. Docker userns-remap. https://docs.docker.com/engine/security/userns-remap/
22. Docker resource constraints. https://docs.docker.com/engine/containers/resource_constraints/
23. CIS Docker Benchmark page. https://www.cisecurity.org/benchmark/docker
24. Ubuntu automatic updates. https://ubuntu.com/server/docs/how-to/software/automatic-updates/
25. CrowdSec docs. https://docs.crowdsec.net/docs/intro
26. LumaDock CrowdSec guide (hosting vendor **[$]**). https://lumadock.com/tutorials/crowdsec-complete-guide
27. GitHub artifact attestations docs. https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations/using-artifact-attestations-to-establish-provenance-for-builds

Secrets
28. SOPS repo. https://github.com/getsops/sops
29. Secrets tools roundup 2026 (blog). https://dev.to/_6638a39c349d7e9c85ee20/best-secrets-management-tools-2026-infisical-vs-doppler-vs-vault-vs-sops-vs-1password-2g39
30. Infisical, Vault alternatives (**[$]**). https://infisical.com/blog/hashicorp-vault-alternatives

Backups
31. The Build, "Notice of obsolescence" (pgBackRest). https://thebuild.com/blog/notice-of-obsolescence/
32. The Build, "After pgBackRest". https://thebuild.com/blog/after-pgbackrest/
33. pgBackRest repo and news (releases 2.59.x-2.60.0, weak-encryption notice). https://github.com/pgbackrest/pgbackrest , https://pgbackrest.org/news.html
34. WAL-G repo. https://github.com/wal-g/wal-g
35. Neo4j, offline backup (dump). https://neo4j.com/docs/operations-manual/current/backup-restore/offline-backup/
36. Neo4j, backup planning. https://neo4j.com/docs/operations-manual/current/backup/planning/
37. restic docs. https://restic.readthedocs.io/en/stable/

Observability, LLM, SLOs
38. Beszel repo. https://github.com/henrygd/beszel
39. Beszel vs Netdata vs Uptime Kuma (blog, uses affiliate-style content **[$]**). https://futurepicker.com/en/beszel-vs-netdata-vs-uptime-kuma-lightweight-server-monitoring-2026-en/
40. GlitchTip install docs. https://glitchtip.com/documentation/install
41. Grafana Alloy intro (**[$]**). https://grafana.com/docs/alloy/latest/introduction/
42. SigNoz Docker install (**[$]**). https://signoz.io/docs/install/docker/
43. Langfuse self-hosting overview (**[$]**). https://langfuse.com/self-hosting
44. Langfuse scaling and sizing (**[$]**). https://langfuse.com/self-hosting/scaling
45. Google SRE Workbook, alerting on SLOs. https://sre.google/workbook/alerting-on-slos/

Automation and testing
46. pyinfra (project site, vendor claims). https://pyinfra.com/
47. Release data via GitHub API for Ansible, Molecule, Goss, testinfra, Caddy, Traefik, restic, borg, age, Uptime Kuma, SigNoz, OTel Collector, Infisical, Alloy, k3s (primary, 2026-11-09).
