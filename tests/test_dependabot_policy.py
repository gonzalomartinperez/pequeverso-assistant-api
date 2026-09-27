"""Decisions and safety properties of the Dependabot unattended-merge policy."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from dependabot_policy import (
    DEPENDABOT_ID,
    DEPENDABOT_LOGIN,
    CheckRun,
    Commit,
    Policy,
    PullFacts,
    ci_state,
    classify,
    evaluate,
)

POLICY = Policy.load()
PYPROJECT = (ROOT / 'pyproject.toml').read_text()
LOCK = (ROOT / 'uv.lock').read_text()
SHA = 'a' * 40


def _bump(text: str, package: str, old: str, new: str) -> str:
    marker = f'name = "{package}"\nversion = "{old}"'
    assert marker in text, package
    return text.replace(marker, f'name = "{package}"\nversion = "{new}"')


def facts(**changes: object) -> PullFacts:
    base = PullFacts(
        author_login=DEPENDABOT_LOGIN,
        author_type='Bot',
        author_id=DEPENDABOT_ID,
        head_repo='gonzalomartinperez/pequeverso-assistant-api',
        base_repo='gonzalomartinperez/pequeverso-assistant-api',
        base_ref='develop',
        state='open',
        draft=False,
        head_sha=SHA,
        expected_head_sha=SHA,
        mergeable_state='clean',
        commits=(Commit(DEPENDABOT_LOGIN, 'web-flow', True),),
        files=(('pyproject.toml', 'modified'), ('uv.lock', 'modified')),
        base_manifests={'pyproject.toml': PYPROJECT, 'uv.lock': LOCK},
        head_manifests={
            'pyproject.toml': PYPROJECT.replace('"fastapi>=0.141.1"', '"fastapi>=0.141.2"'),
            'uv.lock': _bump(LOCK, 'fastapi', '0.141.1', '0.141.2'),
        },
        check_runs=(CheckRun('checks', 'completed', 'success'),),
        protection_available=True,
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def _lock(*bumps: tuple[str, str, str]) -> dict[str, str]:
    text = LOCK
    for bump in bumps:
        text = _bump(text, *bump)
    return {'pyproject.toml': PYPROJECT, 'uv.lock': text}


@pytest.mark.parametrize(
    ('old', 'new', 'kind'),
    [
        ('1.2.3', '1.2.4', 'patch'),
        ('1.2.3', '1.3.0', 'minor'),
        ('1.2.3', '2.0.0', 'major'),
        ('0.141.1', '0.141.2', 'patch'),
        ('0.141.1', '0.142.0', 'major'),  # 0.x minor is breaking by semver
        ('1.2.3', '1.3.0rc1', 'prerelease'),
        ('1.2.3', '1.2.2', 'unknown'),  # downgrade
        ('2026.7.22', 'abc', 'unknown'),
        (None, '1.0.0', 'added'),
        ('1.0.0', None, 'removed'),
    ],
)
def test_classify(old: str | None, new: str | None, kind: str) -> None:
    assert classify(old, new) == kind


def test_eligible_patch_enables_auto_merge() -> None:
    decision = evaluate(facts(), POLICY)
    assert decision.eligible
    assert decision.automerge
    assert decision.updates == [{'package': 'fastapi', 'from': '0.141.1', 'to': '0.141.2', 'type': 'patch'}]


def test_allowlisted_minor_dev_tool_is_eligible() -> None:
    decision = evaluate(
        facts(files=(('uv.lock', 'modified'),), head_manifests=_lock(('pytest', '9.1.1', '9.2.0'))), POLICY
    )
    assert decision.eligible, decision.reasons


@pytest.mark.parametrize(
    'bumps',
    [
        (('pytest', '9.1.1', '10.0.0'),),  # major
        (('ruff', '0.16.9', '0.17.0'),),  # 0.x minor
        (('pytest', '9.1.1', '9.2.0rc1'),),  # prerelease
        (('openai', '3.19.2', '3.19.3'),),  # never allowlisted (provider SDK)
        (('starlette', '1.7.0', '1.7.1'),),  # sessions/cookies/SSE core: manual
        (('fastapi', '0.141.1', '0.142.0'),),  # 0.x minor of the framework
    ],
)
def test_risky_or_unlisted_updates_need_review(bumps: tuple[tuple[str, str, str], ...]) -> None:
    decision = evaluate(facts(files=(('uv.lock', 'modified'),), head_manifests=_lock(*bumps)), POLICY)
    assert not decision.eligible
    assert not decision.automerge


def test_grouped_update_is_eligible_only_when_every_member_is() -> None:
    safe = _lock(('pytest', '9.1.1', '9.1.2'), ('ruff', '0.16.9', '0.16.10'))
    assert evaluate(facts(files=(('uv.lock', 'modified'),), head_manifests=safe), POLICY).eligible
    mixed = _lock(('pytest', '9.1.1', '9.1.2'), ('pydantic', '2.13.5', '2.13.6'))
    decision = evaluate(facts(files=(('uv.lock', 'modified'),), head_manifests=mixed), POLICY)
    assert not decision.eligible
    assert any('pydantic' in r for r in decision.reasons)


@pytest.mark.parametrize(
    'spoof',
    [
        {'author_login': 'dependabot'},  # look-alike user
        {'author_type': 'User'},
        {'author_id': 1},
        {'head_repo': 'attacker/pequeverso-assistant-api'},  # fork with a Dependabot-style branch
    ],
)
def test_spoofed_identity_is_rejected(spoof: dict[str, object]) -> None:
    assert not evaluate(facts(**spoof), POLICY).eligible


def test_title_labels_and_branch_are_not_inputs() -> None:
    # PullFacts has no title, label or branch-name field at all: they cannot grant eligibility.
    assert not {'title', 'labels', 'head_ref'} & set(PullFacts.__dataclass_fields__)


def test_unexpected_files_and_script_changes_need_review() -> None:
    workflow = facts(files=(('uv.lock', 'modified'), ('.github/workflows/quality.yml', 'modified')))
    assert not evaluate(workflow, POLICY).eligible
    code = facts(files=(('uv.lock', 'modified'), ('app/main.py', 'modified')))
    assert not evaluate(code, POLICY).eligible
    scripts = PYPROJECT.replace('[tool.uv]', '[project.scripts]\nevil = "app.main:x"\n\n[tool.uv]')
    changed = facts(
        head_manifests={
            'pyproject.toml': scripts,
            'uv.lock': _lock(('fastapi', '0.141.1', '0.141.2'))['uv.lock'],
        }
    )
    decision = evaluate(changed, POLICY)
    assert not decision.eligible
    assert any('more than dependency versions' in r for r in decision.reasons)
    added = PYPROJECT.replace('"httpx>=0.28.1",', '"httpx>=0.28.1",\n    "requests>=2",')
    assert not evaluate(facts(head_manifests={'pyproject.toml': added, 'uv.lock': LOCK}), POLICY).eligible


def test_human_commits_on_a_dependency_pr_need_review() -> None:
    human = facts(commits=(Commit(DEPENDABOT_LOGIN, 'web-flow', True), Commit('someone', 'someone', True)))
    assert not evaluate(human, POLICY).eligible
    unverified = facts(commits=(Commit(DEPENDABOT_LOGIN, DEPENDABOT_LOGIN, False),))
    assert not evaluate(unverified, POLICY).eligible


def test_wrong_target_branch_is_rejected() -> None:
    for branch in ('main', 'release', 'deploy'):
        assert not evaluate(facts(base_ref=branch), POLICY).eligible


def test_new_head_after_evaluation_is_rejected() -> None:
    decision = evaluate(facts(head_sha='b' * 40), POLICY)
    assert not decision.eligible
    assert not decision.automerge


@pytest.mark.parametrize(
    ('runs', 'state', 'eligible'),
    [
        ((CheckRun('checks', 'completed', 'success'),), 'success', True),
        ((CheckRun('checks', 'in_progress', None),), 'pending', True),  # native auto-merge waits
        ((), 'missing', True),  # not reported yet; required-check enforcement is GitHub's
        ((CheckRun('checks', 'completed', 'failure'),), 'failure', False),
        ((CheckRun('checks', 'completed', 'cancelled'),), 'cancelled', False),
        ((CheckRun('checks', 'completed', 'timed_out'),), 'failure', False),
        ((CheckRun('other', 'completed', 'success'),), 'missing', True),
    ],
)
def test_check_states(runs: tuple[CheckRun, ...], state: str, eligible: bool) -> None:
    assert ci_state(runs, POLICY.required_checks) == state
    assert evaluate(facts(check_runs=runs), POLICY).eligible is eligible


def test_conflicts_need_review_and_behind_is_left_to_rebase() -> None:
    assert not evaluate(facts(mergeable_state='dirty'), POLICY).eligible
    assert not evaluate(facts(mergeable_state='unknown'), POLICY).eligible
    assert evaluate(facts(mergeable_state='behind'), POLICY).eligible


def test_without_branch_protection_auto_merge_fails_closed() -> None:
    decision = evaluate(facts(protection_available=False), POLICY)
    assert decision.eligible
    assert not decision.automerge
    assert any('no enforceable protection' in r for r in decision.reasons)


def test_lockfile_only_change_without_version_change_needs_review() -> None:
    same = facts(
        files=(('uv.lock', 'modified'),), head_manifests={'pyproject.toml': PYPROJECT, 'uv.lock': LOCK + '\n'}
    )
    assert not evaluate(same, POLICY).eligible


def test_closed_or_draft_pull_requests_are_rejected() -> None:
    assert not evaluate(facts(state='closed'), POLICY).eligible
    assert not evaluate(facts(draft=True), POLICY).eligible
