"""Catalog page counts are checked before provisional and authoritative presentation."""

import pytest

from app.application.answers import REPLACEMENT_ANSWER
from tests.support import JSON_HEADERS, ScriptedProvider, answer_json, ask, client, open_session


@pytest.mark.parametrize(
    'answer',
    [
        'Safari tiene 40 páginas. Juega incluye juegos. Ambos tienen 40 páginas cada uno.',
        'Safari and Juega are included bonuses. Both have 40 pages each.',
        'Juega con Sonidos y Sílabas tiene 40 páginas.',
        'Safari tiene 50 páginas.',
        'Safari y Juega suman 80 páginas en total.',
    ],
)
def test_false_explicit_page_counts_never_reach_sse_final_or_history(tmp_path, answer):
    provider = ScriptedProvider(answer_json(answer), chunk=1)
    with client(tmp_path, provider) as http:
        csrf = open_session(http)
        _, events, _ = ask(http, csrf, '¿Qué diferencias hay entre los bonos?', 'pages-bad-001')
        final = events[-2]['message']
        assert final['content'] == REPLACEMENT_ANSWER
        assert final['notices'] == ['answer_replaced']
        streamed = ''.join(e['text'] for e in events if e['type'] == 'message.delta')
        assert '40 páginas cada uno' not in streamed and '40 pages each' not in streamed
        assert 'Juega con Sonidos y Sílabas tiene 40 páginas' not in streamed
        assert 'Safari tiene 50 páginas' not in streamed
        assert '80 páginas' not in streamed
        assert http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages'][-1] == final
        _, replay, _ = ask(http, csrf, '¿Qué diferencias hay entre los bonos?', 'pages-bad-001')
        assert replay[-2]['message'] == final
        assert len(provider.calls) == 1


@pytest.mark.parametrize(
    'answer',
    [
        'Safari tiene 40 páginas y Juega tiene 50 páginas.',
        'Safari tiene 40 páginas, Juega tiene 50 páginas y el kit tiene 414 páginas en total.',
        'Juega tiene 50 páginas. Puedes imprimir 10 páginas para comenzar.',
        'Juega tiene 50 páginas. Safari tiene 40 páginas.',
        'Safari y Juega suman 90 páginas en total.',
        'Safari y Mi Pared de Sonidos tienen 40 páginas cada uno.',
        'Safari tiene 40 páginas. Juega tiene 50 páginas. El kit tiene 414 páginas en total.',
        'Puedes imprimir 10 páginas de Safari para comenzar.',
        'Choose 10 pages from Juega to print.',
        'Safari tiene 40 páginas; puedes elegir 5 páginas para la práctica.',
        'Los bonos son PDF imprimibles. No necesitas imprimir todas las páginas.',
        'El kit ofrece 10 minutos de práctica diaria y tiene 414 páginas.',
    ],
)
def test_published_individual_shared_total_and_print_subset_counts_remain_allowed(tmp_path, answer):
    provider = ScriptedProvider(answer_json(answer), chunk=1)
    with client(tmp_path, provider) as http:
        _, events, _ = ask(http, open_session(http), '¿Cómo usar los materiales?')
        final = events[-2]['message']
        assert final['content'] == answer and not final['notices']
        assert ''.join(e['text'] for e in events if e['type'] == 'message.delta') == answer
        assert len(provider.calls) == 1
