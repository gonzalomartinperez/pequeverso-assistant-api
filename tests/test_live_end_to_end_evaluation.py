"""Explicit live runner opt-in tested with synthetic keys and mocked provider transport only."""

import json
import stat

import httpx2
import pytest

from scripts.evaluate_end_to_end import evaluate, load_live_provider
from scripts.real_eval_budget import BoundedProvider, Envelope


def matrix(turns=2):
    return {
        'cases': [
            {
                'id': 'live-synthetic',
                'family': 'inclusions',
                'locale': 'es',
                'turns': [
                    {'question': '¿Qué incluye el kit?', 'expected_language': 'es'} for _ in range(turns)
                ],
            }
        ]
    }


def test_replay_wrong_answer_stops_even_when_history_and_terminal_remain_valid(tmp_path, monkeypatch):
    from scripts import evaluate_end_to_end as runner

    def success(request):
        answer = json.dumps(
            {
                'answer': 'Puedes consultar la página del producto.',
                'references': [],
                'sources': [],
                'follow_ups': [],
            }
        )
        events = [
            {'type': 'response.output_text.delta', 'delta': answer},
            {
                'type': 'response.completed',
                'response': {
                    'id': 'resp-synthetic',
                    'object': 'response',
                    'created_at': 0,
                    'status': 'completed',
                    'model': 'gpt-6-luna',
                    'output': [],
                    'usage': {'input_tokens': 500, 'output_tokens': 50, 'total_tokens': 550},
                },
            },
        ]
        return httpx2.Response(
            200,
            headers={'content-type': 'text/event-stream'},
            content=''.join(f'data: {json.dumps(e)}\n\n' for e in events),
        )

    real_ask = runner.ask

    def wrong_replay(*args, **kwargs):
        result = real_ask(*args, **kwargs)
        if kwargs.get('on_event') is None:
            for event in result['events']:
                if event['type'] == 'message.completed':
                    event['message']['content'] = 'Una respuesta distinta que no está en el historial.'
        return result

    monkeypatch.setattr(runner, 'ask', wrong_replay)
    output = tmp_path / 'answers'
    output.mkdir(mode=0o700)
    envelope = Envelope(tmp_path / 'budget.sqlite3')
    bounded = BoundedProvider('synthetic-key', envelope, transport=httpx2.MockTransport(success))
    result = runner.evaluate(matrix(), output, 'abcdef0', bounded=bounded)
    assert result['queries'] == 1 and result['stop_reason'] == 'replay_gate_failure'
    row = result['cases'][0]
    assert row['replay_history_unchanged'] and row['replay_terminal'] == ['run.completed']
    assert row['replay_new_provider_calls'] == 0 and not row['replay_answer_matches']
    assert envelope.snapshot()['attempts'] == 1


def test_live_socket_path_usage_replay_and_private_artifacts(tmp_path):
    calls = []

    def transport(request):
        wire = json.loads(request.content)
        calls.append(wire)
        assert wire['model'] == 'gpt-6-luna'
        assert wire['reasoning'] == {'effort': 'medium'}
        assert wire['store'] is False and wire['service_tier'] == 'default'
        answer = json.dumps(
            {
                'answer': 'Puedes consultar la página del producto.',
                'references': [],
                'sources': [],
                'follow_ups': [],
            }
        )
        events = [
            {'type': 'response.output_text.delta', 'delta': answer},
            {
                'type': 'response.completed',
                'response': {
                    'id': 'resp-synthetic',
                    'object': 'response',
                    'created_at': 0,
                    'status': 'completed',
                    'model': 'gpt-6-luna',
                    'output': [],
                    'usage': {'input_tokens': 5000, 'output_tokens': 100, 'total_tokens': 5100},
                },
            },
        ]
        return httpx2.Response(
            200,
            headers={'content-type': 'text/event-stream'},
            content=''.join(f'data: {json.dumps(e)}\n\n' for e in events),
        )

    output = tmp_path / 'answers'
    output.mkdir(mode=0o700)
    envelope = Envelope(tmp_path / 'budget.sqlite3')
    bounded = BoundedProvider('synthetic-key', envelope, transport=httpx2.MockTransport(transport))
    result = evaluate(matrix(), output, '156a0cd', bounded=bounded)
    assert result['queries'] == 2 and result['stop_reason'] is None
    assert result['history_mismatches'] == 0
    assert result['cases'][-1]['replay_new_provider_calls'] == 0
    assert result['cases'][-1]['replay_history_unchanged']
    assert len(calls) == 2 and envelope.snapshot()['attempts'] == 2
    assert result['actual_provider_usd'] is None and result['uncertain_paid_calls'] == 0
    assert envelope.snapshot()['reserved_micro_usd'] == 2970
    assert result['invalid_csrf_http_status'] == result['invalid_origin_http_status'] == 403
    serialized = json.dumps(result)
    assert 'synthetic-key' not in serialized and 'csrf_token' not in serialized
    for file in output.iterdir():
        assert stat.S_IMODE(file.stat().st_mode) == 0o600


@pytest.mark.parametrize('status', [401, 429, 500])
def test_live_failure_never_retries_and_preserves_unknown_reservation(tmp_path, status, caplog):
    calls = []
    sentinel = 'sk-proj-SYNTHETIC-MUST-NOT-LEAK'

    def failure(request):
        calls.append(request.url.path)
        return httpx2.Response(status, json={'error': {'message': sentinel, 'type': 'invalid_request_error'}})

    output = tmp_path / 'answers'
    output.mkdir(mode=0o700)
    envelope = Envelope(tmp_path / 'budget.sqlite3')
    bounded = BoundedProvider(sentinel, envelope, transport=httpx2.MockTransport(failure))
    result = evaluate(matrix(3), output, '156a0cd', bounded=bounded)
    assert len(calls) == result['queries'] == 1
    assert result['stop_reason'] and len(result['missing_turns']) == 2
    assert result['uncertain_paid_calls'] == 1
    assert Envelope(envelope.path).snapshot()['reserved_micro_usd'] == 11000
    assert sentinel not in caplog.text
    for artifact in ('answers.json', 'summary.json', 'inflight.json', 'budget.json'):
        assert sentinel not in (output / artifact).read_text()


def test_exhausted_shared_envelope_never_dispatches(tmp_path):
    output = tmp_path / 'answers'
    output.mkdir(mode=0o700)
    envelope = Envelope(tmp_path / 'budget.sqlite3', 11000)
    envelope.reserve()
    bounded = BoundedProvider(
        'synthetic-key', envelope, transport=httpx2.MockTransport(lambda _: pytest.fail('no dispatch'))
    )
    result = evaluate(matrix(), output, '156a0cd', bounded=bounded)
    assert result['queries'] == 0 and len(result['missing_turns']) == 2
    assert result['stop_reason'] == 'budget_or_attempt_limit'
    assert envelope.snapshot()['attempts'] == 1


def test_live_key_loader_validates_private_model_configuration(tmp_path):
    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    key = private / 'key.env'
    key.write_text('OPENAI_API_KEY=synthetic-key\nOPENAI_MODEL=gpt-6-luna\nOPENAI_REASONING_EFFORT=medium\n')
    key.chmod(0o600)
    provider = load_live_provider(key, private / 'common.sqlite3')
    assert provider.model == 'gpt-6-luna'
    key.chmod(0o644)
    with pytest.raises(ValueError, match='mode600'):
        load_live_provider(key, private / 'other.sqlite3')
    key.chmod(0o600)
    key.write_text('OPENAI_API_KEY=synthetic-key\nOPENAI_MODEL=other\nOPENAI_REASONING_EFFORT=medium\n')
    with pytest.raises(ValueError, match='authorized model'):
        load_live_provider(key, private / 'other.sqlite3')
    link = private / 'linked.env'
    link.symlink_to(key)
    with pytest.raises(ValueError, match='symlinks'):
        load_live_provider(link, private / 'other.sqlite3')


def test_missing_usage_halts_with_unknown_cost_and_keeps_completed_history(tmp_path):
    def success_without_usage(request):
        answer = json.dumps(
            {
                'answer': 'Puedes consultar la página del producto.',
                'references': [],
                'sources': [],
                'follow_ups': [],
            }
        )
        events = [
            {'type': 'response.output_text.delta', 'delta': answer},
            {
                'type': 'response.completed',
                'response': {
                    'id': 'resp-synthetic',
                    'object': 'response',
                    'created_at': 0,
                    'status': 'completed',
                    'model': 'gpt-6-luna',
                    'output': [],
                },
            },
        ]
        return httpx2.Response(
            200,
            headers={'content-type': 'text/event-stream'},
            content=''.join(f'data: {json.dumps(e)}\n\n' for e in events),
        )

    output = tmp_path / 'answers'
    output.mkdir(mode=0o700)
    envelope = Envelope(tmp_path / 'budget.sqlite3')
    bounded = BoundedProvider(
        'synthetic-key', envelope, transport=httpx2.MockTransport(success_without_usage)
    )
    result = evaluate(matrix(3), output, '156a0cd', bounded=bounded)
    assert result['queries'] == result['dispatched_attempts'] == 1
    assert result['stop_reason'] == 'missing_usage' and result['uncertain_paid_calls'] == 1
    assert result['history_mismatches'] == 0
    assert envelope.snapshot()['reserved_micro_usd'] == 11000
    assert len(result['missing_turns']) == 2


def test_orderly_interrupt_preserves_partial_events_and_stops_shared_envelope(tmp_path, monkeypatch):
    from scripts import evaluate_end_to_end as runner

    def interrupted(*args, on_event=None, **kwargs):
        on_event([{'type': 'run.started', 'run_id': 'synthetic-run'}])
        raise KeyboardInterrupt

    monkeypatch.setattr(runner, 'ask', interrupted)
    output = tmp_path / 'answers'
    output.mkdir(mode=0o700)
    envelope = Envelope(tmp_path / 'budget.sqlite3')
    bounded = BoundedProvider(
        'synthetic-key', envelope, transport=httpx2.MockTransport(lambda _: pytest.fail('no dispatch'))
    )
    result = runner.evaluate(matrix(), output, '156a0cd', bounded=bounded)
    assert result['stop_reason'] == 'interrupted'
    assert envelope.snapshot()['stop_reason'] == 'interrupted'
    assert result['queries'] == 0 and len(result['missing_turns']) == 2
    assert json.loads((output / 'inflight.json').read_text())['events'][0]['type'] == 'run.started'
    assert json.loads((output / 'answers.json').read_text()) == []


def test_default_cli_ignores_key_file_and_live_ambient_settings(tmp_path, monkeypatch):
    from scripts import evaluate_end_to_end as runner

    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-environment-must-ignore')
    monkeypatch.setenv('AI_PROVIDER', 'openai')
    monkeypatch.setenv('ALLOW_PAID_AI', 'true')
    monkeypatch.setattr(runner, 'load_live_provider', lambda *args: pytest.fail('no private file read'))

    def fixture_only(manifest, destination, revision, *, bounded=None):
        assert bounded is None and revision == '156a0cd'
        return {'cases': [], 'fixture_only': True, 'stop_reason': None}

    monkeypatch.setattr(runner, 'evaluate', fixture_only)
    monkeypatch.setattr(
        'sys.argv',
        [
            'evaluate_end_to_end.py',
            '--output-dir',
            str(tmp_path / 'new'),
            '--source-revision',
            '156a0cd',
            '--key-file',
            '/never/read/key',
            '--budget-state',
            '/never/read/state',
        ],
    )
    runner.main()


def test_prepared_evidence_is_distinct_from_dispatch_and_live_settings_are_accurate(tmp_path, monkeypatch):
    from scripts import evaluate_end_to_end as runner

    actual_create = runner.create_app
    configurations = []

    def inspect_settings(settings, **kwargs):
        configurations.append(settings)
        assert settings.ai_provider == 'openai' and settings.allow_paid_ai
        assert settings.openai_api_key.get_secret_value() == 'synthetic-key'
        return actual_create(settings, **kwargs)

    monkeypatch.setattr(runner, 'create_app', inspect_settings)
    monkeypatch.setattr('scripts.real_eval_budget.bound_bytes', lambda _: 25000)
    output = tmp_path / 'answers'
    output.mkdir(mode=0o700)
    envelope = Envelope(tmp_path / 'budget.sqlite3')
    bounded = BoundedProvider(
        'synthetic-key', envelope, transport=httpx2.MockTransport(lambda _: pytest.fail('no dispatch'))
    )
    result = runner.evaluate(matrix(), output, '156a0cd', bounded=bounded)
    assert len(configurations) == 1
    assert result['provider_calls'] == result['dispatched_attempts'] == 0
    assert result['prepared_evidence_count'] == 1
    assert result['cases'][0]['provider_calls'] == 0
    assert result['cases'][0]['prepared_evidence_count'] == 1
    assert result['cases'][0]['provider'] == 'not-dispatched'
    assert result['stop_reason'] == 'request_bound'
    assert 'synthetic-key' not in json.dumps(result)


def test_prior_history_mutation_is_detected_even_when_final_message_matches(tmp_path, monkeypatch):
    import httpx

    from scripts import evaluate_end_to_end as runner

    original = httpx.Client.post

    def mutate_restore(client, url, *args, **kwargs):
        response = original(client, url, *args, **kwargs)
        if url == '/api/v1/session' and response.status_code == 200:
            payload = response.json()
            if len(payload['messages']) == 4:
                payload['messages'][1]['content'] = 'synthetic changed earlier answer'
                response._content = json.dumps(payload).encode()
        return response

    monkeypatch.setattr(httpx.Client, 'post', mutate_restore)
    result = runner.evaluate(matrix(), tmp_path, '156a0cd')
    assert result['history_mismatches'] == 1
    assert not result['cases'][-1]['prior_history_preserved']
    assert not result['cases'][-1]['history_matches']
