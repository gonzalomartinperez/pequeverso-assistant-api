"""Pin the weekly single-PR Dependabot rule (OD-20/21/22) and its guard caller."""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
GROUP = 'weekly-all'
SEMVER_KEYS = {'semver-major-days', 'semver-minor-days', 'semver-patch-days'}
REUSABLE = 'gonzalomartinperez/engineering-standards/.github/workflows/deps-weekly-guard.yml'


def _load(path: str) -> dict[str, Any]:
    return yaml.safe_load((ROOT / path).read_text())


def validate_config(cfg: dict[str, Any]) -> None:
    assert cfg['version'] == 2
    groups = cfg['multi-ecosystem-groups']
    assert list(groups) == [GROUP]
    group = groups[GROUP]
    assert group['schedule'] == {
        'interval': 'weekly',
        'day': 'monday',
        'time': '09:00',
        'timezone': 'America/Argentina/Buenos_Aires',
    }
    assert group['target-branch'] == 'develop'
    assert group['open-pull-requests-limit'] == 1
    assert group['commit-message'] == {'prefix': 'build(deps)'}
    updates = cfg['updates']
    assert {u['package-ecosystem'] for u in updates} == {'uv', 'github-actions', 'docker'}
    assert len(updates) == 3
    for entry in updates:
        eco = entry['package-ecosystem']
        assert entry['multi-ecosystem-group'] == GROUP
        assert entry['patterns'] == ['*']
        for forbidden in ('open-pull-requests-limit', 'commit-message', 'target-branch', 'schedule'):
            assert forbidden not in entry, f'{eco}: {forbidden} belongs on the group'
        cooldown = entry['cooldown']
        assert cooldown['default-days'] == 7
        if eco == 'uv':
            assert cooldown['semver-major-days'] == 14
            assert cooldown['semver-patch-days'] == 3
        else:
            assert not SEMVER_KEYS & set(cooldown), f'{eco}: semver cooldown unsupported'
        if eco == 'docker':
            assert set(entry['directories']) == {
                '/infra/docker/app',
                '/infra/docker/postgres',
                '/infra/docker/neo4j',
            }


def validate_guard(workflow: dict[str, Any], group_name: str) -> None:
    # PyYAML parses the bare key `on` as boolean True.
    assert workflow.get('permissions') == {}
    triggers = workflow[True]
    assert triggers['schedule'] == [{'cron': '30 13 * * 1'}]
    assert triggers['pull_request'] == {'types': ['opened', 'reopened', 'synchronize']}
    assert set(triggers) == {'schedule', 'pull_request', 'workflow_dispatch'}
    guard = workflow['jobs']['guard']
    assert (
        guard['if']
        == "github.event_name != 'pull_request' || github.event.pull_request.user.login == 'dependabot[bot]'"
    )
    assert guard['permissions'] == {
        'contents': 'read',
        'pull-requests': 'write',
        'issues': 'write',
        'checks': 'read',
    }
    assert 'secrets' not in guard
    assert guard['with']['gate-check-name'] == 'checks'
    uses = guard['uses']
    assert uses.startswith(f'{REUSABLE}@')
    assert re.fullmatch(r'[0-9a-f]{40}', uses.split('@', 1)[1]), 'pin the reusable workflow by SHA'
    assert guard['with']['group-name'] == group_name


@pytest.fixture
def config() -> dict[str, Any]:
    return _load('.github/dependabot.yml')


def test_config_is_valid(config: dict[str, Any]) -> None:
    validate_config(config)


def test_no_pull_request_target() -> None:
    for path in (ROOT / '.github/workflows').glob('*.y*ml'):
        assert 'pull_request_target' not in path.read_text(), path.name


def test_guard_caller_is_pinned_thin_and_matches_group(config: dict[str, Any]) -> None:
    workflow = _load('.github/workflows/deps-weekly-guard.yml')
    validate_guard(workflow, next(iter(config['multi-ecosystem-groups'])))


def _entry(cfg: dict[str, Any], eco: str) -> dict[str, Any]:
    return next(u for u in cfg['updates'] if u['package-ecosystem'] == eco)


def test_rejects_entry_pull_request_limit(config: dict[str, Any]) -> None:
    bad = deepcopy(config)
    _entry(bad, 'uv')['open-pull-requests-limit'] = 5
    with pytest.raises(AssertionError):
        validate_config(bad)


def test_rejects_semver_cooldown_on_docker(config: dict[str, Any]) -> None:
    bad = deepcopy(config)
    _entry(bad, 'docker')['cooldown']['semver-major-days'] = 14
    with pytest.raises(AssertionError):
        validate_config(bad)


def test_rejects_wrong_timezone(config: dict[str, Any]) -> None:
    bad = deepcopy(config)
    bad['multi-ecosystem-groups'][GROUP]['schedule']['timezone'] = 'UTC'
    with pytest.raises(AssertionError):
        validate_config(bad)


def test_rejects_extra_group(config: dict[str, Any]) -> None:
    bad = deepcopy(config)
    bad['multi-ecosystem-groups']['second'] = deepcopy(bad['multi-ecosystem-groups'][GROUP])
    with pytest.raises(AssertionError):
        validate_config(bad)


def test_rejects_unpinned_or_mismatched_guard() -> None:
    good = _load('.github/workflows/deps-weekly-guard.yml')
    good['jobs']['guard']['uses'] = f'{REUSABLE}@' + 'a' * 40
    validate_guard(good, GROUP)
    for uses in (f'{REUSABLE}@main', f'{REUSABLE}@ENGINEERING_STANDARDS_SHA'):
        bad = deepcopy(good)
        bad['jobs']['guard']['uses'] = uses
        with pytest.raises(AssertionError):
            validate_guard(bad, GROUP)
    bad = deepcopy(good)
    bad['permissions'] = {'contents': 'read'}
    with pytest.raises(AssertionError):
        validate_guard(bad, GROUP)
    with pytest.raises(AssertionError):
        validate_guard(good, 'other')


@pytest.mark.parametrize('mutation', ['widen', 'secrets', 'if', 'cron'])
def test_rejects_a_broadened_guard(mutation: str) -> None:
    bad = _load('.github/workflows/deps-weekly-guard.yml')
    guard = bad['jobs']['guard']
    if mutation == 'widen':
        guard['permissions']['contents'] = 'write'
    elif mutation == 'secrets':
        guard['secrets'] = 'inherit'
    elif mutation == 'if':
        guard['if'] = 'always()'
    else:
        bad[True]['schedule'] = [{'cron': '0 0 * * *'}]
    with pytest.raises(AssertionError):
        validate_guard(bad, GROUP)
