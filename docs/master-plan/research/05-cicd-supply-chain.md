# 05 - Best-in-class CI/CD and software supply chain in 2026 for a solo engineer (7 repos)

Date: 2026-11-09. Scope: GitHub Actions design, supply chain, release automation, vulnerability SLAs.
Method note: ~45 sources via search and fetch. The session web-search budget ran out near the end, so three points rest on my prior knowledge and are flagged **[unverified]**. Sources with commercial interest are tagged **[C]** in the source list. Primary docs (GitHub, SLSA, OpenSSF) are weighted over vendor blogs.

---

## 1. What changed in 2025-2026 (the threat model you are designing against)

1. **Mutable tags are the attack surface.** tj-actions/changed-files (CVE-2025-30066, March 2025) had its tags re-pointed to a malicious commit that dumped runner secrets into logs; it was reached via the earlier reviewdog compromise (CVE-2025-30154) [S1][S2]. In March 2026 the same pattern hit `aquasecurity/trivy-action` (76 of 77 tags force-pushed) and `setup-trivy`, plus a Trivy binary release and Docker Hub images; root cause was an incomplete credential rotation after a late-February foothold via a GitHub Actions misconfiguration [S3][S4]. Aqua itself notes that GitHub's "Immutable" badge did not stop the tag rewrites and that full-SHA pinning "remains the only truly immutable protection" [S3] (vendor, but consistent with the tj-actions facts).
2. **Provenance does not mean safe.** In the Shai-Hulud 2.0 and "Mini Shai-Hulud" npm waves (Nov 2025, 2026), malicious packages carried valid provenance because attackers abused `pull_request_target` "pwn request" workflows that held OIDC publish rights [S5][S6]. Trusted publishing removed long-lived tokens but moved the target to the workflow. Lesson: attestations prove *where* something was built, so the build workflow itself must be hardened.
3. **GitHub is moving platform controls in.** SHA-pinning enforcement as an allowed-actions policy (Aug 2025, `sha_pinning_required`) [S7]; immutable releases GA (Oct 2025) [S8]; Dependabot cooldown GA (July 2025) and now a 3-day default for version updates [S9]; the March 2026 Actions security roadmap (dependency locking, ruleset-based execution policy, scoped secrets, native egress firewall) - **none GA when published; preview windows 3-9 months** [S10]. Treat all roadmap items as "watch, do not depend on".
4. **SLSA v1.2** (Nov 2025) added a Source track; v1.1 is marked retired but the Build track levels are unchanged and backward compatible [S11][S12].
5. **Pricing:** hosted-runner prices fell up to 39% on 1 Jan 2026 with a built-in $0.002/min platform charge; the self-hosted-runner charge was postponed; public-repo standard runners stay free [S13]. For a solo dev the practical effect is small, but minutes still matter for private repos.

---

## 2. GitHub Actions pipeline design

### 2.1 Job graph

Recommended shape for every repo (names are stable because they become required checks):

```
changes (paths filter) ──┬─> lint-typecheck ──┐
                         ├─> unit-test (shard) ┼─> build (once) ──> [e2e | image scan | attest] ──> ci-gate
                         └─> security (codeql / osv / zizmor / gitleaks)
```

- **One aggregate "ci-gate" job** (`if: always()`, `needs: [...]`, fails on any `failure`/`cancelled`) is the *only* required status check. This decouples rulesets from job renames, sharding changes and path-filtered skips (a skipped required job otherwise blocks merge or silently passes depending on config). This is the single most useful structural pattern for a small repo set and works identically under `pull_request` and `merge_group`.
- **Path filters at the job level, not workflow level**, via a `changes` job (e.g. dorny/paths-filter or `git diff`), so the gate always reports. Workflow-level `paths:` makes required checks "pending forever" when skipped.
- **`concurrency` groups** with `cancel-in-progress: true` for PRs, never for `main`/release/deploy workflows.
- **Least privilege by default:** top-level `permissions: {}` or `contents: read`, widen per job. This is also what Scorecard's Token-Permissions check rewards [S14].
- **Pin every `uses:` to a full SHA with a version comment**, let Dependabot/Renovate bump both (Scorecard confirms Dependabot updates the hash and the comment) [S14][S15]. Turn on the repo/org policy that *requires* full-SHA pins [S7]. Caveat from testers: it covers `uses:` for actions only, local actions are out of scope, and reusable-workflow calls may still use tag refs [S7], so keep `zizmor` (unpinned-uses) as the second layer.
- **`persist-credentials: false`** on checkout unless the job pushes (zizmor `artipacked`), no `pull_request_target`/`workflow_run` that checks out PR head, no `${{ }}` of untrusted context in `run:` (template-injection) [S16][S14].

### 2.2 Build once, reuse

- Build the artifact (Next.js `.next`/standalone output, or Docker image) in ONE job, upload via `actions/upload-artifact` (or push the image by digest) and have e2e/scan/attest jobs *consume that exact artifact*. For APIs: build image once in CI, scan and test that digest, then **promote the same digest** to the registry tag and to Coolify. Never rebuild at deploy time - the digest you tested is the digest you ship.
- Coolify supports image deploys by tag or by SHA256 digest (64 hex chars, no `sha256:` prefix, do not set both) and recommends tag/digest over `latest` in production [S17]. Its documented GitHub Actions flow is "push image, then call the deploy webhook/API" [S18]. **Inference, not documented:** a digest-pinned resource needs its digest field updated through the Coolify API before the webhook fires, otherwise it redeploys the old pin. Verify in a staging app before committing the design.
- Docker: `docker/build-push-action` + `setup-buildx-action`, `cache-from/to: type=gha,mode=max` with a **distinct `scope` per image** (caches are branch-scoped and same-scope images overwrite each other) [S19]. BuildKit attaches provenance/SBOM through `provenance:` / `sbom:` (`attests:`) inputs [S19].

### 2.3 Caching

- Language caches via `actions/setup-node` (`cache: npm|pnpm`) keyed on the lockfile. Cache **package-manager stores, not `node_modules`**. Add framework caches (`.next/cache`, keyed on lockfile + source hash) for Next.js builds.
- Only the default branch should *write* the broad caches; PR caches are not readable by sibling branches, so a PR-only cache wastes quota. GHA cache is 10 GB per repo (my knowledge, **[unverified]** this session) so prune with scoped keys.
- Remote build caches (Turborepo, Nx) only if a repo is a monorepo; for 7 small repos GHA cache is enough.

### 2.4 Sharding and duration budgets

- Shard only what exceeds budget. Playwright: `--shard=i/n` in a matrix, merge blob reports in a final job; Vitest/Jest: `--shard`. Fail-fast off for test matrices so you see all failures.
- **Budgets (recommended, not an industry standard):** PR critical path p50 <= 5 min, p95 <= 10 min; lint+typecheck <= 2 min; image build with warm cache <= 4 min. Alert (a weekly summary job using `gh run list --json` or a simple workflow-duration annotation) when p95 drifts >25% over a 4-week baseline. When over budget: first fix cache hit rate, then split jobs, then shard, then (last) paid larger runners.
- Skip expensive jobs on docs-only changes through the `changes` job; run full e2e on `main`/release PRs and a smoke subset on feature PRs.

### 2.5 Merge queue vs strict status checks

- A merge queue tests the PR merged onto the latest base plus queued PRs, but **requires `merge_group` as a workflow trigger or required checks never report and the queue stalls**; it cannot be enabled on wildcard-named branch protection rules; third-party CI must listen to `gh-readonly-queue/...` branches [S20]. Rulesets that require workflows also need `merge_group` [S21].
- **Availability:** the page I fetched does not state plan/visibility limits. From prior knowledge, merge queue historically required an organization-owned repo (not a personal-account repo) and, for private repos, a paid plan **[unverified, check before planning]**. Your repos live under `gonzalomartinperez/...` (a user namespace), which would exclude them.
- **Recommendation for a solo engineer:** do NOT adopt merge queue. With one author there are no concurrent PRs to serialize; "Require branches to be up to date" (strict) in the ruleset gives the same guarantee at the cost of an occasional "Update branch" click. Revisit only if you add contributors or if CI >15 min makes manual rebasing painful. The develop→main release PR is the one place the strict setting matters most (main must equal tested develop).

### 2.6 Flaky test policy

No authoritative standard exists; the 2016 Google figures (≈1.5% of runs flaky, ≈16% of tests touched, 84% of retried failures flaky) are quoted second-hand [S22][S23]. A defensible policy for one engineer:

1. No blanket CI retries on unit tests. Playwright `retries: 1` in CI only, and a test that passes on retry is *recorded as flaky* (Playwright reports it) - it is not "green".
2. A flaky test gets a tracked issue labelled `flaky`, quarantined (tagged skip/`test.fixme` with issue link) the same day; **fix-or-delete within 7 days**; quarantine cap 2% of tests or 5, whichever is smaller [S22].
3. Weekly digest: count of `flaky` retries from reports; if first-attempt failure rate on `main` > 2% over 20 runs, stop feature work and fix.
4. Never quarantine silently: the quarantined set is a list in the repo.

### 2.7 Reusable workflows, org-level sharing, and a central "standards" repo

- Mechanism today: **reusable workflows** (`workflow_call`) in a central repo, called from each repo with `uses: owner/standards/.github/workflows/x.yml@<SHA>`; plus **composite actions** for step-level reuse; plus **repository/organization rulesets** with the "require workflows to pass" rule, GA since Oct 2023, which replaced the legacy "required workflows" [S21][S24]. Org/enterprise-level ruleset workflows are described for org-owned repos; **a user-namespace owner has no org-level ruleset**, so each repo gets the same ruleset applied by script (see below) [S21; org-ruleset scope is **[unverified]** for user accounts].
- Private reusable workflows can only be called by repos in the same user/org with explicit "Accessible from repositories..." enabled; public ones are callable by anyone, which is also a supply-chain consideration if you consume your own standards repo by SHA.
- **Central "standards" repo contents (recommended):**
  - `.github/workflows/`: `ci-node.yml`, `ci-docker-api.yml`, `security.yml` (zizmor, gitleaks, osv-scanner, dependency-review), `release.yml`, `attest-image.yml`.
  - `rulesets/*.json` + a `scripts/apply-rulesets.sh` using `gh api` (idempotent) so all 7 repos converge; run weekly in "drift report" mode.
  - Templates: `dependabot.yml`, `SECURITY.md`, PR template, `release-please-config.json`, `.gitleaks.toml`, CODEOWNERS.
  - Consumers pin by SHA and Dependabot bumps the standards SHA across the 7 repos (one grouped PR per repo). Treat standards-repo changes as high-blast-radius: PR, CI, and a canary repo first.
- Caveat: SLSA Build L3 via a reusable workflow means the *called workflow* signs provenance in isolation from the caller's steps [S25][S26]; the identity in the attestation is then the standards workflow path, so `gh attestation verify --signer-workflow owner/standards/.github/workflows/attest-image.yml` is how you pin the verifier.

### 2.8 Rulesets and required checks

- Use **rulesets, not classic branch protection** (Scorecard reads both; classic rules need a privileged token to be read) [S14].
- Ruleset for `main`: PR required (release PRs from develop), required check = `ci-gate`, strict up-to-date, block force-push/deletion, linear history optional, **no bypass actors** (consistent with your "never --admin" rule), signed commits optional. For `develop`: PR required, `ci-gate`, force-push blocked.
- Add a **tag ruleset** for `v*` (restrict creation/update/deletion) so release tags cannot be moved; this complements immutable releases.
- Scorecard honesty: Branch-Protection tops out around tier 3 (8/10) without a second reviewer, and Code-Review scores 0 for self-merged PRs (bot reviews do not count) [S14][S27]. Do not contort the process for those points; document the ceiling.

---

## 3. Supply-chain controls, ranked by value per effort for 7 repos

### Tier 1 - do now (hours, high value)

1. **SHA pin everything + enforcement policy + zizmor + actionlint in CI** (you already have this; add the repo-level `sha_pinning_required` policy as a backstop) [S7][S16]. zizmor's online audits need a token; zizmor-action enables them by default [S16].
2. **`permissions` hardening** (read-only default; `id-token`/`attestations`/`packages` write only on the build job).
3. **Dependabot with cooldown and groups** (section 5).
4. **gitleaks** in CI plus GitHub push protection and secret scanning on (free for public repos).
5. **CodeQL default setup**: includes the `actions` language (GA Apr 2025) that flags workflow injection/permission issues, plus JS/TS [S28]. Free for public repos; private repos need GitHub Code Security (paid) **[unverified for current pricing]**, so on private Pequeverso repos rely on zizmor + osv-scanner + semgrep-style tooling if CodeQL is unavailable.
6. **Immutable releases** switched on in the repo setting for repos that publish GitHub Releases: assets and tags are locked, and each release gets a Sigstore-bundle attestation; only *new* releases are covered and existing ones must be republished [S8]. Enable it before the first public release of each portfolio repo.

### Tier 2 - do for repos that ship binaries/images (API and backoffice images)

7. **Artifact attestations**: `actions/attest-build-provenance` (and `actions/attest` for SBOMs) with `id-token: write`, `attestations: write`, `contents: read`, plus `packages: write` for images; images pass `subject-name` + `subject-digest` + `push-to-registry: true` [S29][S30]. Verify with `gh attestation verify oci://IMAGE@sha256:... -R owner/repo` (add `--predicate-type` for SBOMs) [S29].
   - Public repos use Sigstore Public Good (entries in the public transparency log); private repos use GitHub's own Sigstore instance without a transparency log [S25]. Private-repo attestations may require an Enterprise Cloud plan **[unverified; the fetched page lists no plan table]**, so test on the smallest private repo before standardizing.
   - **Claim L2 honestly:** attestations alone give SLSA v1.0 Build L2; L3 needs the build in a reusable workflow isolated from the caller [S25][S26]. A separate guide that routes L3 through slsa-github-generator is the older approach [S31]. With your central standards repo, an `attest-image.yml` reusable workflow is the cleanest route to L3 and costs little. Pin the workflow by SHA.
2. **Deploy-by-digest gate:** the deploy job (or a Coolify pre-step) runs `gh attestation verify` against the digest and your standards workflow identity before updating Coolify. This turns attestations from decoration into a control. Note the Shai-Hulud lesson: it only proves provenance, so keep the build workflow free of untrusted-input triggers [S5].
3. **SBOM:** generate with **Syft** (CycloneDX JSON primary, SPDX 2.3 export only if someone asks); consensus favours CycloneDX for security tooling and SPDX for licence/compliance requests; SPDX 3.0 export is reported immature in Syft (single ADR, **[unverified]**) [S32][S33]. Attach as an attestation (`actions/attest` with the SBOM predicate) or via BuildKit `sbom: true`; check which format BuildKit actually emits in your version [S19]. Scorecard has an SBOM check (medium) [S27].
4. **Image scanning:** Grype or Trivy against the *built digest* in CI, fail on fixable High/Critical. **Trivy caveat:** after the March 2026 incident, if you use `trivy-action` pin by SHA to a post-incident release (v0.35.0 or later per Aqua) and run the scanner as a pinned binary/container, with egress restricted; or prefer Grype to diversify [S3][S4]. Vendor note: Aqua [C] and Anchore (Syft/Grype) [C] both sell products.
5. **Cosign vs GitHub attestations:** for a solo operator on GitHub, **`attest-build-provenance` is simpler** (no key mgmt, built-in `gh attestation verify`). Use cosign keyless only if a consumer outside GitHub (Kubernetes admission, Docker policy) expects cosign signatures. Cosign v3 writes the protobuf bundle format by default and needs `cosign-installer` v4 [S34]. Do not do both by default.

### Tier 3 - nice to have / selective

 1. **dependency-review-action** on PRs: fails on new vulns above a severity and checks licences (`allow-licenses`); works on public repos, and private repos need a GitHub Advanced Security licence [S35]. It only diffs a PR, so it is a regression gate, not a full scan.
 2. **osv-scanner** (scheduled full scan + PR regression mode via its reusable workflows) as the free, licence-neutral complement, and the same OSV data Scorecard's Vulnerabilities check uses [S36][S27]. Reasonable combination: dependency-review (public repos) or osv PR mode (private) on PRs, osv scheduled weekly everywhere, Dependabot alerts for ongoing advisories.
 3. **VEX:** only worth producing if you publish images that consumers scan. Use OpenVEX (`vexctl`) statements when a scanner reports a CVE you have shown unreachable; commit `.vex/` or attach as attestation. For private Pequeverso images it is overhead; use `osv-scanner.toml`/`.trivyignore` with expiry dates and an issue link instead.
 4. **harden-runner (StepSecurity [C]):** audit mode first, then egress `block` with `allowed-endpoints` for build/publish jobs; block mode now covers Linux, macOS and Windows hosted runners (v2.20+), `denied-endpoints` since v2.21 [S37]. CVE-2026-25598 was a detection bypass affecting **audit mode only**, so keep it patched and do not rely on audit mode against hostile input [S37]. Because the vendor sells a SaaS dashboard and GitHub plans a native egress firewall [S10], start with harden-runner only on jobs that hold secrets (publish/deploy) and re-evaluate when the native firewall ships.
 5. **OpenSSF Scorecard** weekly action publishing SARIF + badge for the *public portfolio repos*. Highest-leverage checks that you can actually max: Dangerous-Workflow (critical), Token-Permissions, Pinned-Dependencies, Dependency-Update-Tool, SAST, Security-Policy, Signed-Releases (a `.intoto.jsonl` provenance file on each release = 10), Vulnerabilities, Maintained, License, Packaging, SBOM [S27]. Accept the ceiling on Code-Review/Branch-Protection for a solo repo, and do not chase Fuzzing/CII badge unless cheap. Use the score as a regression alarm (fail if it drops >1 point), not a vanity target.

### SLSA positioning (a one-line claim you can defend)

- Target **Build L2 now, L3 for images via the shared reusable workflow**; Source track (v1.2): you can honestly claim roughly L1-L2 (VCS + history + provenance of changes) and should not claim L3/L4, since L4 requires two-person review [S11][S12].

---

## 4. Immutable releases, tags and versions

- Immutable releases: locked assets, protected tags, signed attestation per release, and Scorecard's Pinned-Dependencies treats an action tag backed by an immutable release as pinned [S8][S27]. But **third-party actions' tags are not immutable unless the maintainer turned it on**; Aqua observes the badge did not prevent the Trivy rewrite [S3] (the exact interplay is not fully documented, so treat it as "do not rely"). SHA pins remain the rule.
- Your own images: tag as `vX.Y.Z` and *always* deploy by digest; keep `latest` out of production. Use `docker buildx imagetools` or `crane` to record the digest in the release notes.

---

## 5. Dependabot vs Renovate and an update policy for a solo dev

**Facts**

- Dependabot `cooldown`: delays version updates N days after release; default 3 days even if unconfigured; **does not apply to security updates**; supports `default-days` and `semver-{major,minor,patch}-days`; `include`/`exclude` lists (exclude wins) [S9]. A Japanese secondary source reports wildcard groups can bypass cooldown (single source, unverified) [S38]; test with one repo.
- Dependabot `groups` (`patterns`, `update-types`, `dependency-type`, `group-by`) and `multi-ecosystem-groups` cut PR counts [S9][S39].
- Renovate: native automerge, stronger lockfile/monorepo handling, 90+ managers vs ~30, `minimumReleaseAge`; Dependabot needs a workflow with `dependabot/fetch-metadata` to automerge [S40][S41]. A Socket analysis of the axios 1.14.1 compromise says Renovate automerged the bad version ~56 min after publish, which is the case for release-age delays on any bot [S42] (Socket [C]).

**Recommendation: stay on Dependabot** for all 7 repos. Reasons: you are GitHub-only, it needs no extra app/token, it understands Actions SHA+comment pins, security updates ignore cooldown so you still get fast fixes, and the standards repo can push one `dependabot.yml`. Switch to Renovate only if lockfile-maintenance churn or Docker digest pin updates become painful. (If you do migrate, Renovate's `helpers:pinGitHubActionDigests` preset exists but I could not verify details this session.)

Policy:

- `cooldown: default-days: 7`, `semver-major-days: 14`, `semver-patch-days: 3`; GitHub Actions ecosystem 7 days (SHA-pinned actions are still the ones attackers target, a week lets the community notice).
- Groups: `npm-dev-minor-patch`, `npm-prod-minor-patch`, `actions` (all), `docker`; majors one PR each.
- **Automerge for a solo dev:** only (a) patch/minor of devDependencies and (b) GitHub Actions *patch/minor* **after 7 days**, **only when `ci-gate` is green**, via a small workflow using `fetch-metadata` and `gh pr merge --auto --squash`. Never automerge: runtime dependency majors, Docker base image changes, anything touching `release`/`publish` workflows, or the standards-repo SHA. This respects your "merge only with green CI, never chain with `;`" rule, since `--auto` waits for required checks. **Caveat:** PRs/merges made with `GITHUB_TOKEN` do not trigger other workflows; with Dependabot the PR is created by Dependabot so CI runs, but check your `pull_request` secrets context (Dependabot PRs have restricted secrets).
- Security updates: enabled, grouped per ecosystem; Dependabot alerts email to you.

---

## 6. Release automation

**Tool choice**

| Tool | Fit | Concern |
|---|---|---|
| **release-please** (googleapis) | Conventional Commits drive a persistent Release PR that bumps version, writes CHANGELOG, tags on merge; manifest mode for multi-package; active repo, v4 action [S43] | Needs a PAT or GitHub App token if you want CI to run on the Release PR (GITHUB_TOKEN-created PRs/tags do not trigger workflows) [S43]; squash-merge titles must be conventional |
| semantic-release | Fully automatic publish on merge | Weak monorepo story (community plugins) and no human-reviewable release PR [S44] |
| Changesets | Explicit intent files, strongest for multi-package npm libraries (v3 reported Sept 2026) [S44][S45] | Extra file per change; npm-centric |

**Recommendation:** **release-please** for all repos. It matches develop→main (release PR targets `main` or accumulates on develop, see below), it produces a reviewable PR (good for a solo dev's "pause and look"), and it keeps `CHANGELOG.md` in Keep-a-Changelog-compatible sections (Added/Fixed/Changed mapping is partial: release-please emits Features/Bug Fixes headings, not literal Keep a Changelog; if you want literal KaC, configure `changelog-sections` or hand-curate) [S43][S46]. Use Changesets only if a repo becomes a multi-package published library.

- Enforce Conventional Commits with a PR-title check (`amannn/action-semantic-pull-request`, pinned) because you squash-merge; commit-level `commitlint` is overkill solo.
- Release PR → merge → tag `vX.Y.Z` → release workflow builds image once → scan → attest → push → create **immutable** GitHub Release with notes and SBOM attached → deploy by digest.
- Use a **GitHub App or fine-grained PAT** scoped to the one repo for release-please so the Release PR runs `ci-gate`. Prefer an App (short-lived tokens). Store credentials only in environment-scoped secrets with required reviewer = you.
- **npm publish (if any):** trusted publishing via OIDC with `--provenance` and a dedicated `release` environment, never `pull_request_target` anywhere in that repo [S5][S6].

**Coordinated multi-repo releases (7 repos)**
Keep repos independently versioned; coordinate through *contracts*, not lockstep tags:

- API image consumers (backoffice/frontend) pin the API's OpenAPI/version range; CI in the consumer runs contract tests against the latest released API image digest.
- A "release train" is a checklist issue in the standards repo (or a `release-train.yml` workflow with `workflow_dispatch`) that triggers each repo's release workflow in dependency order and waits (`gh run watch`); each step must be green before the next (matches your merge-only-green rule).
- Record a `deploy-manifest.json` (service → image digest → version → attestation URL) as a release asset in a small "ops" repo; Coolify deploys read from it. This gives atomic rollback ("redeploy previous manifest").
- Database-affecting changes: expand/contract migrations so API and backoffice may deploy in either order.

**Gitflow vs trunk for solo**

- The standard 2026 advice is trunk-based (short-lived branches, feature flags) for small teams because long-lived `develop` adds merge debt without a QA team to justify it. You have a stated policy (develop→main by release, hotfix only with owner OK). Treat that as acceptable **if** develop never diverges for more than ~1 week and releases are mostly fast-forward-able. Concrete guard: a weekly "develop is N commits ahead of main" report, and a rule that any develop-only state older than 7 days is released or reverted. For static sites autodeployed by Hostinger from `main`, a long-lived develop increases the risk that `main` hotfixes drift; back-merge `main`→`develop` automatically after each release (a small workflow opening a PR). **Contested - see section 9.**

---

## 7. Vulnerability SLA policy (a version you can actually meet)

No mandate applies to your repos; the numbers below blend CISA-KEV-oriented tiers from several vendor/policy sources, which differ by tier and are not authoritative [S47][S48][S49]. An unrealistic SLA is ignored, so tiers are sized for one person [S47].

| Trigger | Target to fix or mitigate | Notes |
|---|---|---|
| In CISA KEV, or active exploitation, reachable in production | 72 h (mitigate: disable, WAF, pin, rollback) | Bump to emergency; rotate secrets if CI-adjacent |
| Critical (CVSS >= 9) reachable or internet-facing API/backoffice | 7 days | |
| High, fixable | 30 days | Image base-layer High: next scheduled rebuild |
| Medium | 90 days or next dependency batch | |
| Low / unreachable / dev-only | Best effort, review quarterly | VEX or ignore entry with expiry |
| Compromised action/package incident (like tj-actions, Trivy) | Same day: pin/remove, rotate secrets | Run `gh` audit of workflow runs in the window |

- **EPSS** is a prioritization input (30-day exploit probability), not a gate [S49]. Use EPSS > 0.5 or public exploit as a one-tier escalator.
- Every exception = an issue with owner, reason, expiry (<= 90 days); scanners' ignore files reference the issue.
- Re-scan *deployed* digests weekly (a scheduled workflow pulling the Coolify manifest digests and running Grype/osv), because the image does not change but the advisory DB does.
- A Qualys blog references a CISA "BOD 26-04" 3-day remediation SLA for federal systems; I did not read the directive, so do not adopt it without checking [S50] (Qualys [C]).
- Public repos: add `SECURITY.md` with a private reporting channel (enable GitHub private vulnerability reporting) and a stated response time (acknowledge 5 days); Scorecard rewards disclosure timelines [S27].

---

## 8. Recommendations for our 7 repos

Assumptions: portfolio repos are public (e.g. portfolio site), Pequeverso repos private (a static Next.js site on Hostinger, APIs and backoffices as Docker on a Coolify VPS). Adjust per repo once I know which is which.

**All 7 (the baseline, ship as a standards-repo PR first):**

1. Create `standards` repo: reusable `ci-node.yml`, `security.yml`, `release.yml`; `rulesets/` JSON + `apply-rulesets.sh`; `dependabot.yml`, `SECURITY.md`, PR/issue templates, release-please config. Callers pin by SHA.
2. Every repo: single required check `ci-gate`; ruleset for `develop` and `main` (PR, strict up-to-date, no force-push, no bypass) plus `v*` tag ruleset.
3. Top-level read-only `permissions`; SHA pins everywhere; enable the repo "require full-SHA pinning" policy; zizmor + actionlint + gitleaks stay required.
4. Dependabot with cooldown 7 days, groups, restricted automerge as in section 5.
5. CodeQL (actions + JS/TS) where free; osv-scanner weekly; dependency-review on public repos.
6. release-please + Conventional Commit PR-title check + immutable releases enabled.
7. Weekly "drift" workflow in `standards` that diffs each repo's ruleset/settings against the JSON and opens an issue.
8. Duration dashboard: a weekly workflow that prints p50/p95 of the last 30 `ci` runs per repo; budgets from section 2.4.

**Public portfolio repos (extra):** Scorecard weekly + badge; attest-build-provenance on any released artifact; Signed-Releases via `.intoto.jsonl` or attestations; SECURITY.md and private reporting; harden-runner audit on the publish job only.

**Pequeverso static Next.js site (Hostinger autodeploy from main):** Hostinger builds from `main`, so provenance cannot cover the deployed artifact. Compensate: (a) `main` ruleset is the control, so keep no-bypass and tag ruleset, (b) a post-deploy check of `build-info.json` against the merge SHA, (c) CI builds the same commit and compares output hash/route manifest only if cheap, (d) lockfile + `npm ci --ignore-scripts` where possible, (e) cooldown stays long on this repo since a bad dependency ships straight to production. No attestation work here beyond CI SBOM artifact.

**Pequeverso APIs and backoffices (Docker, Coolify, deploy by digest):**

1. `ci-docker-api.yml`: build once → Grype scan the digest → integration tests against that digest → push → attest provenance (+ CycloneDX SBOM attestation) → `gh attestation verify` → update Coolify digest → call deploy webhook → smoke test → rollback to previous manifest on failure.
2. Move the attest step into the standards reusable workflow for L3 claim; document the claim as "Build L3 (isolated reusable workflow), Source ~L2".
3. Weekly rescan of the deployed digests (section 7); base image digest pinned and bumped by Dependabot Docker updates in one grouped PR.
4. Environment `production` with required reviewer = you and branch restriction to `main`/tags; deployment secrets (Coolify API token with Deploy-only permission [S18]) live only in that environment.
5. Image tags immutable by convention; disable `latest` in Coolify resources.

**Do not adopt now:** merge queue, Renovate migration, Changesets (unless a multi-package library appears), dual cosign + attestations, VEX for private images, harden-runner everywhere, GitHub roadmap features (dependency locking, native egress firewall) until GA.

**Sequencing (about 3 weekends):** (1) standards repo + `ci-gate` + rulesets + Dependabot policy; (2) release-please + immutable releases + SBOM/attest on one API as canary; (3) roll to remaining repos; (4) Scorecard + drift report + SLA issue labels.

---

## 9. Contested / uncertain

- **Is SHA pinning sufficient?** It stops tag-rewrite attacks (tj-actions, Trivy) but not a malicious *new* commit you then upgrade to, nor compromised dependencies the action pulls at runtime, which is why GitHub's roadmap targets transitive dependency locking [S10]. Cooldown plus review of bump diffs is the pragmatic complement; there is no consensus on a correct cooldown length (3-14 days across sources).
- **Do immutable releases protect action consumers?** Aqua says the badge did not prevent the Trivy tag rewrites [S3]; GitHub's docs say new releases get locked tags [S8]. The discrepancy (mutable pre-existing tags, non-release tags, or republish) is not resolved in what I read.
- **SLSA L3 via attest-build-provenance in a reusable workflow:** GitHub's docs assert it [S25]; others route through slsa-github-generator [S31]; the Shai-Hulud events show L3-style provenance on malicious artifacts [S5], so the level says little about the *workflow's trust inputs*.
- **Merge queue availability for user-owned repos, private-repo attestation plan requirement, org-level rulesets for user accounts, CodeQL pricing on private repos, Actions cache size:** all **[unverified]**; confirm in GitHub docs/settings before relying.
- **Dependabot cooldown specifics:** docs confirm a 3-day default; a blog gives a July 2026 date for the change and a wildcard-group interaction that I could not corroborate [S9][S38].
- **Gitflow vs trunk:** trunk-based is mainstream advice, but your owner-defined develop→main flow is a legitimate choice given Hostinger/Coolify deploys; evidence is opinion-based, not empirical.
- **SPDX 3.0 vs CycloneDX tooling maturity** and which format BuildKit emits by default: single-source claims.
- **Flake thresholds:** no authoritative number; Google statistics are quoted second-hand from 2016.
- **Vulnerability SLA numbers:** every source is a vendor/policy blog; adopt as policy choices, not standards.
- **Harden-runner vs native egress firewall:** the native firewall is roadmap only (preview 6-9 months from March 2026, GA unstated) [S10].
- **Roadmap items** (dependency locking, ruleset execution policy, scoped secrets) may have shipped after my sources; check the Actions changelog.

---

## 10. Sources

**GitHub / primary and standards**

- [S1] CVE-2025-30066 coverage, Orca [C]: https://orca.security/resources/blog/github-action-tj-actions-changed-files-compromised/
- [S2] The Hacker News on tj-actions: https://thehackernews.com/2025/03/github-action-compromise-puts-cicd.html
- [S3] Aqua Security, Trivy supply chain attack [C, vendor affected]: https://www.aquasec.com/blog/trivy-supply-chain-attack-what-you-need-to-know/
- [S4] Snyk, Trivy GitHub Actions compromise [C]: https://snyk.io/articles/trivy-github-actions-supply-chain-compromise/
- [S5] Aikido, Shai-Hulud and trusted publishing [C]: https://www.aikido.dev/blog/shai-hulud-trusted-publishing
- [S6] CSA research note, Mini Shai-Hulud (May 2026): https://labs.cloudsecurityalliance.org/research/csa-research-note-mini-shai-hulud-npm-supply-chain-20260516/
- [S7] GitHub changelog, blocking and SHA-pinning policy (Aug 2025): https://github.blog/changelog/2025-08-15-github-actions-policy-now-supports-blocking-and-sha-pinning-actions/
- [S8] GitHub changelog, immutable releases GA: https://github.blog/changelog/2025-10-28-immutable-releases-are-now-generally-available/
- [S9] GitHub docs, Dependabot options reference: https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference
- [S10] GitHub blog, Actions 2026 security roadmap: https://github.blog/security/supply-chain-security/whats-coming-to-our-github-actions-2026-security-roadmap/
- [S11] SLSA v1.1 levels (retired page): https://slsa.dev/spec/v1.1/levels
- [S12] SLSA v1.2 announcement: https://slsa.dev/blog/2025/11/announce-slsa-v1.2
- [S13] GitHub, 2026 Actions pricing changes: https://resources.github.com/actions/2026-pricing-changes-for-github-actions/
- [S14] OpenSSF Scorecard docs and third-party posture notes: https://github.com/ossf/scorecard/blob/main/docs/checks.md ; https://raes-environment-packs.readthedocs.io/en/latest/decisions/adrs/0018-openssf-scorecard-posture.html
- [S15] Meziantou, SHA pinning across personal repos: https://www.meziantou.net/enable-sha-pinning-for-github-actions-across-personal-repositories.htm
- [S16] zizmor docs and release notes: https://docs.zizmor.sh/release-notes/ ; Trail of Bits on hardening zizmor: https://blog.trailofbits.com/2026/05/22/we-hardened-zizmors-github-actions-static-analyzer/
- [S17] Coolify, deploy a Docker image: https://coolify.io/docs/applications/deployments/docker-image
- [S18] Coolify, GitHub Actions CI/CD: https://coolify.io/docs/applications/ci-cd/github/actions
- [S19] docker/build-push-action README: https://github.com/docker/build-push-action ; buildx GHA cache guide mirror: https://gitea.wagshome.duckdns.org/publicWagsHome/buildx/src/commit/167c77baeccf4b0d70abff16cf337ec0e091640b/docs/guides/cache/gha.md
- [S20] GitHub docs, managing a merge queue: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue
- [S21] GitHub Well-Architected, rulesets best practices: https://wellarchitected.github.com/library/governance/recommendations/managing-repositories-at-scale/rulesets-best-practices/
- [S22] OneUptime, quarantine flaky tests [C]: https://oneuptime.com/blog/post/2026-07-28-quarantine-flaky-tests/view
- [S23] TestDino flaky benchmark 2026 [C]: https://testdino.com/blog/flaky-test-benchmark-report-2026
- [S24] GitHub changelog, requiring workflows via rulesets GA: https://github.blog/changelog/2023-10-11-requiring-workflows-with-repository-rules-is-generally-available/
- [S25] GitHub docs, artifact attestations concepts: https://docs.github.com/en/actions/concepts/security/artifact-attestations
- [S26] Attested-delivery guide, "SLSA L3 is nearly free": https://attested-delivery.github.io/docs/concepts/05-slsa-l3-is-nearly-free/
- [S27] OpenSSF Scorecard site: https://securityscorecards.dev
- [S28] GitHub changelog, CodeQL for Actions workflows GA: https://github.blog/changelog/2025-04-22-github-actions-workflow-security-analysis-with-codeql-is-now-generally-available
- [S29] GitHub docs, use artifact attestations: https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations
- [S30] DevOpsCube, SLSA provenance in Actions: https://devopscube.com/slsa-provenance/
- [S31] (same as S30) slsa-github-generator route
- [S32] Anchore, SBOM standards [C]: https://anchore.com/sbom/key-things-to-know-about-sboms-and-sbom-standards/
- [S33] ADR on CycloneDX primary + SPDX export: https://attested-delivery.github.io/docs/adrs/0003-sbom-format-cyclonedx-spdx-oci-referrers/
- [S34] Sigstore cosign install docs and cosign v3 notes: https://docs.sigstore.dev/cosign/system_config/installation/ ; https://oneuptime.com/blog/post/2026-08-11-cosign-keyless-signing-explained/view [C]
- [S35] actions/dependency-review-action: https://github.com/actions/dependency-review-action
- [S36] OSV-Scanner GitHub Action docs: https://google.github.io/osv-scanner/github-action
- [S37] StepSecurity harden-runner docs [C]: https://docs.stepsecurity.io/harden-runner ; CVE-2026-25598 write-up: https://devansh.bearblog.dev/harden-runner/ ; block mode on macOS/Windows [C]: https://www.stepsecurity.io/blog/harden-runner-block-mode-now-available-for-macos-and-windows-github-hosted-runners
- [S38] Classmethod, Dependabot wildcard groups and cooldown (single source): https://dev.classmethod.jp/en/articles/dependabot-wildcard-group-cooldown-trap/
- [S39] GitHub blog, Tame Dependabot: https://github.blog/security/application-security/tame-dependabot-group-your-updates-slow-the-cadence-keep-security-fast/
- [S40] AppSecSanta, Dependabot vs Renovate [C-ish, affiliate-style site]: https://appsecsanta.com/dependabot-vs-renovate
- [S41] Aikido, Dependabot vs Renovate [C]: https://www.aikido.dev/blog/dependabot-vs-renovate
- [S42] Socket glossary on automated dependency updates (axios incident) [C]: https://socket.dev/glossary/automated-dependency-updates.md
- [S43] googleapis/release-please-action: https://github.com/googleapis/release-please-action
- [S44] PkgPulse, changesets vs semantic-release vs release-it 2026: https://www.pkgpulse.com/guides/changesets-vs-semantic-release-vs-release-it-guide-for-npm-publishing-2026
- [S45] InfoQ, Changesets v3: https://infoq.com/news/2026/09/changesets-v3-release
- [S46] Tenki, release automation in Actions [C]: https://www.tenki.cloud/blog/release-automation-github-actions
- [S47] Decryption Digest, patch SLA developers will follow: https://www.decryptiondigest.com/blog/patch-sla-policy-developers-will-follow
- [S48] DefectDojo, remediation SLAs [C]: https://docs.defectdojo.com/federal_compliance/remediation_slas/
- [S49] NHIMG, CVE prioritization with KEV and EPSS: https://nhimg.org/articles/cve-prioritization-needs-kev-and-epss-not-cvss-alone/
- [S50] Qualys, CISA BOD 26-04 3-day SLA [C, unread directive]: https://blog.qualys.com/product-tech/2026/07/09/cisa-bod-26-04-3-day-remediation-sla
- Additional read: Semgrep SHA pinning org-wide [C]: https://app.semgrep.dev/blog/2026/sha-pinning-for-github-actions-org-wide ; Lullabot ADR on pinning: https://architecture.lullabot.com/adr/20260505-pin-github-actions-to-hash/ ; SLSA v1.2 source requirements: https://slsa.dev/spec/v1.2/source-requirements ; GitHub Community immutable releases GA thread: https://github.com/orgs/community/discussions/178351 ; Wiz Trivy incident page [C]: https://threats.wiz.io/all-incidents/trivy-supply-chain-attack ; Ox Security on tj-actions [C]: https://www.ox.security/blog/15-hours-of-open-sourced-hell-lessons-learned-from-tj-actions-changed-files/ ; Dependabot cooldown vs npm min-release-age: https://dev.classmethod.jp/en/articles/npm-min-release-age-dependabot-cooldown/ ; Packagist zizmor adoption: https://blog.packagist.com/securing-our-github-actions-workflows-with-zizmor/ ; Trunk merge-queue docs [C]: https://docs.trunk.io/merge-queue/getting-started/configure-branch-protection
