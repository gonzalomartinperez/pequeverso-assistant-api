"""Provider citation syntax never replaces the structured, validated source contract."""

import hashlib

import pytest

from app.application.answers import REPLACEMENT_ANSWER
from app.domain.web_evidence import SOURCES, WebEvidence
from tests.support import (
    CATALOG_BYTES,
    JSON_HEADERS,
    ScriptedProvider,
    answer_json,
    ask,
    client,
    open_session,
)

MARKER = '\ue200cite\ue202policy.guarantee\ue202hotmart:360061973392\ue201'


@pytest.mark.parametrize(
    ('answer', 'expected'),
    [
        (
            f'{MARKER} Consulta el procedimiento general publicado.',
            'Consulta el procedimiento general publicado.',
        ),
        (
            f'Puedes solicitar el reembolso por Hotmart. {MARKER}',
            'Puedes solicitar el reembolso por Hotmart.',
        ),
        (
            f'Consulta {MARKER} el procedimiento general publicado.',
            'Consulta el procedimiento general publicado.',
        ),
    ],
)
def test_complete_provider_marker_is_removed_but_effective_structured_sources_survive(
    tmp_path, answer, expected
):
    import json
    from datetime import datetime

    provider = ScriptedProvider(
        answer_json(answer, sources=['policy.guarantee', 'hotmart:360061973392']), chunk=1
    )
    text = 'Synthetic general request procedure, not eligibility or merchant policy.'
    item = WebEvidence(
        SOURCES[1],
        text,
        hashlib.sha256(text.encode()).hexdigest(),
        datetime.fromisoformat(json.loads(CATALOG_BYTES)['generated_at']),
    )

    class Reader:
        async def read(self, topics):
            return (item,)

    with client(tmp_path, provider) as http:
        http.app.state.services.chat.official_help = Reader()
        csrf = open_session(http)
        _, events, _ = ask(http, csrf, '¿Cómo solicitar un reembolso?', 'citation-marker-001')
        assert all(
            not any(char in event.get('text', '') for char in ('\ue200', '\ue201', '\ue202'))
            for event in events
        )
        final = events[-2]['message']
        assert final['content'] == expected and not final['notices']
        assert [source['id'] for source in final['sources']] == ['policy.guarantee', 'hotmart:360061973392']
        assert http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages'][-1] == final
        _, replay, _ = ask(http, csrf, '¿Cómo solicitar un reembolso?', 'citation-marker-001')
        assert replay[-2]['message'] == final and len(provider.calls) == 1


@pytest.mark.parametrize(
    'marker', ['\ue200cite\ue202policy.guarantee', '\ue200cite\ue202' + 'x' * 300 + '\ue201']
)
def test_incomplete_or_oversized_marker_is_safe_terminal_replacement(tmp_path, marker):
    provider = ScriptedProvider(answer_json(f'Consulta la información publicada {marker}.'), chunk=1)
    with client(tmp_path, provider) as http:
        _, events, _ = ask(http, open_session(http), '¿Cómo solicitar un reembolso?')
        assert not any(event['type'] == 'message.delta' for event in events)
        assert events[-2]['message']['content'] == REPLACEMENT_ANSWER
        assert events[-2]['message']['notices'] == ['answer_replaced']


@pytest.mark.parametrize(
    'hidden', ['https://evil.example/secret', 'US$999', 'La garantía es de 30 días', 'Juega tiene 40 páginas']
)
def test_marker_cleanup_never_hides_a_raw_destination_or_price_violation(tmp_path, hidden):
    provider = ScriptedProvider(
        answer_json(f'Información publicada. \ue200cite\ue202{hidden}\ue201'), chunk=1
    )
    with client(tmp_path, provider) as http:
        _, events, _ = ask(http, open_session(http), '¿Qué incluye el kit?')
        assert events[-2]['message']['content'] == REPLACEMENT_ANSWER
        assert events[-2]['message']['notices'] == ['answer_replaced']
        assert all(
            not any(char in event.get('text', '') for char in ('\ue200', '\ue201', '\ue202'))
            for event in events
        )
