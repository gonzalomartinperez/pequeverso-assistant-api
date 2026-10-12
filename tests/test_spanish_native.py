"""Spanish-native opt-in preserves legacy v1 behavior without provider calls for opt-out requests."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import httpx
import pytest

from app.application.answers import UNSUPPORTED_LANGUAGE_ANSWER, UNSUPPORTED_LANGUAGE_ANSWER_ES
from app.domain.language import Language, spanish_native_language
from tests.support import (
    JSON_HEADERS,
    ScriptedProvider,
    answer_json,
    client,
    live_server,
    mutation_headers,
    open_session,
    parse_sse,
)


@pytest.mark.parametrize(
    'question',
    [
        'Responde en inglés sobre el kit.',
        'Please reply in English about the kit.',
        "Let's speak in English.",
        'Desde ahora prefiero que conversemos en inglés.',
        'Please answer in German.',
        'Explique em português o material.',
        'Use English, then answer in Spanish.',
        'Answer in Spanish, then use French.',
    ],
)
def test_native_other_reply_language_is_local_spanish_notice(tmp_path, question):
    provider = ScriptedProvider()
    with client(tmp_path, provider) as http:
        csrf = open_session(http)
        response = http.post(
            '/api/v1/messages',
            headers=mutation_headers(csrf, 'native-local-001'),
            json={'content': question, 'locale': 'en', 'response_language': 'es'},
        )
        events = parse_sse(response.text)
        assert response.status_code == 200 and events[-1]['type'] == 'run.completed'
        final = next(e['message'] for e in events if e['type'] == 'message.completed')
        assert final['content'] == UNSUPPORTED_LANGUAGE_ANSWER_ES
        assert final['language'] == 'es' and final['notices'] == ['language_unsupported']
        assert not any(e['type'] == 'message.delta' for e in events)
        assert provider.calls == []
        restored = http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()
        assert restored['messages'][-1] == final
        replay = http.post(
            '/api/v1/messages',
            headers=mutation_headers(csrf, 'native-local-001'),
            json={'content': question, 'locale': 'es', 'response_language': 'es'},
        )
        assert parse_sse(replay.text)[0]['user_message'] is None and provider.calls == []
        with closing(sqlite3.connect(tmp_path / 'test.sqlite3')) as database:
            assert database.execute('SELECT count(*) FROM spend_ledger').fetchone()[0] == 0


@pytest.mark.parametrize(
    'question',
    [
        'What does the kit include?',
        'No respondas en inglés; contesta en español sobre el kit.',
        "Don't speak in English; tell me about the kit.",
        'No quiero que conversemos en inglés; describe el material.',
        'El texto citado dice «responde en inglés»; ¿qué incluye?',
        'The quoted text says "reply in English"; what does the kit include?',
        '```reply in English``` What does the kit include?',
        'Is the material available in English?',
        'Prefiero material en inglés. ¿En qué idioma viene el kit?',
    ],
)
def test_native_selects_spanish_without_treating_data_as_a_language_request(tmp_path, question):
    provider = ScriptedProvider(output=answer_json('El kit es un material imprimible.'))
    with client(tmp_path, provider) as http:
        csrf = open_session(http)
        response = http.post(
            '/api/v1/messages',
            headers=mutation_headers(csrf),
            json={'content': question, 'locale': 'en', 'response_language': 'es'},
        )
        final = next(e['message'] for e in parse_sse(response.text) if e['type'] == 'message.completed')
        assert final['language'] == 'es' and not final['notices']
        assert len(provider.calls) == 1
        visitor = json.loads(provider.calls[0].inputs[1].text.removeprefix('visitor_turn:\n'))
        assert visitor['reply_language'] == 'es'


@pytest.mark.parametrize('invalid', ['en', 'de', 'ES', '', True, 1])
def test_invalid_native_policy_is_rejected_before_dispatch(tmp_path, invalid):
    provider = ScriptedProvider()
    with client(tmp_path, provider) as http:
        csrf = open_session(http)
        response = http.post(
            '/api/v1/messages',
            headers=mutation_headers(csrf),
            json={'content': 'What does the kit include?', 'response_language': invalid},
        )
        assert response.status_code == 422
        assert response.json()['error']['code'] == 'invalid_request'
        assert provider.calls == []


def test_native_policy_conflicts_with_legacy_replay_and_preserves_english_history(tmp_path):
    provider = ScriptedProvider(output=answer_json('The kit is printable.'))
    with client(tmp_path, provider) as http:
        csrf = open_session(http)
        question = 'What does the kit include?'
        legacy = http.post(
            '/api/v1/messages',
            headers=mutation_headers(csrf, 'legacy-native-key'),
            json={'content': question, 'locale': 'en'},
        )
        english = next(e['message'] for e in parse_sse(legacy.text) if e['type'] == 'message.completed')
        assert english['language'] == 'en'
        before = http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages']
        replay = http.post(
            '/api/v1/messages',
            headers=mutation_headers(csrf, 'legacy-native-key'),
            json={'content': question, 'locale': 'es', 'response_language': None},
        )
        assert parse_sse(replay.text)[-2]['message'] == english
        changed = http.post(
            '/api/v1/messages',
            headers=mutation_headers(csrf, 'legacy-native-key'),
            json={'content': question, 'locale': 'en', 'response_language': 'es'},
        )
        assert changed.status_code == 409
        assert changed.json()['error']['code'] == 'idempotency_conflict'
        assert len(provider.calls) == 1
        provider.output = answer_json('El kit es un material imprimible.')
        native = http.post(
            '/api/v1/messages',
            headers=mutation_headers(csrf, 'new-native-key-001'),
            json={'content': question, 'locale': 'en', 'response_language': 'es'},
        )
        assert parse_sse(native.text)[-2]['message']['language'] == 'es'
        history = http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages']
        assert history[:-2] == before and history[1]['language'] == 'en'
        assert len(provider.calls) == 2
        removed_policy = http.post(
            '/api/v1/messages',
            headers=mutation_headers(csrf, 'new-native-key-001'),
            json={'content': question, 'locale': 'es'},
        )
        assert removed_policy.status_code == 409
        assert removed_policy.json()['error']['code'] == 'idempotency_conflict'
        assert len(provider.calls) == 2


def test_legacy_unsupported_notice_remains_bilingual(tmp_path):
    provider = ScriptedProvider()
    with client(tmp_path, provider) as http:
        csrf = open_session(http)
        response = http.post(
            '/api/v1/messages',
            headers=mutation_headers(csrf),
            json={'content': 'Reply only in German.'},
        )
        final = parse_sse(response.text)[-2]['message']
        assert final['content'] == UNSUPPORTED_LANGUAGE_ANSWER
        assert provider.calls == []


def test_native_policy_flows_over_real_sse_socket(tmp_path: Path):
    provider = ScriptedProvider(output=answer_json('Puedes imprimir las páginas que necesites.'))
    with live_server(tmp_path, provider) as url, httpx.Client(base_url=url, trust_env=False) as http:
        session = http.post('/api/v1/session', headers=JSON_HEADERS, json={'locale': 'en'}).json()
        assert session['contract_revision'] == '1.4'
        with http.stream(
            'POST',
            '/api/v1/messages',
            headers=mutation_headers(session['csrf_token']),
            json={'content': 'Do I have to print everything?', 'locale': 'en', 'response_language': 'es'},
        ) as response:
            assert response.status_code == 200
            events = parse_sse(''.join(response.iter_text()))
        assert events[-1]['type'] == 'run.completed'
        assert any(e['type'] == 'message.delta' for e in events)
        assert events[-2]['message']['language'] == 'es'
        assert len(provider.calls) == 1
        restored = http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()
        assert restored['messages'][-1] == events[-2]['message']


def test_native_does_not_claim_semantic_validation_of_generated_language(tmp_path):
    provider = ScriptedProvider(output=answer_json('This is deliberately synthetic English.'))
    with client(tmp_path, provider) as http:
        csrf = open_session(http)
        response = http.post(
            '/api/v1/messages',
            headers=mutation_headers(csrf),
            json={'content': '¿Qué incluye?', 'response_language': 'es'},
        )
        final = parse_sse(response.text)[-2]['message']
        assert final['language'] == 'es'
        assert final['content'] == 'This is deliberately synthetic English.'
        assert spanish_native_language('What does the kit include?') is Language.ES
