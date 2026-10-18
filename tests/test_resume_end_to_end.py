"""Deterministic recovery boundaries; no key reads or provider calls."""

import json

import pytest

from scripts.real_eval_budget import Envelope
from scripts.resume_end_to_end import remaining_cases, verify_existing_budget


@pytest.fixture
def state(tmp_path):
    manifest = {'cases': [{'id': f'case-{i}', 'turns': [{'question': 'test'}]} for i in range(200)]}
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    (tmp_path / 'answers.json').write_text(
        json.dumps([{'case_id': 'case-0', 'turn': 1, 'terminal': ['run.completed']}])
    )
    return manifest, tmp_path


def test_terminal_checkpoint_is_skipped_without_claiming_http_recovery(state):
    manifest, path = state
    (path / 'inflight.json').write_text(
        json.dumps(
            {
                'case_id': 'case-1',
                'turn': 1,
                'events': [{'type': 'message.completed'}, {'type': 'run.completed'}],
            }
        )
    )
    before = (path / 'answers.json').read_bytes()
    remaining, receipt = remaining_cases(manifest, path)
    assert len(remaining['cases']) == 198
    assert remaining['cases'][0]['id'] == 'case-2'
    assert receipt['terminal_only_completion']['http_history_and_replay_verified'] is False
    assert (path / 'answers.json').read_bytes() == before


def test_unfinished_generation_is_never_retried(state):
    manifest, path = state
    (path / 'inflight.json').write_text(
        json.dumps({'case_id': 'case-1', 'turn': 1, 'events': [{'type': 'message.delta'}]})
    )
    with pytest.raises(ValueError, match='never retry'):
        remaining_cases(manifest, path)


def test_mismatched_manifest_is_rejected(state):
    manifest, path = state
    manifest['cases'][0]['turns'][0]['question'] = 'changed'
    with pytest.raises(ValueError, match='frozen manifest'):
        remaining_cases(manifest, path)


def test_partial_conversation_needs_its_original_session(state):
    manifest, path = state
    manifest['cases'][0]['turns'].append({'question': 'follow-up'})
    (path / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='partially completed conversation'):
        remaining_cases(manifest, path)


def test_original_matrix_still_requires_200_queries(state):
    manifest, path = state
    manifest['cases'] = manifest['cases'][:3]
    with pytest.raises(ValueError, match='at least 200'):
        remaining_cases(manifest, path)


def test_continuation_cannot_create_a_fresh_allowance(tmp_path):
    path = tmp_path / 'typo.sqlite3'
    with pytest.raises(ValueError, match='existing shared budget'):
        verify_existing_budget(tmp_path, path, False)
    assert not path.exists()


def test_budget_preserves_prior_charge_and_terminal_completion(tmp_path):
    ledger = Envelope(tmp_path / 'budget.sqlite3')
    first = ledger.reserve()
    ledger.settle(first, 100, 100)
    (tmp_path / 'budget.json').write_text(json.dumps(ledger.snapshot()))
    with pytest.raises(ValueError, match='previous run allowance'):
        verify_existing_budget(tmp_path, ledger.path, True)
    second = ledger.reserve()
    ledger.settle(second, 100, 100)
    verify_existing_budget(tmp_path, ledger.path, True)
    ledger.stop('do_not_restart')
    with pytest.raises(ValueError, match='never reset'):
        verify_existing_budget(tmp_path, ledger.path, True)


def test_continuation_refuses_owned_budget_before_key_read_evaluation_or_new_output(state, monkeypatch):
    from scripts import resume_end_to_end as resume
    from scripts.real_eval_budget import evaluation_run_ownership

    _, previous = state
    ledger = Envelope(previous / 'budget.sqlite3')
    before = ledger.snapshot()
    (previous / 'budget.json').write_text(json.dumps(before))
    (previous / 'catalog.json').write_bytes(resume.DEFAULT_CATALOG.read_bytes())
    output = previous / 'new-segment'
    dispatched = []
    monkeypatch.setattr(resume, 'load_live_provider', lambda *args: dispatched.append('key'))
    monkeypatch.setattr(
        resume, 'evaluate', lambda *args, **kwargs: dispatched.append('evaluate') or {'stop_reason': None}
    )
    monkeypatch.setattr(
        resume.sys,
        'argv',
        [
            'resume_end_to_end',
            '--manifest',
            str(previous / 'manifest.json'),
            '--previous-run',
            str(previous),
            '--key-file',
            str(previous / 'must-never-be-read'),
            '--budget-state',
            str(ledger.path),
            '--output-dir',
            str(output),
            '--source-revision',
            'a' * 40,
        ],
    )
    with evaluation_run_ownership(ledger.path), pytest.raises(ValueError, match='already owned'):
        resume.main()
    assert dispatched == []
    assert not output.exists()
    assert ledger.snapshot() == before


@pytest.mark.parametrize('evaluation_fails', [False, True])
def test_continuation_holds_same_owner_through_validation_key_and_evaluation_and_releases_on_exit(
    state, monkeypatch, evaluation_fails
):
    from scripts import resume_end_to_end as resume
    from scripts.real_eval_budget import evaluation_run_ownership

    _, previous = state
    ledger = Envelope(previous / 'budget.sqlite3')
    before = ledger.snapshot()
    (previous / 'budget.json').write_text(json.dumps(before))
    (previous / 'catalog.json').write_bytes(resume.DEFAULT_CATALOG.read_bytes())
    original_answers = (previous / 'answers.json').read_bytes()
    output = previous / 'new-segment'
    phases = []
    verify = resume.verify_existing_budget

    def require_ownership(phase):
        with pytest.raises(ValueError, match='already owned'), evaluation_run_ownership(ledger.path):
            pass
        phases.append(phase)

    def verify_owned(*args):
        require_ownership('verify')
        verify(*args)

    def load(*args):
        require_ownership('key')
        return object()

    def evaluate(*args, **kwargs):
        require_ownership('evaluate')
        if evaluation_fails:
            raise RuntimeError('synthetic_evaluation_failure')
        return {'stop_reason': None}

    monkeypatch.setattr(resume, 'verify_existing_budget', verify_owned)
    monkeypatch.setattr(resume, 'load_live_provider', load)
    monkeypatch.setattr(resume, 'evaluate', evaluate)
    monkeypatch.setattr(
        resume.sys,
        'argv',
        [
            'resume_end_to_end',
            '--manifest',
            str(previous / 'manifest.json'),
            '--previous-run',
            str(previous),
            '--key-file',
            str(previous / 'synthetic-never-read'),
            '--budget-state',
            str(ledger.path),
            '--output-dir',
            str(output),
            '--source-revision',
            'a' * 40,
        ],
    )
    if evaluation_fails:
        with pytest.raises(RuntimeError, match='synthetic_evaluation_failure'):
            resume.main()
    else:
        resume.main()
    assert phases == ['verify', 'key', 'evaluate']
    with evaluation_run_ownership(ledger.path):
        pass
    assert ledger.snapshot() == before
    assert (previous / 'answers.json').read_bytes() == original_answers
