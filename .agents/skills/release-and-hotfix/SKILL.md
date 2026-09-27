---
name: release-and-hotfix
description: Release develop into main, or ship an owner-authorized hotfix, within the protected branch flow.
---

# Release and hotfix

**Release (develop → main).** Only when the owner asks for it (e.g. "mergeá todo en main" or
"sincronizá main").
1. `develop` CI is green and there are no open task PRs meant for the release.
2. `gh pr create --base main --head develop --title "release: ..."` listing the included PRs.
3. After `checks` and `Branch policy` pass: `gh pr merge <n> --merge --auto` (merge commit, never
   squash, so both branches keep shared history). Never `--admin`.
4. Verify: `git rev-list --count origin/main..origin/develop` is 0 and
   `git diff origin/main origin/develop` is empty. Only `main` and `develop` remain.

**Hotfix (directly into main).** Requires the owner's explicit authorization **in the current
conversation, for this fix**. Earlier approvals, releases or urgency do not count. If there is no
authorization, stop and ask.
1. `git switch -c hotfix/<kebab-case> origin/main`: the smallest fix, with a test.
2. PR into `main` stating the owner's authorization (date and wording). After the checks pass,
   `gh pr merge --merge --auto`.
3. Immediately open a PR `main` → `develop` (merge commit) so `develop` contains the fix.
4. Verify both branches are synchronized as in step 4 of the release.

Never push to `main`, change or disable rulesets, add bypass actors, or use `--admin`.
`Branch policy` rejects any other head branch for `main`.
