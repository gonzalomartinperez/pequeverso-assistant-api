"""Generate the pinned v1 contract artifacts from the code that serves them.

    uv run python -m contracts.export          # write contracts/
    uv run python -m contracts.export --check  # fail if contracts/ is stale (CI)

Examples are built deterministically through the real answer validation and wire models
(fixed ids and times, the committed catalog), so they cannot drift from behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from app.adapters.catalog_schema import CatalogParser
from app.application.answers import PAYMENT_REFUSAL_ANSWER, answer_rules, finalize, replacement
from app.application.ports import Draft, DraftReference
from app.bootstrap.config import DEFAULT_CATALOG, Settings
from app.bootstrap.container import create_app
from app.domain.catalog import ActiveCatalog, PriceStatus
from app.domain.conversation import AnswerDetails, Message, Notice, Role
from app.domain.errors import FailureCode
from app.presentation.events import (
    MessageCompletedEvent,
    MessageDeltaEvent,
    RunCancelledEvent,
    RunCompletedEvent,
    RunFailedEvent,
    RunStartedEvent,
    StreamEvent,
)
from app.presentation.middleware import error_payload
from app.presentation.schemas import AvailabilityOut, LimitsOut, MessageOut, SessionOut

ROOT = Path(__file__).resolve().parent
CONTRACT_VERSION = '1'
NOW = datetime(2026, 9, 28, 15, 0, tzinfo=UTC)
RUN = 'run_EXAMPLE0000001'


def _dump(data: Any) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + '\n').encode()


def _catalog() -> ActiveCatalog:
    catalog = CatalogParser(frozenset(Settings.model_fields['catalog_allowed_hosts'].default))(
        DEFAULT_CATALOG.read_bytes()
    )
    return ActiveCatalog(catalog, 'example', catalog.generated_at, timedelta(hours=168))


def _answer(active: ActiveCatalog, draft: Draft, status: PriceStatus = PriceStatus.VERIFIED) -> Message:
    final = finalize(draft, active, status, answer_rules(active.catalog, status, ()))
    return Message('msg_EXAMPLEassistant1', Role.ASSISTANT, final.content, NOW, final.details)


def _user(content: str, notices: tuple[Notice, ...] = ()) -> Message:
    return Message('msg_EXAMPLEuser00001', Role.USER, content, NOW, AnswerDetails(notices=notices))


def _sse(events: list[Any]) -> bytes:
    return ''.join(
        f'id: {e.sequence}\nevent: {e.type}\ndata: {e.model_dump_json()}\n\n' for e in events
    ).encode()


def _transcript(user: Message | None, answer: Message, chunks: int = 3) -> list[Any]:
    base = {'run_id': RUN, 'timestamp': NOW}
    events: list[Any] = [
        RunStartedEvent(**base, sequence=0, user_message=MessageOut.of(user) if user else None)
    ]
    size = max(1, len(answer.content) // chunks + 1)
    for start in range(0, len(answer.content), size):
        events.append(
            MessageDeltaEvent(**base, sequence=len(events), text=answer.content[start : start + size])
        )
    events.append(MessageCompletedEvent(**base, sequence=len(events), message=MessageOut.of(answer)))
    events.append(RunCompletedEvent(**base, sequence=len(events)))
    return events


def build() -> dict[str, bytes]:
    active = _catalog()
    recommendation = _answer(
        active,
        Draft(
            answer=(
                'Para una niña de 4 años que está empezando, **Grafismo Fonético** encaja bien: son hojas '
                'para imprimir con sílabas grandes, imágenes y trazo guiado, unos 10 minutos por día.\n'
                '- **Los Sonidos de Mi Casa**: palabras de objetos cotidianos, fáciles de reconocer.\n'
                '- **10 Minutos de Grafismo Fonético**: una guía breve para elegir la hoja de cada día.\n'
                'El kit cuesta US$14,99 en un único pago; Hotmart lo convierte a tu moneda local.'
            ),
            references=(
                DraftReference('product', 'grafismo-fonetico'),
                DraftReference('resource', 'grafismo-fonetico/sonidos-de-mi-casa'),
                DraftReference('resource', 'grafismo-fonetico/10-minutos'),
            ),
            sources=('faq.grafismo-fonetico.02', 'faq.grafismo-fonetico.05'),
            follow_ups=('¿Tengo que imprimir todo?', '¿Cómo funciona la garantía?'),
        ),
    )
    unknown = _answer(
        active,
        Draft(
            answer='No tengo información sobre envíos físicos: el kit es digital y el acceso llega por correo. '
            'Si necesitas algo más, escríbenos desde soporte.',
            references=(DraftReference('link', 'support'),),
            sources=('policy.delivery',),
            follow_ups=(),
        ),
    )
    replaced = _answer(active, Draft('Usa el cupón PEQUE50 y paga menos.', (), (), ()))
    stale = _answer(
        active,
        Draft(
            'El precio actual está en la página del kit y en el pago de Hotmart.',
            (DraftReference('product', 'grafismo-fonetico'),),
            (),
            (),
        ),
        PriceStatus.UNVERIFIED,
    )
    refusal = Message(
        'msg_EXAMPLEassistant1',
        Role.ASSISTANT,
        PAYMENT_REFUSAL_ANSWER,
        NOW,
        replacement(active.catalog, Notice.PAYMENT_DATA_REFUSED),
    )
    base = {'run_id': RUN, 'timestamp': NOW}
    session = SessionOut(
        csrf_token='csrf_EXAMPLE_keep_in_memory_only',  # noqa: S106 - documented placeholder
        expires_at=NOW + timedelta(hours=24),
        created=True,
        messages=[],
        availability=AvailabilityOut(status='available'),
        limits=LimitsOut(max_message_chars=600, messages_per_day=30),
    )

    app = create_app(Settings(_env_file=None, database_path=':memory:'))
    artifacts: dict[str, bytes] = {
        'openapi.json': _dump(app.openapi()),
        'sse.schema.json': _dump(TypeAdapter(StreamEvent).json_schema()),
        'examples/session.created.json': _dump(session.model_dump(mode='json')),
        'examples/stream.recommendation.sse': _sse(
            _transcript(
                _user('Mi hija tiene 4 años y recién empieza con las letras, ¿qué me recomiendas?'),
                recommendation,
            )
        ),
        'examples/stream.unknown-policy.sse': _sse(
            _transcript(_user('¿Cuánto tarda el envío a Chile?'), unknown)
        ),
        'examples/stream.answer-replaced.sse': _sse(_transcript(_user('¿Tienen algún cupón?'), replaced)),
        'examples/stream.price-unverified.sse': _sse(_transcript(_user('¿Cuánto cuesta?'), stale)),
        'examples/stream.payment-data-refused.sse': _sse(
            _transcript(
                _user('[mensaje eliminado: contenía datos de pago]', (Notice.PAYMENT_DATA_REFUSED,)),
                refusal,
                1,
            )
        ),
        'examples/stream.failed.sse': _sse(
            [
                RunStartedEvent(**base, sequence=0, user_message=MessageOut.of(_user('Hola'))),
                MessageDeltaEvent(**base, sequence=1, text='Hola, te '),
                RunFailedEvent(**base, sequence=2, code='provider_unavailable', retryable=True),
            ]
        ),
        'examples/stream.cancelled.sse': _sse(
            [
                RunStartedEvent(**base, sequence=0, user_message=MessageOut.of(_user('Hola'))),
                RunCancelledEvent(**base, sequence=1),
            ]
        ),
        'examples/errors.json': _dump(
            {code.value: error_payload(code, 'req_EXAMPLE') for code in FailureCode}
        ),
    }
    manifest = {
        'contract_version': CONTRACT_VERSION,
        'schema_version': '1',
        'artifacts': {name: hashlib.sha256(data).hexdigest() for name, data in sorted(artifacts.items())},
    }
    artifacts['manifest.json'] = _dump(manifest)
    return artifacts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    stale: list[str] = []
    for name, data in build().items():
        path = ROOT / name
        if args.check:
            if not path.exists() or path.read_bytes() != data:
                stale.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    if stale:
        print('stale contract artifacts (run: uv run python -m contracts.export):', ', '.join(stale))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
