"""Branch flow: releases and owner-authorized hotfixes into main; task branches into develop."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from branch_policy import check

REPO = 'gonzalomartinperez/pequeverso-assistant-api'


@pytest.mark.parametrize(
    ('base', 'head'),
    [
        ('main', 'develop'),
        ('main', 'hotfix/session-expiry'),
        ('develop', 'feat/assistant-foundation'),
        ('develop', 'fix/stream-timeout'),
        ('develop', 'ci/branch-policy'),
        ('develop', 'dependabot/uv/develop/fastapi-0.141.2'),
        ('develop', 'main'),
    ],
)
def test_allowed_flows(base: str, head: str) -> None:
    assert check(base, head, REPO, REPO) is None


@pytest.mark.parametrize(
    ('base', 'head'),
    [
        ('main', 'feat/skip-develop'),  # features never go straight to production
        ('main', 'fix/quick-change'),  # a hotfix must be named hotfix/* (owner-authorized)
        ('main', 'dependabot/uv/main/openai-4.0.0'),  # security PRs are retargeted to develop
        ('main', 'hotfix/Bad_Name'),
        ('develop', 'feature/no-type'),
        ('develop', 'feat/CamelCase'),
        ('develop', 'hotfix/x'),  # hotfixes go to main, then main is merged back
        ('release', 'develop'),
        ('deploy', 'main'),
    ],
)
def test_rejected_flows(base: str, head: str) -> None:
    assert check(base, head, REPO, REPO) is not None


def test_forks_are_rejected_even_with_allowed_names() -> None:
    assert check('main', 'develop', 'attacker/pequeverso-assistant-api', REPO) is not None
    assert check('develop', 'feat/x', 'attacker/pequeverso-assistant-api', REPO) is not None
