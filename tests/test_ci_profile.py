"""Assert the paired graph and execute its fail-closed aggregate without services."""

from __future__ import annotations

import os
import re
import subprocess
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from scripts import ci_identity

ROOT = Path(__file__).resolve().parents[1]
NAMES = {
    'workflows': 'Workflow validation',
    'secrets': 'Secret scan',
    'static': 'Static checks',
    'database': 'Database tests',
    'container': 'Container verification',
    'checks': 'Required checks',
}
NEEDS = {
    'workflows': [],
    'secrets': [],
    'static': [],
    'database': ['static'],
    'container': ['static'],
    'checks': ['workflows', 'secrets', 'static', 'database', 'container'],
}
COMMANDS = {
    'workflows': [],
    'secrets': ['.github/scripts/secret-scan.sh'],
    'static': [
        'uv sync --frozen',
        'ruff check',
        'ruff format --check',
        'uv run mypy',
        'uv run pytest -q',
        'contracts.export --check',
        'scripts/evaluate_retrieval.py',
        'scripts/evaluate_conversations.py',
    ],
    'database': [
        'infra/docker/postgres/Dockerfile',
        'infra/docker/neo4j/Dockerfile',
        'scripts/smoke_knowledge_postgres.sh',
        'scripts.smoke_knowledge_neo4j',
        'scripts.smoke_graph_runtime',
        '--with-index-jobs --with-evaluation-tests',
    ],
    'container': ['infra/docker/app/Dockerfile', 'scripts/smoke_container.sh pequeverso-assistant-api:smoke'],
}


def workflow():
    return yaml.safe_load((ROOT / '.github/workflows/quality.yml').read_text())


def validate(value):
    events = value.get('on', value.get(True))
    assert value['name'] == 'Quality'
    assert events['pull_request'] == {
        'branches': ['develop', 'main'],
        'types': ['opened', 'synchronize', 'reopened', 'edited', 'ready_for_review'],
    }
    assert events['push'] == {'branches': ['develop', 'main']}
    assert not ({'pull_request_target', 'workflow_run'} & events.keys())
    assert value['permissions'] == {}
    assert value['concurrency']['cancel-in-progress'] is True
    assert value['env']['AI_PROVIDER'] == 'fixture'
    assert value['env']['ALLOW_PAID_AI'] == 'false'
    assert value['env']['LANGSMITH_TRACING'] == 'false'
    assert set(value['jobs']) == set(NAMES)
    for key, job in value['jobs'].items():
        assert job['name'] == NAMES[key]
        assert job.get('needs', []) == NEEDS[key]
        assert job['runs-on'] == 'ubuntu-24.04'
        assert not job.get('continue-on-error')
        assert job.get('if') == ('always()' if key == 'checks' else None)
        assert job['permissions'] == ({} if key == 'checks' else {'contents': 'read'})
        for step in job['steps']:
            assert 'if' not in step
            assert not step.get('continue-on-error')
            if 'uses' in step:
                assert re.fullmatch(r'[\w./-]+@[a-f0-9]{40}', step['uses'])
                assert 'upload-artifact' not in step['uses']
            if step.get('uses', '').startswith('actions/checkout@'):
                assert step['with']['persist-credentials'] is False
                assert 'ref' not in step['with']
        commands = '\n'.join(step.get('run', '') for step in job['steps'])
        for command in COMMANDS.get(key, []):
            assert command in commands
        if key != 'checks':
            assert 'python3 -m scripts.ci_identity' in commands
    actions = [step.get('uses', '') for step in value['jobs']['workflows']['steps']]
    assert any(action.startswith('raven-actions/actionlint@') for action in actions)
    assert any(action.startswith('zizmorcore/zizmor-action@') for action in actions)
    assert value['jobs']['secrets']['steps'][0]['with']['fetch-depth'] == 0
    gate = value['jobs']['checks']
    assert len(gate['steps']) == 1
    assert gate['steps'][0]['env'] == {
        f'{key.upper()}_RESULT': '${{ needs.' + key + '.result }}' for key in NEEDS['checks']
    }


def test_actual_profile_preserves_required_work():
    validate(workflow())
    assert all((ROOT / name).is_file() for name in ci_identity.BUILD_INPUTS)


@pytest.mark.parametrize('key', NAMES)
def test_missing_or_renamed_job_and_wrong_dependency_are_rejected(key):
    for field, replacement in (('name', 'placeholder'), ('needs', ['unknown'])):
        value = workflow()
        value['jobs'][key][field] = replacement
        with pytest.raises(AssertionError):
            validate(value)
    value = workflow()
    del value['jobs'][key]
    with pytest.raises(AssertionError):
        validate(value)


@pytest.mark.parametrize(
    'mode', ['path', 'write', 'action', 'skip', 'continue', 'empty_gate', 'missing_command']
)
def test_filtered_privileged_or_missing_work_cannot_pass(mode):
    value = workflow()
    job = value['jobs']['database']
    if mode == 'path':
        value.get('on', value.get(True))['pull_request']['paths'] = ['app/**']
    elif mode == 'write':
        job['permissions']['contents'] = 'write'
    elif mode == 'action':
        job['steps'][0]['uses'] = 'actions/checkout@main'
    elif mode == 'skip':
        job['steps'][-1]['if'] = 'false'
    elif mode == 'continue':
        job['continue-on-error'] = True
    elif mode == 'empty_gate':
        value['jobs']['checks']['steps'][0]['env'] = {}
    else:
        job['steps'] = [s for s in job['steps'] if 'scripts.smoke_graph_runtime' not in s.get('run', '')]
    with pytest.raises(AssertionError):
        validate(value)


def test_actual_aggregate_shell_fails_for_every_missing_or_unsuccessful_job():
    gate = workflow()['jobs']['checks']['steps'][0]
    green = {name: 'success' for name in gate['env']}
    clean = {name: value for name, value in os.environ.items() if name not in green}

    def run(results):
        return subprocess.run(  # noqa: S603 -- execute only the owned aggregate, with synthetic results
            ['/bin/bash', '-e', '-c', gate['run']], env={**clean, **results}, capture_output=True, check=False
        ).returncode

    assert run(green) == 0
    for key in green:
        for result in ('failure', 'cancelled', 'skipped', 'pending', ''):
            assert run({**green, key: result}) != 0
        missing = deepcopy(green)
        del missing[key]
        assert run(missing) != 0


def test_required_check_name_is_unique_across_workflows():
    names = []
    for path in (ROOT / '.github/workflows').glob('*.yml'):
        value = yaml.safe_load(path.read_text())
        names.extend(job.get('name', key) for key, job in value['jobs'].items())
    assert names.count('Required checks') == 1
    assert len(names) == len(set(names))


def identity_environment():
    return {
        'GITHUB_SHA': 'a' * 40,
        'GITHUB_WORKFLOW_SHA': 'b' * 40,
        'CI_BASE_SHA': 'c' * 40,
        'GITHUB_RUN_ID': '17',
        'GITHUB_RUN_ATTEMPT': '1',
        'PRIVATE_SENTINEL': 'never copied',
    }


def test_identity_records_hashes_not_environment_and_rejects_other_source(tmp_path):
    for name in ci_identity.BUILD_INPUTS:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('reviewed input')
    with (
        patch.object(ci_identity.subprocess, 'check_output', return_value='a' * 40),
        patch.object(ci_identity.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)),
    ):
        report = ci_identity.identity(tmp_path, identity_environment())
        assert report['source_sha'] == 'a' * 40
        assert report['base_sha'] == 'c' * 40
        assert set(report['build_inputs_sha256']) == set(ci_identity.BUILD_INPUTS)
        assert 'never copied' not in str(report)
        with pytest.raises(ValueError, match='candidate'):
            ci_identity.identity(tmp_path, {**identity_environment(), 'GITHUB_SHA': 'd' * 40})


@pytest.mark.parametrize('result', [1, 128])
def test_identity_rejects_dirty_or_unverifiable_source(tmp_path, result):
    with (
        patch.object(ci_identity.subprocess, 'check_output', return_value='a' * 40),
        patch.object(ci_identity.subprocess, 'run', return_value=subprocess.CompletedProcess([], result)),
        pytest.raises(ValueError, match='Tracked inputs'),
    ):
        ci_identity.identity(tmp_path, identity_environment())


def test_image_identity_rejects_unknown_image_and_invalid_digest():
    with pytest.raises(ValueError, match='Unexpected'):
        ci_identity.image_identity('foreign:latest')
    with (
        patch.object(ci_identity.subprocess, 'check_output', return_value='bad'),
        pytest.raises(ValueError, match='Invalid'),
    ):
        ci_identity.image_identity('pv-knowledge-pg:ci')
    with patch.object(ci_identity.subprocess, 'check_output', return_value='sha256:' + 'a' * 64):
        assert ci_identity.image_identity('pv-knowledge-pg:ci') == 'sha256:' + 'a' * 64
