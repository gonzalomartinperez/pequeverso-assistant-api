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
from app.application.answers import (
    PAYMENT_REFUSAL_ANSWER,
    UNSUPPORTED_LANGUAGE_ANSWER,
    answer_rules,
    finalize,
    replacement,
)
from app.application.operations import RecentRun, ServiceInfo, Summary
from app.application.ports import Draft, DraftReference
from app.bootstrap.config import DEFAULT_CATALOG, Settings
from app.bootstrap.container import create_app
from app.domain.catalog import ActiveCatalog, PriceStatus
from app.domain.conversation import AnswerDetails, Message, Notice, Role
from app.domain.errors import FailureCode
from app.domain.language import Language
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
from app.presentation.operations import OpsSummaryOut
from app.presentation.schemas import CONTRACT_REVISION, AvailabilityOut, LimitsOut, MessageOut, SessionOut

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


def _answer(
    active: ActiveCatalog,
    draft: Draft,
    status: PriceStatus = PriceStatus.VERIFIED,
    language: Language = Language.ES,
) -> Message:
    final = finalize(draft, active, status, answer_rules(active.catalog, status, ()), language)
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
    english = _answer(
        active,
        Draft(
            answer=(
                '**Grafismo Fonético** is a printable kit (the material is in Spanish) for ages 3 to 7. '
                'It includes the main guide plus bonus PDFs, such as **Los Sonidos de Mi Casa**, with '
                'large syllables, pictures and guided tracing for about 10 minutes a day.'
            ),
            references=(
                DraftReference('product', 'grafismo-fonetico'),
                DraftReference('resource', 'grafismo-fonetico/sonidos-de-mi-casa'),
            ),
            sources=('faq.grafismo-fonetico.05',),
            follow_ups=('Do I need to print everything?',),
        ),
        language=Language.EN,
    )
    unsupported = Message(
        'msg_EXAMPLEassistant1',
        Role.ASSISTANT,
        UNSUPPORTED_LANGUAGE_ANSWER,
        NOW,
        AnswerDetails(notices=(Notice.LANGUAGE_UNSUPPORTED,)),
    )
    base = {'run_id': RUN, 'timestamp': NOW}
    session = SessionOut(
        csrf_token='csrf_EXAMPLE_keep_in_memory_only',  # noqa: S106 - documented placeholder
        expires_at=NOW + timedelta(hours=24),
        created=True,
        messages=[],
        availability=AvailabilityOut(status='available'),
        limits=LimitsOut(max_message_chars=600, messages_per_day=30),
        starters=[
            '¿Qué incluye exactamente la compra?',
            '¿Para qué edades se recomienda?',
            '¿Tengo que imprimir todo el material?',
            '¿Cómo funciona la garantía de 7 días?',
        ],
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
        'examples/stream.english.sse': _sse(_transcript(_user('What does the kit include?'), english)),
        'examples/stream.language-unsupported.sse': _sse(
            _transcript(_user('Quanto custa o kit?'), unsupported)
        ),
        'ops.schema.json': _dump(OpsSummaryOut.model_json_schema()),
        'examples/ops.summary.json': _dump(_ops_example().model_dump(mode='json')),
        'examples/errors.json': _dump(
            {code.value: error_payload(code, 'req_EXAMPLE') for code in FailureCode}
        ),
    }
    manifest = {
        'contract_version': CONTRACT_VERSION,
        'contract_revision': CONTRACT_REVISION,
        'schema_version': '1',
        'artifacts': {name: hashlib.sha256(data).hexdigest() for name, data in sorted(artifacts.items())},
    }
    artifacts['manifest.json'] = _dump(manifest)
    return artifacts


def _ops_example() -> OpsSummaryOut:
    """A fixture-mode reading: `synthetic` is true, so every number is simulated."""
    spend = {'confirmed': '0.004200', 'estimated': '0.005400', 'pending': '0.000000'}
    window = {
        'runs': {'completed': 7, 'failed': 1, 'cancelled': 1, 'interrupted': 0, 'refused': 1},
        'replaced': 1,
        'failures': {'budget_exhausted': 1, 'provider_unavailable': 1},
        'latency_ms': {
            'first_delta': {'p50': 820, 'p95': 1900, 'count': 8},
            'total': {'p50': 3100, 'p95': 6400, 'count': 7},
        },
        'tokens': {
            'input': 41000,
            'cached_input': 30000,
            'output': 9100,
            'reasoning': 5200,
            'runs_with_usage': 7,
        },
    }
    day = {'completed': 7, 'failed': 1, 'cancelled': 1, 'interrupted': 0, 'refused': 1}
    return OpsSummaryOut.of(
        Summary(
            generated_at=NOW,
            service=ServiceInfo(
                'development',
                'abcdef1',
                'fixture',
                'fixture',
                'n/a',
                True,
                NOW,
                168,
                {
                    'revision': 'openai-gpt-6-luna-2026-10-05',
                    'model': 'gpt-6-luna',
                    'input_per_million': '0.10',
                    'cached_input_per_million': '0.01',
                    'cache_write_per_million': '0.125',
                    'output_per_million': '0.50',
                },
            ),
            availability=None,
            catalog={
                'status': 'active',
                'source': 'bundled',
                'revision': 'ae6d237877c248551be988af9be920eac69b16da',
                'sha256': '0' * 64,
                'generated_at': NOW,
                'verified_at': NOW,
                'activated_at': NOW,
                'price_status': 'verified',
                'price_max_age_hours': 168,
                'last_attempt_at': NOW,
                'last_failure': None,
                'last_failure_at': None,
                'products': 1,
                'documents': 23,
            },
            budget={
                'month': '2026-09',
                'day': '2026-09-28',
                'monthly_limit': '10.000000',
                'monthly_cutoff': '9.000000',
                'daily_limit': '1.000000',
                'month_spend': spend,
                'day_spend': spend,
                'remaining_month': '8.990400',
            },
            windows=[{'hours': 24, **window}, {'hours': 720, **window}],
            daily=[
                {
                    'day': '2026-09-27',
                    **day,
                    'confirmed': '0.002100',
                    'estimated': '0.000000',
                    'input_tokens': 20000,
                    'output_tokens': 4000,
                    'reasoning_tokens': 2500,
                },
                {
                    'day': '2026-09-28',
                    **day,
                    'confirmed': '0.002100',
                    'estimated': '0.005400',
                    'input_tokens': 21000,
                    'output_tokens': 5100,
                    'reasoning_tokens': 2700,
                },
            ],
            metrics_since=NOW - timedelta(days=1),
            recent=[
                RecentRun('3f9a1c2b7d4e8f01', NOW, 'completed', None, True, False, 'es', 780, 2900),
                RecentRun(
                    'a1b2c3d4e5f60718',
                    NOW - timedelta(minutes=5),
                    'refused',
                    'budget_exhausted',
                    False,
                    False,
                    'es',
                    None,
                    0,
                ),
            ],
        )
    )


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
