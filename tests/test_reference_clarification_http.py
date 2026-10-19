"""Ambiguous current referents cannot be silently resolved by the opened page."""

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


def completed(response):
    assert response.status_code == 200
    return next(e['message'] for e in parse_sse(response.text) if e['type'] == 'message.completed')


def test_comparison_then_printing_clarification_and_correction_are_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = ScriptedProvider(
        output=answer_json(
            'Grafismo Fonético es un kit imprimible y Guía de Alimentación para Bebés es un curso en video.',
            references=[
                {'kind': 'product', 'id': 'grafismo-fonetico'},
                {'kind': 'product', 'id': 'alimentacion-bebe'},
            ],
        )
    )
    with client(tmp_path, provider) as http:
        csrf = open_session(http)
        first = completed(
            http.post(
                '/api/v1/messages',
                headers=mutation_headers(csrf, 'compare-products'),
                json={'content': 'Compara los dos productos.', 'response_language': 'es'},
            )
        )
        assert len(first['products']) == 2

        class Knowledge:
            async def ready(self, active):
                return True

            async def retrieve(self, *args, **kwargs):
                raise AssertionError('Local reference clarification must not embed or retrieve')

        def forbidden(*args, **kwargs):
            raise AssertionError('Local reference clarification must not prepare generation')

        http.app.state.services.chat.knowledge = Knowledge()
        monkeypatch.setattr(http.app.state.services.chat.composer, 'prepare', forbidden)
        with closing(sqlite3.connect(tmp_path / 'test.sqlite3')) as database:
            spend_before = database.execute('SELECT count(*) FROM spend_ledger').fetchone()
        provider.output = answer_json(
            'Sí, ese producto se imprime.', references=[{'kind': 'product', 'id': 'grafismo-fonetico'}]
        )
        payload = {
            'content': 'Ese producto, ¿se imprime?',
            'response_language': 'es',
            'page': 'product',
            'context': {'opened_path': '/grafismo-fonetico/'},
        }
        second = completed(
            http.post('/api/v1/messages', headers=mutation_headers(csrf, 'uncertain'), json=payload)
        )
        assert len(provider.calls) == 1
        assert second['products'] == [] and '¿A qué producto' in second['content']
        provider.output = answer_json(
            'No, la guía no se puede imprimir.', references=[{'kind': 'product', 'id': 'alimentacion-bebe'}]
        )
        correction = {'content': 'Me refiero a la guía de alimentación.', 'response_language': 'es'}
        third_response = http.post(
            '/api/v1/messages', headers=mutation_headers(csrf, 'correction'), json=correction
        )
        third = completed(third_response)
        assert len(provider.calls) == 1
        assert 'video' in third['content'].lower() and 'confirm' in third['content'].lower()
        assert 'no se puede imprimir' not in third['content'].lower()
        assert [p['id'] for p in third['products']] == ['alimentacion-bebe']
        assert not any(e['type'] == 'message.delta' for e in parse_sse(third_response.text))
        replay = completed(
            http.post('/api/v1/messages', headers=mutation_headers(csrf, 'correction'), json=correction)
        )
        assert replay == third and len(provider.calls) == 1
        history = http.post('/api/v1/session', json={}, headers=JSON_HEADERS).json()['messages']
        assert len(history) == 6 and history[-1] == third
        with closing(sqlite3.connect(tmp_path / 'test.sqlite3')) as database:
            assert database.execute('SELECT count(*) FROM spend_ledger').fetchone() == spend_before
            assert database.execute('SELECT model_call FROM run_metrics').fetchall() == [(1,), (0,), (0,)]


def test_mixed_resource_comparison_keeps_counts_and_clarifies_guide(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        output=answer_json(
            'Safari de Sonidos y Sílabas tiene 40 páginas y Juega con Sonidos y Sílabas tiene 50.',
            references=[
                {'kind': 'resource', 'id': 'grafismo-fonetico/safari'},
                {'kind': 'resource', 'id': 'grafismo-fonetico/juega'},
            ],
        )
    )
    with client(tmp_path, provider) as http:
        csrf = open_session(http)
        first = completed(
            http.post(
                '/api/v1/messages',
                headers=mutation_headers(csrf, 'resources'),
                json={'content': '¿Safari y Juega tienen ambas 40 páginas?', 'response_language': 'es'},
            )
        )
        assert len(first['resources']) == 2
        provider.output = answer_json(
            'La guía 10 Minutos los incluye.',
            references=[{'kind': 'resource', 'id': 'grafismo-fonetico/10-minutos'}],
        )
        final = completed(
            http.post(
                '/api/v1/messages',
                headers=mutation_headers(csrf, 'resource-clarify'),
                json={
                    'content': 'Corrijo: compáralos usando el dato real y luego dime si la guía los incluye.',
                    'response_language': 'es',
                },
            )
        )
        assert len(provider.calls) == 1
        assert '40' in final['content'] and '50' in final['content']
        assert '¿A qué guía' in final['content']
        assert {r['id'] for r in final['resources']} == {
            'grafismo-fonetico/safari',
            'grafismo-fonetico/juega',
        }
        assert '10 Minutos' not in final['content']
