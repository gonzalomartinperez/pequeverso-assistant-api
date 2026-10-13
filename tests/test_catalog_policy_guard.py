"""The merchant guarantee boundary survives disabled or unavailable public evidence."""

import json

import pytest

from app.application.answers import REPLACEMENT_ANSWER
from app.domain.web_evidence import SOURCES, HelpTopic, WebEvidence
from tests.support import (
    CATALOG_BYTES,
    JSON_HEADERS,
    ScriptedProvider,
    answer_json,
    ask,
    client,
    open_session,
)


@pytest.mark.parametrize('mode', ['off', 'unavailable', 'selected'])
@pytest.mark.parametrize(
    'answer',
    [
        'Tienes una garantía de 30 días para el kit. Puedes comprarlo.',
        'No olvides la garantía de 30 días. Puedes comprarlo.',
        'Do not forget the 30-day guarantee. You can buy it.',
        'Tu reembolso será aprobado. Está garantizado.',
    ],
)
def test_false_guarantee_and_refund_claims_never_reach_stream_final_or_history(tmp_path, mode, answer):
    provider = ScriptedProvider(answer_json(answer), chunk=1)
    with client(tmp_path, provider) as http:
        _reader(http, mode)
        csrf = open_session(http)
        status, events, _ = ask(http, csrf, '¿Cómo funciona la garantía?', 'policy-mode-001')
        assert status == 200
        assert not any(e['type'] == 'message.delta' for e in events)
        final = events[-2]['message']
        assert final['content'] == REPLACEMENT_ANSWER and final['notices'] == ['answer_replaced']
        assert http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages'][-1] == final
        assert len(provider.calls) == 1
        assert any(i.text.startswith('official_platform_data:') for i in provider.calls[0].inputs) == (
            mode == 'selected'
        )


@pytest.mark.parametrize('mode', ['off', 'unavailable', 'selected'])
@pytest.mark.parametrize(
    'answer',
    [
        'Tienes una garantía de 7 días para el kit. El reembolso se solicita por Hotmart.',
        'No tenemos una garantía de 30 días. La garantía publicada es de 7 días.',
        'A refund is not guaranteed. Check the published conditions.',
        'Hotmart gestiona el pago y el acceso digital. Puedes consultar su procedimiento público.',
    ],
)
def test_published_window_honest_denials_and_general_procedures_remain_allowed(tmp_path, mode, answer):
    provider = ScriptedProvider(answer_json(answer), chunk=1)
    with client(tmp_path, provider) as http:
        _reader(http, mode)
        _, events, _ = ask(http, open_session(http), '¿Cómo funciona la garantía?')
        assert events[-2]['message']['content'] == answer
        assert events[-2]['message']['notices'] == []
        assert ''.join(e['text'] for e in events if e['type'] == 'message.delta') == answer
        assert len(provider.calls) == 1


def _reader(http, mode):
    if mode == 'off':
        assert http.app.state.services.chat.official_help is None
        return
    from datetime import datetime

    catalog = json.loads(CATALOG_BYTES)
    source = next(s for s in SOURCES if s.topic is HelpTopic.REFUND)
    item = WebEvidence(
        source,
        'Synthetic general buyer procedure, not merchant guarantee.',
        'a' * 64,
        datetime.fromisoformat(catalog['generated_at']),
    )

    class Reader:
        async def read(self, topics):
            return (item,) if mode == 'selected' else ()

    http.app.state.services.chat.official_help = Reader()
