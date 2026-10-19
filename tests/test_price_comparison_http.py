"""Price uncertainty is resolved before generation, streaming, retrieval and accounting."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from tests.support import (
    JSON_HEADERS,
    ScriptedProvider,
    answer_json,
    client,
    mutation_headers,
    open_session,
    parse_sse,
)


def test_unknown_price_relation_never_dispatches_or_streams_a_categorical_answer(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        output=answer_json(
            'No. Grafismo Fonético cuesta US$14,99; no conozco el precio de la Guía de Alimentación para Bebés.',
            references=[
                {'kind': 'product', 'id': 'grafismo-fonetico'},
                {'kind': 'product', 'id': 'alimentacion-bebe'},
            ],
        )
    )
    with client(tmp_path, provider) as http:
        csrf = open_session(http)
        payload = {'content': '¿Ambos tienen el mismo precio?', 'response_language': 'es'}
        response = http.post(
            '/api/v1/messages', headers=mutation_headers(csrf, 'price-relation-original'), json=payload
        )
        assert response.status_code == 200
        events = parse_sse(response.text)
        final = next(event['message'] for event in events if event['type'] == 'message.completed')
        assert provider.calls == []
        assert not any(event['type'] == 'message.delta' for event in events)
        assert 'comparar' in final['content'].lower()
        assert 'Guía de Alimentación para Bebés' in final['content']
        assert not final['content'].startswith(('No.', 'Sí.', 'Yes.', 'They are different'))
        assert final['notices'] == []
        assert {product['id'] for product in final['products']} == {'grafismo-fonetico', 'alimentacion-bebe'}
        history = http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages']
        assert len(history) == 2 and history[-1] == final
        replay = http.post(
            '/api/v1/messages', headers=mutation_headers(csrf, 'price-relation-original'), json=payload
        )
        assert next(e['message'] for e in parse_sse(replay.text) if e['type'] == 'message.completed') == final
        assert http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages'] == history
        with closing(sqlite3.connect(tmp_path / 'test.sqlite3')) as database:
            assert database.execute('SELECT count(*) FROM spend_ledger').fetchone() == (0,)
            assert database.execute('SELECT model_call FROM run_metrics').fetchall() == [(0,)]


@pytest.mark.parametrize(
    ('question', 'native', 'locale', 'language'),
    [
        ('¿El curso y el kit tienen precios diferentes?', True, 'es', 'es'),
        ('¿Los dos cuestan US$99?', True, 'es', 'es'),
        ('¿El curso es más barato que Grafismo?', True, 'es', 'es'),
        ('Do both cost the same?', False, 'en', 'en'),
        ('Are the course and kit different prices?', False, 'en', 'en'),
        ('Do both cost $14.99?', True, 'en', 'es'),
    ],
)
def test_unknown_comparison_variants_and_legacy_language_never_call_model(
    tmp_path: Path, question: str, native: bool, locale: str, language: str
) -> None:
    provider = ScriptedProvider(output=answer_json('No. They have different prices.'))
    with client(tmp_path, provider) as http:
        body = {
            'content': question,
            'locale': locale,
            'page': 'product',
            'context': {'opened_path': '/grafismo-fonetico/'},
        }
        if native:
            body['response_language'] = 'es'
        response = http.post('/api/v1/messages', headers=mutation_headers(open_session(http)), json=body)
        assert response.status_code == 200
        events = parse_sse(response.text)
        final = next(e['message'] for e in events if e['type'] == 'message.completed')
        assert not provider.calls and not any(e['type'] == 'message.delta' for e in events)
        assert final['language'] == language
        assert ('No puedo comparar' if language == 'es' else 'I cannot compare') in final['content']
        assert 'US$99' not in final['content']
        assert final['notices'] == []


def test_local_comparison_obeys_security_readiness_and_rate_before_retrieval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typing import Any

    from app.domain.catalog import ActiveCatalog

    class Knowledge:
        available = True

        async def ready(self, active: ActiveCatalog) -> bool:
            return self.available

        async def retrieve(self, *args: object, **kwargs: object) -> Any:
            raise AssertionError('Local price uncertainty must not retrieve or embed')

    class Official:
        async def read(self, *args: object, **kwargs: object) -> Any:
            raise AssertionError('Local price uncertainty must not fetch official evidence')

    def forbidden(*args: object, **kwargs: object) -> Any:
        raise AssertionError('Local price uncertainty must not prepare generation')

    provider = ScriptedProvider()
    with client(tmp_path, provider, messages_per_session_per_day=1) as http:
        csrf = open_session(http)
        chat = http.app.state.services.chat
        knowledge = Knowledge()
        chat.knowledge = knowledge
        chat.official_help = Official()
        monkeypatch.setattr(chat.composer, 'prepare', forbidden)
        body = {'content': '¿Ambos cuestan lo mismo?', 'response_language': 'es'}
        assert http.post('/api/v1/messages', headers=JSON_HEADERS, json=body).status_code == 403
        knowledge.available = False
        assert http.post('/api/v1/messages', headers=mutation_headers(csrf), json=body).status_code == 503
        knowledge.available = True
        assert http.post('/api/v1/messages', headers=mutation_headers(csrf), json=body).status_code == 200
        assert http.post('/api/v1/messages', headers=mutation_headers(csrf), json=body).status_code == 429
        assert provider.calls == []


def test_comparison_followup_and_visitor_isolation_preserve_real_history(tmp_path: Path) -> None:
    provider = ScriptedProvider()
    with client(tmp_path, provider) as http:
        csrf = open_session(http)
        first_cookies = dict(http.cookies)
        for number, text in enumerate(('¿Ambos cuestan lo mismo?', '¿Cuál cuesta menos?')):
            response = http.post(
                '/api/v1/messages',
                headers=mutation_headers(csrf, f'comparison-history-{number}'),
                json={'content': text, 'response_language': 'es'},
            )
            assert response.status_code == 200
            final = next(e['message'] for e in parse_sse(response.text) if e['type'] == 'message.completed')
            assert 'No puedo comparar' in final['content']
        history = http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages']
        assert len(history) == 4 and history[-1] == final
        http.cookies.clear()
        other = http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()
        assert other['messages'] == []
        other_response = http.post(
            '/api/v1/messages',
            headers=mutation_headers(other['csrf_token']),
            json={
                'content': '¿Cuestan lo mismo?',
                'page': 'product',
                'context': {'opened_path': '/grafismo-fonetico/'},
                'response_language': 'es',
            },
        )
        clarified = next(
            e['message'] for e in parse_sse(other_response.text) if e['type'] == 'message.completed'
        )
        assert clarified['products'] == [] and '¿Qué productos' in clarified['content']
        http.cookies.clear()
        http.cookies.update(first_cookies)
        assert http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages'] == history
        assert provider.calls == []


@pytest.mark.parametrize(
    ('question', 'notice'),
    [
        ('¿Ambos cuestan lo mismo? 4242 4242 4242 4242', 'payment_data_refused'),
        ('Responde en francés: ¿Ambos tienen el mismo precio?', 'language_unsupported'),
    ],
)
def test_security_and_language_remain_before_price_policy(tmp_path: Path, question: str, notice: str) -> None:
    provider = ScriptedProvider()
    with client(tmp_path, provider) as http:
        response = http.post(
            '/api/v1/messages',
            headers=mutation_headers(open_session(http)),
            json={'content': question, 'response_language': 'es'},
        )
        final = next(e['message'] for e in parse_sse(response.text) if e['type'] == 'message.completed')
        assert notice in final['notices'] and not final['products']
        assert provider.calls == []


def test_a_single_known_product_price_question_keeps_legitimate_no(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        output=answer_json('No. Grafismo Fonético tiene un precio de referencia de US$14,99.')
    )
    with client(tmp_path, provider) as http:
        response = http.post(
            '/api/v1/messages',
            headers=mutation_headers(open_session(http)),
            json={'content': '¿Grafismo cuesta US$10?', 'response_language': 'es'},
        )
        final = next(e['message'] for e in parse_sse(response.text) if e['type'] == 'message.completed')
        assert len(provider.calls) == 1 and final['content'].startswith('No.')
        assert 'answer_replaced' not in final['notices']


def test_contact_data_is_redacted_before_local_comparison_and_persistence(tmp_path: Path) -> None:
    provider = ScriptedProvider()
    with client(tmp_path, provider) as http:
        response = http.post(
            '/api/v1/messages',
            headers=mutation_headers(open_session(http)),
            json={
                'content': '¿Ambos cuestan lo mismo? Mi correo es prueba@example.org',
                'response_language': 'es',
            },
        )
        assert response.status_code == 200
        final = next(e['message'] for e in parse_sse(response.text) if e['type'] == 'message.completed')
        assert 'No puedo comparar' in final['content'] and not provider.calls
        history = http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages']
        assert history[-1] == final and len(history) == 2
        assert 'prueba@example.org' not in str(history)
        assert 'contact_data_redacted' in history[0]['notices']


def test_external_comparison_history_cannot_turn_both_into_two_catalog_cards(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        output=answer_json(
            'Grafismo Fonético es un kit imprimible.',
            references=[{'kind': 'product', 'id': 'grafismo-fonetico'}],
        )
    )
    with client(tmp_path, provider) as http:
        csrf = open_session(http)
        first = http.post(
            '/api/v1/messages',
            headers=mutation_headers(csrf, 'external-comparison'),
            json={
                'content': 'Compara Grafismo Fonético con el curso de otra editorial',
                'response_language': 'es',
            },
        )
        first_final = next(e['message'] for e in parse_sse(first.text) if e['type'] == 'message.completed')
        assert [p['id'] for p in first_final['products']] == ['grafismo-fonetico']
        second = http.post(
            '/api/v1/messages',
            headers=mutation_headers(csrf, 'ambiguous-both'),
            json={
                'content': '¿Ambos tienen el mismo precio?',
                'response_language': 'es',
            },
        )
        final = next(e['message'] for e in parse_sse(second.text) if e['type'] == 'message.completed')
        assert final['products'] == [] and '¿Qué productos' in final['content']
        assert len(provider.calls) == 1
        history = http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages']
        assert len(history) == 4 and history[-1] == final
