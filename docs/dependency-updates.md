# Dependency updates and manual review

## Current profile — 2026-10-17

Dependabot continues to open version-update PRs into `develop`, weekly for every configured ecosystem, with its existing
groups and native `rebase-strategy: auto`. Every update requires manual review and a protected
merge. The read-only policy classifies authenticated metadata and manifest changes; an
`eligible` result means only a low-risk review candidate. Its `automerge` output is always
`false`. It cannot approve, enable auto-merge or merge a PR and has no write-scoped job.

The previous `gh pr merge --auto` adapter could merge immediately when a PR was already clean
and green. It therefore did not guarantee “arm native auto-merge only”. That writer was removed;
no currently open Dependabot PR depended on it at reconciliation. This is the default manual
profile, not a pause of dependency updates. A future native writer requires a separately
reviewed contract, exact-head/protection/review verification and a real `GITHUB_TOKEN` proof.

## Review assessment

`scripts/dependabot_policy.py` and `.github/dependabot-policy.json` retain conservative analysis:

- Verify authenticated Dependabot login/type/id, same repository, open non-draft PR,
  expected head SHA and `develop` base. Inspect every verified Dependabot commit.
- Inspect all changed files and both manifests. Only modifications to `pyproject.toml` and
  `uv.lock` are candidates; dependency addition/removal, tool configuration or unknown impact
  requires explicit review. Compare every direct and transitive locked version.
- The patch/minor allowlists classify impact only. Majors, prereleases, downgrades, unknown
  versions and sensitive 0.x minors always need explicit review, as do provider SDKs,
  validation/TLS/session boundaries, Actions and Docker images.
- Missing, pending or successful checks never authorize a merge. Failed/cancelled checks and
  unknown/conflicting merge state remain visible rejection reasons. A maintainer waits for
  current-head required checks, strict branch freshness and any required independent review.

Review release notes/changelogs, scope and CI before integrating. Use squash into `develop`;
release `develop` → `main` uses a merge commit and the owner's release authorization.
Never use bot approval, a PAT, `--admin`, direct pushes or protection changes to bypass a gate.

## Security updates and rebasing

Alerts remain enabled and visible. Dependabot security updates may target default `main`;
`target-branch: develop` for routine updates does not redirect every security update. A
maintainer assesses and retargets compatible fixes to `develop` or follows a specifically
owner-authorized hotfix. Nothing automatically merges into `main` or suppresses an alert.

Native auto-rebase remains enabled; request `@dependabot rebase` only when needed. Do not add
rebase polling/spam, rewrite a bot branch yourself or close an incompatible update without
recording why it is superseded or blocked. Existing incompatible/sensitive updates stay manual.

## Workflow trust boundary

`pull_request_target` reads the policy from the protected base commit through sparse checkout
with `persist-credentials: false`. PR code is never checked out, installed or executed.
The job has only `contents`, `pull-requests` and `checks`: read. No mutation endpoint or merge
command is used. Normal PR CI runs separately on the PR code with its read-only token.
Actions stay pinned by immutable SHA. Unit regressions cover unsafe identities, files,
versions, check states, missing protection and the absence of a privileged merge workflow.

## Operating and rollback

- Review candidates with their exact head SHA, changelog, manifests and CI; merge normally
  only after all required gates pass. Labels and assessment summaries are not authorization.
- To pause updates, use an explicit reviewed configuration change; the manual profile itself
  does not set the PR limit to zero or disable Dependabot.
- Revert a defective update through a normal PR into `develop`, restoring its previous lock
  version, and document any `@dependabot ignore this patch version` decision.
- To restore automation, propose a separate policy change and independent review; do not
  reintroduce a CLI writer on the assumption that `--auto` cannot perform an immediate merge.

## Historical evidence

The September policy/configuration activation and PR #3 Docker/uv review are historical,
not proof of an eligible native auto-merge. They remain in Git history. No successful real
eligible auto-arming path was demonstrated before adopting this manual profile.
