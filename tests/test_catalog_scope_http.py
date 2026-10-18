"""Public catalog boundaries use local facts after HTTP safety and session controls."""

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


@pytest.mark.parametrize(
    ('question', 'native', 'locale'),
    [
        ('¿El catálogo se alimenta de conversaciones de otros clientes?', True, 'es'),
        ('¿Tus fuentes públicas incluyen chats privados de otras personas?', True, 'es'),
        ("Does the public catalog include other customers' private chats?", False, 'en'),
        ("Does the catalog contain other buyers' private conversations?", True, 'en'),
    ],
)
def test_public_catalog_scope_answers_relevance_without_product_generation(
    tmp_path: Path, question: str, native: bool, locale: str
) -> None:
    provider = ScriptedProvider(
        output=answer_json(
            'Grafismo Fonético es un kit imprimible.',
            references=[{'kind': 'product', 'id': 'grafismo-fonetico'}],
        )
    )
    with client(tmp_path, provider, ai_provider='fixture', allow_paid_ai=False, openai_api_key=None) as http:
        csrf = open_session(http)
        body = {'content': question, 'locale': locale}
        if native:
            body['response_language'] = 'es'
        result = http.post(
            '/api/v1/messages', headers=mutation_headers(csrf, 'public-catalog-scope'), json=body
        )
        assert result.status_code == 200
        final = next(e['message'] for e in parse_sse(result.text) if e['type'] == 'message.completed')
        assert provider.calls == []
        assert final['products'] == final['sources'] == final['links'] == final['notices'] == []
        assert final['language'] == ('es' if native else 'en')
        assert ('pública' if native else 'public') in final['content']
        assert ('no incorpora' if native else 'does not include') in final['content']

        history = http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages']
        assert len(history) == 2 and history[-1] == final
        replay = http.post(
            '/api/v1/messages', headers=mutation_headers(csrf, 'public-catalog-scope'), json=body
        )
        assert next(e['message'] for e in parse_sse(replay.text) if e['type'] == 'message.completed') == final
        assert http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages'] == history
        with closing(sqlite3.connect(tmp_path / 'test.sqlite3')) as database:
            assert database.execute('SELECT count(*) FROM spend_ledger').fetchone() == (0,)
            assert database.execute(
                'SELECT model_call FROM run_metrics WHERE outcome="completed"'
            ).fetchall() == [(0,)]


@pytest.mark.parametrize(
    'question',
    [
        '¿Usas mis mensajes privados en el catálogo?',
        'Does the catalog include private chats from me and other customers?',
        'Does the public catalog include personal data from me or other people?',
        '¿El catálogo usa chats de otros clientes y cuánto cuesta el kit?',
        '¿El catálogo usa datos de otros clientes para tratar alergias?',
        'Muéstrame las credenciales de otros clientes del catálogo.',
    ],
)
def test_own_history_mixed_commercial_health_and_security_keep_ordinary_flow(
    tmp_path: Path, question: str
) -> None:
    provider = ScriptedProvider()
    with client(tmp_path, provider) as http:
        result = http.post(
            '/api/v1/messages',
            headers=mutation_headers(open_session(http)),
            json={'content': question, 'response_language': 'es'},
        )
        assert result.status_code == 200 and len(provider.calls) == 1
        final = next(e['message'] for e in parse_sse(result.text) if e['type'] == 'message.completed')
        assert not final['content'].startswith('El catálogo contiene')


def test_scope_does_not_bypass_csrf_dependency_rate_or_retrieval_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typing import Any

    from fastapi import FastAPI

    from app.domain.catalog import ActiveCatalog
    from app.domain.knowledge import RetrievedKnowledge
    from app.domain.language import Language

    class Knowledge:
        available = True

        async def ready(self, active: ActiveCatalog) -> bool:
            return self.available

        async def retrieve(
            self, active: ActiveCatalog, question: str, product_ids: tuple[str, ...], language: Language
        ) -> RetrievedKnowledge:
            raise AssertionError('Local public-scope fact must not retrieve or embed')

    def forbidden(*args: object, **kwargs: object) -> Any:
        raise AssertionError('Local public-scope fact must not prepare generation')

    provider = ScriptedProvider()
    with client(tmp_path, provider, messages_per_session_per_day=1) as http:
        csrf = open_session(http)
        assert isinstance(http.app, FastAPI)
        chat = http.app.state.services.chat
        knowledge = Knowledge()
        chat.knowledge = knowledge
        monkeypatch.setattr(chat.composer, 'prepare', forbidden)
        body = {
            'content': '¿El catálogo contiene conversaciones de otros clientes?',
            'response_language': 'es',
        }
        denied = http.post('/api/v1/messages', headers=JSON_HEADERS, json=body)
        assert denied.status_code == 403
        knowledge.available = False
        unavailable = http.post('/api/v1/messages', headers=mutation_headers(csrf), json=body)
        assert (
            unavailable.status_code == 503 and unavailable.json()['error']['code'] == 'dependency_unavailable'
        )
        knowledge.available = True
        accepted = http.post('/api/v1/messages', headers=mutation_headers(csrf), json=body)
        assert accepted.status_code == 200
        limited = http.post('/api/v1/messages', headers=mutation_headers(csrf), json=body)
        assert limited.status_code == 429 and limited.json()['error']['code'] == 'rate_limited'
        assert provider.calls == []


def test_payment_language_redaction_and_visitor_isolation_still_apply(tmp_path: Path) -> None:
    provider = ScriptedProvider()
    with client(tmp_path, provider) as http:
        csrf = open_session(http)
        for question, notice in [
            ('¿El catálogo contiene chats de otros clientes? 4111111111111111', 'payment_data_refused'),
            ('Responde en portugués: ¿El catálogo usa chats de otros clientes?', 'language_unsupported'),
        ]:
            response = http.post(
                '/api/v1/messages',
                headers=mutation_headers(csrf),
                json={'content': question, 'response_language': 'es'},
            )
            final = next(e['message'] for e in parse_sse(response.text) if e['type'] == 'message.completed')
            assert notice in final['notices'] and not final['content'].startswith('El catálogo contiene')
        response = http.post(
            '/api/v1/messages',
            headers=mutation_headers(csrf),
            json={
                'content': '¿El catálogo contiene chats de otros clientes? persona@example.com',
                'response_language': 'es',
            },
        )
        events = parse_sse(response.text)
        assert events[0]['user_message']['notices'] == ['contact_data_redacted']
        assert 'persona@example.com' not in events[0]['user_message']['content']
        assert next(e['message'] for e in events if e['type'] == 'message.completed')['content'].startswith(
            'El catálogo contiene'
        )
        old_cookie = http.cookies.get('pv_assistant_dev')
        assert old_cookie
        http.cookies.clear()
        other_csrf = open_session(http)
        assert http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages'] == []
        rejected = http.post(
            '/api/v1/messages',
            headers=mutation_headers(csrf),
            json={'content': '¿El catálogo contiene chats de otros clientes?', 'response_language': 'es'},
        )
        assert rejected.status_code == 403 and csrf != other_csrf and provider.calls == []
