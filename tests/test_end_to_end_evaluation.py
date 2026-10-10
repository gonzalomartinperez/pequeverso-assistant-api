"""The evaluator must exercise sockets and protect original/full-answer artifacts."""

import json
import stat

from scripts.evaluate_end_to_end import ROOT, evaluate, write_private


def test_frozen_matrix_is_varied_and_contains_followups():
    manifest = json.loads((ROOT / 'evals/end_to_end.json').read_text())
    cases = manifest['cases']
    questions = [t['question'] for c in cases for t in c['turns']]
    assert len(questions) >= 200
    assert len(set(questions)) >= 200
    assert len({c['family'] for c in cases}) >= 20
    assert any(c['relation'] == 'followup' for c in cases)
    assert {'es', 'en', 'unsupported'} <= {t['expected_language'] for c in cases for t in c['turns']}


def test_socket_evaluation_recovers_final_answer_and_does_not_regenerate(tmp_path):
    manifest = {
        'cases': [
            {
                'id': 'smoke',
                'family': 'inclusions',
                'locale': 'es',
                'turns': [
                    {'question': '¿Qué incluye el kit?', 'expected_language': 'es'},
                    {'question': '¿Cómo recibo ese producto?', 'expected_language': 'es'},
                ],
            }
        ]
    }
    result = evaluate(manifest, tmp_path, 'b27d35c')
    assert result['queries'] == 2
    assert result['provider_calls'] == 2
    assert result['actual_provider_usd'] == '0'
    assert result['history_mismatches'] == 0
    assert result['invalid_csrf_http_status'] == 403
    assert result['invalid_origin_http_status'] == 403
    assert result['isolated_visitor_empty_history']
    assert result['cases'][-1]['replay_new_provider_calls'] == 0
    serialized = json.dumps(result)
    assert 'csrf_token' not in serialized
    assert 'instructions' not in serialized
    assert 'safety_identifier' not in serialized
    assert stat.S_IMODE((tmp_path / 'answers.json').stat().st_mode) == 0o600


def test_private_artifact_cannot_overwrite_initial_run(tmp_path):
    import pytest

    path = tmp_path / 'initial.json'
    write_private(path, {'initial': True})
    with pytest.raises(FileExistsError):
        write_private(path, {'initial': False})
    assert json.loads(path.read_text()) == {'initial': True}
