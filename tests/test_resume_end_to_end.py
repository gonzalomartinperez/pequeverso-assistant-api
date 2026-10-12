"""Deterministic recovery boundaries; no key reads or provider calls."""

import json

import pytest

from scripts.resume_end_to_end import remaining_cases


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
