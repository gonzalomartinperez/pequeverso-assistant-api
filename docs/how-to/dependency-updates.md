# Review the weekly dependency PR

[Dependabot configuration](../../.github/dependabot.yml) groups uv, GitHub Actions and the
application, PostgreSQL and Neo4j Docker images into `weekly-all`. The group runs Mondays at
09:00 in `America/Argentina/Buenos_Aires`, targets `develop` and limits open PRs to one.
All entries have a seven-day default cooldown. The uv entry uses separate major, minor and patch
cooldowns. The policy and SLA are in
[ADR-0016](../decisions/ADR-0016-weekly-dependency-pr-and-vulnerability-sla.md).

GitHub reads the configuration and scheduled workflows from the default branch, `develop`.
The November 2026 observation recorded a grouped PR into `develop`, followed by a replacement
that Dependabot opened before closing the older PR. The guard ran successfully on both PR
events and on schedule. The engineering-standards sandbox verified grouped cooldowns.
[Observation in ADR-0016](https://github.com/gonzalomartinperez/pequeverso-assistant-api/blob/d972d026a8a994d74d4e08a88a87b1a9c560a4ba/docs/decisions/ADR-0016-weekly-dependency-pr-and-vulnerability-sla.md#observed-in-this-repository-2026-11-16-to-2026-11-21-pva-m11)

## Review and merge

1. Find the open dependency PR and set `pr` to its number. Verify Dependabot is the author,
   the base is `develop`, and the head is
   `dependabot/develop/weekly-all-<hash>`.

   ```sh
   gh pr list --base develop --state open --label dependencies
   pr=PR_NUMBER
   gh pr view "$pr" --json author,baseRefName,headRefName,labels,url
   ```

2. If there are duplicates, review the newest only. The API-only
   [guard](../../.github/workflows/deps-weekly-guard.yml) checks for duplicates when Dependabot PRs
   open, reopen or synchronize, and on Monday at 10:30 Buenos Aires time or manual dispatch.
   It closes older grouped PRs with a link to the survivor. Scheduled and manual runs also
   record the survivor's status in the tracker, add `needs-fix` for a red `checks` result,
   and remove the label when the check turns green. Automatic rebase requests are disabled.

3. Read the PR diff and upstream changelogs between the pinned versions. Check Starlette session
   and cookie behavior, Pydantic validation, OpenAI SDK streaming and Responses API types, TLS,
   and configuration loading. For an OpenAI SDK update, compare the new types with
   [the provider adapter](../../app/adapters/providers/openai_provider.py). Check changed image
   digests for app, PostgreSQL and Neo4j and review GitHub Actions pins. Major updates and
   framework updates require human review.

   ```sh
   gh pr diff "$pr"
   ```

4. Check out the PR and run the locked install, tests and contract export check in fixture mode.
   Live evaluations require the owner's explicit authorization.

   ```sh
   gh pr checkout "$pr"
   uv sync --locked && uv run pytest -n auto && uv run python -m contracts.export --check
   ```

5. Wait for green [CI](../reference/ci.md), including the container gates and SBOM. If the PR
   is red or marked `needs-fix`, record the failure and required fix in a review comment.
   Push fixes to the Dependabot branch only at the owner's request.

   ```sh
   gh pr checks "$pr" --watch
   ```

6. The owner merges the green PR manually into `develop` using a merge commit.

   ```sh
   gh pr checks "$pr" --watch && gh pr merge "$pr" --merge --delete-branch
   ```

## Supersede a pending weekly PR

1. Use the listing and inspection commands above to check for a replacement. If Dependabot
   or the guard has closed the older PR, follow the supersede comment to the new PR and
   review its current head.
2. To pick up newer versions before Monday, close the open weekly PR so the next Dependabot
   run can open a complete replacement.

   ```sh
   gh pr close "$pr"
   ```

3. Review the replacement from step 1 of the weekly procedure.

## Route urgent vulnerabilities

1. Read the Dependabot alerts and the pinned [Dependency and vulnerability tracker](https://github.com/gonzalomartinperez/pequeverso-assistant-api/issues/123).
   Dependabot security-update PRs are disabled and alerts use the weekly digest. `vuln-daily`
   updates the tracker silently, with a weekly summary on Monday.
2. Use the ADR-0016 SLA to decide whether the fix can ride the weekly PR. A KEV finding, a
   reachable critical finding, or a fix that would miss its SLA takes the manual path.
3. Open a normal task-branch PR into `develop` that updates the single affected dependency.
   Review the diff, run the same local validation and wait for green CI. The owner merges
   through the protected branch flow. This keeps the weekly Dependabot slot available.
