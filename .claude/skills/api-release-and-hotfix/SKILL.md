---
name: api-release-and-hotfix
description: Release develop into main, or ship an owner-authorized hotfix, within the protected branch flow. Not an authorization to release, hotfix or deploy.
---

# Release and hotfix

**Release (develop → main).** Only when the owner asks for it (e.g. "mergeá todo en main" or
"sincronizá main").
1. Review the complete release diff at its exact full head SHA. `develop` CI is green and
   there are no open task PRs meant for the release.
2. `gh pr create --base main --head develop --title "chore(release): ..."` listing the included PRs.
3. After all required checks pass on that reviewed head and branch rules permit merging,
   merge manually: `gh pr merge <n> --merge --match-head-commit <reviewed-full-head-sha>`
   (merge commit, never squash, so both branches keep shared history). If the head changes,
   review the new diff and its required checks before merging.
4. Fetch both branches. Verify the recorded released `develop` SHA is an ancestor of
   `origin/main` (`git merge-base --is-ancestor <released-develop-sha> origin/main`) and
   `git diff origin/main origin/develop` is empty. If the branch flow needs synchronization,
   use a reviewed normal `main` → `develop` PR with all required checks, then verify ancestry
   and equal content again. Synchronization merge commits can differ; identical branch SHAs
   or a zero commit count are not required.

**Hotfix (directly into main).** Requires the owner's explicit authorization **in the current
conversation, for this fix**. Earlier approvals, releases or urgency do not count. If there is no
authorization, stop and ask.
1. `git switch -c hotfix/<kebab-case> origin/main`: the smallest fix, with a test.
2. PR into `main` stating the owner's authorization (date and wording). Review its exact full
   head SHA; after all required checks pass on that head, merge manually:
   `gh pr merge <n> --merge --match-head-commit <reviewed-full-head-sha>`.
3. Immediately open a PR `main` → `develop` (merge commit) so `develop` contains the fix.
4. Verify the released hotfix SHA is an ancestor of `origin/main`, `origin/main` is an
   ancestor of `origin/develop`, and `git diff origin/main origin/develop` is empty.

Remove only your already merged task branches after verifying their commits remain recoverable.
Preserve unmerged work, other agents' branches and deployment branches.

Manual review and merge are the default. Never use `--auto` or `--admin`, push to `main`,
change or disable branch protection, or add bypass actors. `main` only receives `develop`
(release) or `hotfix/*` (authorized hotfix).

## Limits

- A release or hotfix happens only when the owner asks for that specific one; this skill is the
  procedure, not the permission. No deploys from this repository (vps-ops deploys).
