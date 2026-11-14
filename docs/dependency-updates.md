# Dependency updates

Rule (owner decisions OD-20/21/22/75, ADR-0016): exactly one dependency PR per week, all ecosystems
together, merged manually by the owner.

## Configuration

`.github/dependabot.yml` defines one multi-ecosystem group, `weekly-all`: Monday 09:00
America/Argentina/Buenos_Aires, `target-branch: develop`, `open-pull-requests-limit: 1`, commit prefix
`build(deps)`. Group-level keys live only on the group (Dependabot rejects them on entries). Entries
join with `patterns: ["*"]`: `uv`, `github-actions` and `docker` (`infra/docker/app`, `postgres`,
`neo4j`). Cooldown is 7 days everywhere; semver cooldowns (major 14, minor 7, patch 3) exist on `uv`
only because Actions and Docker reject them. `tests/test_dependabot_config.py` pins all of this.

## Weekly flow

- The owner merges the PR into `develop` (squash) after green CI, including the container image gates.
  No bot approves, enables auto-merge or merges. Promotion to `main` stays an owner-requested release.
- A PR left unmerged is updated or superseded, never duplicated (OD-21): at most one is open.
- `deps-weekly-guard` (`.github/workflows/deps-weekly-guard.yml`, Monday 10:30 ART and on Dependabot PR
  events) is a thin caller of the shared reusable workflow. It uses the GitHub API only; no PR code is
  checked out or executed and nothing uses `pull_request_target`. It closes an older duplicate with a
  pointer to the newer, asks Dependabot to rebase, and labels a red PR `needs-fix`. Agents may push
  fixes to the Dependabot branch only when it carries `needs-fix`. Review with the skill
  `api-review-weekly-dependencies`.

## Vulnerabilities

- Dependabot security-update PRs are off (repository setting); alerts are on and use GitHub's weekly
  digest. Findings ride the weekly PR.
- A daily osv-scanner job records findings silently in one pinned issue, #123 "Dependency and
  vulnerability tracker" (label `vuln`); only the Monday run posts the weekly summary (OD-75).
- Urgent fix (KEV, reachable critical, SLA at risk): a normal task-branch PR bumping the single
  dependency, merged by the owner; it does not create a second Dependabot PR. SLA targets:
  `docs/master-plan/ci-cd.md` and ADR-0016.

## Retired (PVA-D9)

The policy workflow, its classifier script, the allowlist and their tests are gone. The eligibility classifier and its `pull_request_target`
workflow assessed many small PRs for possible auto-merge; with one weekly PR that the owner always
merges by hand it has no decision left to inform, and removing it also removes the only privileged
trigger. Previous profiles remain in Git history.

## Operating

- Pause or revert through a reviewed PR (restore the previous lock version; document any
  `@dependabot ignore` decision). Never use `--admin`, a PAT, direct pushes or protection changes.
