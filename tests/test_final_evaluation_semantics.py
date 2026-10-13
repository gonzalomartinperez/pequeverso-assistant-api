"""Two finite regressions from the preserved post-tool development evaluation."""

import pytest

from app.application.answers import REPLACEMENT_ANSWER
from app.domain.language import Language, reply_language, spanish_native_language
from tests.support import (
    ScriptedProvider,
    answer_json,
    ask,
    client,
    mutation_headers,
    open_session,
    parse_sse,
)


@pytest.mark.parametrize('question', ["Réponds en français, s'il te plaît.", 'Répondez en français.'])
def test_explicit_french_reply_request_is_local_without_provider(tmp_path, question):
    assert spanish_native_language(question) is None
    assert reply_language(question, [], None) is None
    provider = ScriptedProvider()
    with client(tmp_path, provider) as http:
        response = http.post(
            '/api/v1/messages',
            headers=mutation_headers(open_session(http)),
            json={'content': question, 'response_language': 'es', 'locale': 'es'},
        )
        assert response.status_code == 200
        events = parse_sse(response.text)
        assert events[-2]['message']['notices'] == ['language_unsupported']
        assert not provider.calls


@pytest.mark.parametrize(
    'question',
    [
        '¿Qué significa "Réponds en français"?',
        '¿Qué significa `Répondez en français`?',
    ],
)
def test_quoted_french_commands_do_not_change_native_reply_policy(question):
    assert spanish_native_language(question) is Language.ES
    assert reply_language(question, [], None) is Language.ES


@pytest.mark.parametrize(
    'answer',
    [
        'La solicitud no se procesa de inmediato: el productor puede tardar hasta 5 días.',
        'El reembolso no se procesa inmediatamente.',
        'The refund request is not processed immediately.',
    ],
)
def test_maximum_window_cannot_become_categorical_minimum_delay(tmp_path, answer):
    provider = ScriptedProvider(answer_json(answer), chunk=1)
    with client(tmp_path, provider) as http:
        _, events, _ = ask(http, open_session(http), '¿Cómo solicito un reembolso?')
        assert not any(e['type'] == 'message.delta' for e in events)
        assert events[-2]['message']['content'] == REPLACEMENT_ANSWER
        assert events[-2]['message']['notices'] == ['answer_replaced']
        assert len(provider.calls) == 1


@pytest.mark.parametrize(
    'answer',
    [
        'El productor puede tardar hasta 5 días en responder. La aprobación puede tardar hasta 7 días.',
        'No puedo procesar tu reembolso. Puedes solicitarlo directamente en Hotmart.',
        'Si la solicitud no se procesa de inmediato, consulta con Hotmart.',
        'I cannot process your refund immediately. You can submit a request through Hotmart.',
    ],
)
def test_upper_bounds_and_assistant_capability_refusals_remain_valid(tmp_path, answer):
    provider = ScriptedProvider(answer_json(answer), chunk=1)
    with client(tmp_path, provider) as http:
        _, events, _ = ask(http, open_session(http), '¿Cómo solicito un reembolso?')
        assert events[-2]['message']['content'] == answer
        assert not events[-2]['message']['notices']
