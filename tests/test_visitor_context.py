"""Additive navigation hints: strict input, unchanged grounding, privacy and idempotency."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from app.application.chat import _request_hash
from app.domain.visitor_context import VisitorContext
from tests.support import ScriptedProvider, answer_json, client, mutation_headers, open_session, parse_sse

CONTEXT = {'opened_path': '/grafismo-fonetico/', 'current_path': '/soporte/', 'presentation': 'expanded'}


def _post(c: object, csrf: str, context: object = None, key: str = 'context-0001') -> object:
    return c.post(
        '/api/v1/messages',
        headers=mutation_headers(csrf, key),
        json={'content': '¿Qué incluye el kit?', 'page': 'product', 'context': context},
    )


def test_context_is_data_only_and_not_stored_or_logged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    provider = ScriptedProvider(answer_json('El kit tiene9PDF.'))
    with client(tmp_path, provider=provider) as c:
        csrf = open_session(c)
        result = _post(c, csrf, CONTEXT)
        assert result.status_code == 200
        events = parse_sse(result.text)
        assert events[-1]['type'] == 'run.completed'
        payload = provider.calls[0]
        visitor = json.loads(payload.inputs[1].text.removeprefix('visitor_turn:\n'))
        assert visitor['visitor_context'] == CONTEXT
        assert '/soporte/' not in payload.instructions
        assert 'visitor_context' not in payload.inputs[0].text
    with closing(sqlite3.connect(tmp_path / 'test.sqlite3')) as db:
        rows = db.execute('SELECT content FROM messages').fetchall()
        assert not any('/soporte/' in row[0] or 'visitor_context' in row[0] for row in rows)
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        assert not any('context' in name for name in tables)
    logged = capsys.readouterr().out
    assert '/soporte/' not in logged and '/grafismo-fonetico/' not in logged


@pytest.mark.parametrize(
    'path',
    [
        '/imprime-y-juega/',
        '/grafismo-fonetico/gracias/',
        '/oferta/',
        '//soporte/',
        'https://pequeverso.com/soporte/',
        '/soporte/?email=visitor@example.com',
        '/soporte/#private',
        '/%73oporte/',
        '/%2573oporte/',
        '/soporte/../privacidad/',
        '/soporte\\',
        '/soporte/\n',
        '/support/',
        '/en/soporte/',
        '<script>alert(1)</script>',
        '/unknown/',
        '',
    ],
)
def test_restricted_encoded_or_identifying_paths_never_reach_model(tmp_path: Path, path: str) -> None:
    provider = ScriptedProvider(answer_json('Respuesta.'))
    with client(tmp_path, provider=provider) as c:
        result = _post(c, open_session(c), {'current_path': path})
        assert result.status_code == 422
        assert result.json()['error']['code'] == 'invalid_request'
    assert provider.calls == []


@pytest.mark.parametrize(
    'bad_context',
    [
        {'theme': 'dark'},
        {'presentation': 'dark'},
        {'presentation': 'iframe'},
        {'opened_path': '/soporte/', 'referrer': 'private'},
        {'html': '<b>hi</b>'},
        {'current_path': 42},
        {'presentation': True},
        'expanded',
        [],
    ],
)
def test_unknown_context_keys_and_types_fail_closed(tmp_path: Path, bad_context: object) -> None:
    provider = ScriptedProvider(answer_json('Respuesta.'))
    with client(tmp_path, provider=provider) as c:
        result = _post(c, open_session(c), bad_context)
        assert result.status_code == 422
    assert provider.calls == []


def test_context_idempotency_and_alias_normalization(tmp_path: Path) -> None:
    provider = ScriptedProvider(answer_json('Respuesta.'))
    with client(tmp_path, provider=provider) as c:
        csrf = open_session(c)
        first = _post(c, csrf, CONTEXT)
        assert first.status_code == 200
        alias = dict(CONTEXT, opened_path='/grafismo-fonetico', current_path='/soporte')
        replay = _post(c, csrf, alias)
        assert replay.status_code == 200
        assert parse_sse(first.text)[-2]['message']['id'] == parse_sse(replay.text)[-2]['message']['id']
        changed = _post(c, csrf, dict(CONTEXT, current_path='/privacidad/'))
        assert changed.status_code == 409 and changed.json()['error']['code'] == 'idempotency_conflict'
    assert len(provider.calls) == 1


def test_absent_and_empty_context_preserve_exact_legacy_hash_and_payload(tmp_path: Path) -> None:
    question = '¿Qué incluye el kit?'
    legacy = hashlib.sha256(json.dumps([question, 'product']).encode()).hexdigest()
    assert _request_hash(question, 'product') == legacy
    assert _request_hash(question, 'product', VisitorContext()) == legacy
    provider = ScriptedProvider(answer_json('Respuesta.'))
    with client(tmp_path, provider=provider) as c:
        csrf = open_session(c)
        first = _post(c, csrf, None)
        assert first.status_code == 200
        assert _post(c, csrf, {}).status_code == 200
        assert (
            _post(c, csrf, {'opened_path': None, 'current_path': None, 'presentation': None}).status_code
            == 200
        )
    assert len(provider.calls) == 1
    assert 'visitor_context' not in provider.calls[0].inputs[1].text


def test_flat_context_fields_are_not_accepted(tmp_path: Path) -> None:
    with client(tmp_path) as c:
        csrf = open_session(c)
        response = c.post(
            '/api/v1/messages',
            headers=mutation_headers(csrf),
            json={'content': 'Hola', 'opened_path': '/soporte/'},
        )
        assert response.status_code == 422
