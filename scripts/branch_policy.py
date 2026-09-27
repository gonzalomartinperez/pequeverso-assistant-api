"""Branch flow policy for pull requests (stdlib only; runs from trusted base-branch code).

    develop  <- type/kebab-case task branches, dependabot/*, or main (back-merge after a hotfix)
    main     <- develop (release) or hotfix/* (only with the owner's explicit authorization)

GitHub cannot tell the owner from an agent acting with the owner's account, so the hotfix
authorization itself is procedural (AGENTS.md); this check keeps every other path closed.

    BASE_REF=main HEAD_REF=develop HEAD_REPO=o/r REPO=o/r python3 scripts/branch_policy.py
"""

from __future__ import annotations

import os
import re
import sys

TASK_BRANCH = re.compile(r'^(feat|fix|chore|docs|refactor|perf|test|ci|build|revert)/[a-z0-9]+(-[a-z0-9]+)*$')
HOTFIX_BRANCH = re.compile(r'^hotfix/[a-z0-9]+(-[a-z0-9]+)*$')
DEPENDABOT_BRANCH = re.compile(r'^dependabot/[A-Za-z0-9._/-]+$')


def check(base: str, head: str, head_repo: str, repo: str) -> str | None:
    """None when allowed, otherwise the reason (safe to print: no untrusted text echoed)."""
    if head_repo != repo:
        return 'pull requests must come from a branch of this repository'
    if base == 'main':
        if head == 'develop' or HOTFIX_BRANCH.match(head):
            return None
        return 'main accepts only develop (release) or hotfix/<kebab-case> (owner-authorized hotfix)'
    if base == 'develop':
        if TASK_BRANCH.match(head) or DEPENDABOT_BRANCH.match(head) or head == 'main':
            return None
        return 'develop accepts type/kebab-case task branches, dependabot/* or main (hotfix back-merge)'
    return 'pull requests must target develop or main'


def main() -> int:
    reason = check(
        os.environ.get('BASE_REF', ''),
        os.environ.get('HEAD_REF', ''),
        os.environ.get('HEAD_REPO', ''),
        os.environ.get('REPO', ''),
    )
    if reason:
        print(f'::error::Branch policy: {reason}')
        return 1
    print('Branch policy: allowed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
