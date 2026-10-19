"""Profile/calendar/report behavior using content-free fixture buckets; never model calls."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.application.product_analytics import AnalyticsService, Bucket
from app.bootstrap.config import Settings
from app.domain.product_analytics import Selection, window
from app.presentation.product_analytics import EventIn, ReportOut
from contracts.product_analytics import artifacts

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)


def event(**changes: object) -> dict[str, object]:
    return {
        'schema_version': 1,
        'project': 'pequeverso',
        'source': 'site',
        'event_id': str(uuid4()),
        'event_name': 'public_click',
        'route': '/',
        'layout_revision': 'pequeverso-v1',
        'section_id': 'hero',
        'viewport_bucket': 'mobile',
        'locale': 'es',
        'cell_x': 0,
        'cell_y': 7,
        **changes,
    }


@pytest.mark.parametrize(
    'changes',
    [
        {'route': '/auth'},
        {'locale': 'en'},
        {'section_id': 'incluye'},
        {'country': 'ES'},
        {'session_id': 'synthetic'},
        {'text': 'synthetic'},
        {'fixture': True},
        {'cell_x': True},
        {'cell_y': 8},
        {'cell_x': None},
        {'project': 'portfolio'},
        {'schema_version': True},
        {'event_name': 'checkout_intent'},
        {'event_id': str(uuid4()).replace('-', '')[:-1]},
    ],
)
def test_closed_profile_rejects_outside_owned_vocabulary(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        EventIn.model_validate(event(**changes))


def test_coordinates_are_pointer_only_and_uuid_is_hashed() -> None:
    value = EventIn.model_validate(event())
    assert value.event().digest != str(value.event_id)
    assert len(value.event().digest) == 64
    with pytest.raises(ValidationError):
        EventIn.model_validate(event(event_name='section_view', cell_x=None, cell_y=None))
    plain = event(event_name='section_view')
    plain.pop('cell_x')
    plain.pop('cell_y')
    assert EventIn.model_validate(plain).event().cell_x is None


@pytest.mark.parametrize(
    ('now', 'period', 'offset', 'start', 'end'),
    [
        ('2024-03-01', 'month', 1, '2024-02-01', '2024-03-01'),
        ('2026-01-01', 'week', 0, '2025-12-29', '2026-01-05'),
        ('2026-01-01', 'month', 2, '2025-11-01', '2025-12-01'),
        ('2026-01-01', 'day', 2, '2025-12-30', '2025-12-31'),
    ],
)
def test_calendar_boundaries(now: str, period: str, offset: int, start: str, end: str) -> None:
    selection = Selection(period=period, offset=offset)  # type: ignore[arg-type]
    actual = window(datetime.fromisoformat(now).replace(tzinfo=UTC), selection)
    assert tuple(value.date().isoformat() for value in actual) == (start, end)


@pytest.mark.parametrize(
    'changes',
    [
        {'period': 'year'},
        {'offset': 3},
        {'offset': True},
        {'route': '/grafismo-fonetico/', 'section_id': 'leer'},
        {'locale': 'en'},
    ],
)
def test_selection_is_closed(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError, match=r'invalid|unknown'):
        Selection(**changes)  # type: ignore[arg-type]


class Rows:
    def __init__(self, rows: tuple[Bucket, ...] = ()) -> None:
        self.value = rows
        self.selections: list[Selection] = []

    async def ingest(self, *args: object) -> bool:
        return True

    async def rows(self, start: datetime, end: datetime, selection: Selection) -> tuple[Bucket, ...]:
        self.selections.append(selection)
        return self.value

    async def ready(self) -> bool:
        return True


async def _small_cells_withheld_grid_selection_and_received_counts() -> None:
    day = NOW.replace(hour=0)
    rows = Rows(
        (
            Bucket(day, 'page_view', -1, -1, 2, NOW, NOW),
            Bucket(day, 'public_click', 0, 7, 3, NOW, NOW),
            Bucket(day, 'public_click', 1, 1, 2, NOW, NOW),
        )
    )
    service = AnalyticsService(rows, synthetic=True)
    selected = ReportOut.model_validate(await service.report(NOW, Selection(route='/', section_id='hero')))
    assert selected.totals.public_clicks == 5
    assert selected.grid.visible_clicks == 3 and selected.grid.withheld_clicks == 2
    assert [(cell.x, cell.y) for cell in selected.grid.cells] == [(0, 7)]
    assert selected.countries[0].count == 7 and selected.countries[0].code == 'unknown'
    all_regions = ReportOut.model_validate(await service.report(NOW, Selection()))
    assert all_regions.grid.unselected_clicks == 5 and all_regions.grid.cells == []
    assert rows.selections[-1] == Selection()


async def _empty_does_not_fabricate_coverage_and_small_country_not_iso() -> None:
    empty = ReportOut.model_validate(await AnalyticsService(Rows(), synthetic=True).report(NOW, Selection()))
    assert empty.first_observed_at is None and empty.countries == [] and empty.daily == []
    one = Rows((Bucket(NOW.replace(hour=0), 'section_view', -1, -1, 1, NOW, NOW),))
    small = ReportOut.model_validate(await AnalyticsService(one, synthetic=True).report(NOW, Selection()))
    assert small.countries[0].code == 'withheld'


@pytest.mark.parametrize(
    'change',
    [
        {'totals': {'page_views': 999, 'section_views': 3, 'public_clicks': 4}},
        {'synthetic': 'false'},
        {'country_collection': 'unverified'},
        {'end': NOW},
        {'generated_at': NOW.replace(tzinfo=None)},
        {'first_observed_at': NOW - timedelta(days=2)},
    ],
)
def test_report_rejects_inconsistent_or_nonfixture_data(change: dict[str, object]) -> None:
    import json

    value = json.loads(artifacts()['examples/product-analytics.json'])['report']
    with pytest.raises(ValidationError):
        ReportOut.model_validate({**value, **change})


def test_feature_off_and_country_activation_refused() -> None:
    settings = Settings(_env_file=None)
    assert not settings.product_analytics_enabled and not settings.product_analytics_country_enabled
    with pytest.raises(ValidationError):
        Settings(_env_file=None, product_analytics_country_enabled=True)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, product_analytics_enabled=True)


def test_small_cells_and_uniform_selection() -> None:
    asyncio.run(_small_cells_withheld_grid_selection_and_received_counts())


def test_empty_and_country_suppression() -> None:
    asyncio.run(_empty_does_not_fabricate_coverage_and_small_country_not_iso())


@pytest.mark.parametrize(
    'dsn',
    [
        'postgresql://synthetic:synthetic@production.invalid:55439/pv_knowledge_test',
        'postgresql://synthetic:synthetic@127.0.0.1:5432/pv_knowledge_test',
        'postgresql://synthetic:synthetic@127.0.0.1:55439/actual_database',
        'postgresql://synthetic:synthetic@127.0.0.1:55439/pv_knowledge_test?host=remote.invalid',
        'host=127.0.0.1 hostaddr=192.0.2.4 port=55439 dbname=pv_knowledge_test user=synthetic',
        'host=127.0.0.1 port=55439 dbname=pv_knowledge_test service=ambient user=synthetic',
        'host=127.0.0.1 port=55439 dbname=pv_knowledge_test options=unsafe user=synthetic',
    ],
)
def test_pg_fixture_rejects_foreign_or_overridden_target_before_connection(dsn: str) -> None:
    from tests.test_postgres_product_analytics import isolated_target

    with pytest.raises(ValueError, match='exact isolated'):
        isolated_target(dsn)


def test_pg_fixture_accepts_only_explicit_isolated_target() -> None:
    from tests.test_postgres_product_analytics import isolated_target

    info = isolated_target('postgresql://synthetic:synthetic@127.0.0.1:55439/pv_knowledge_test')
    assert info['host'] == '127.0.0.1' and info['dbname'] == 'pv_knowledge_test'


@pytest.mark.parametrize('dsn', ['not-a-dsn', 'postgresql://[broken'])
def test_pg_fixture_malformed_dsn_is_rejected_without_echo(dsn: str) -> None:
    from tests.test_postgres_product_analytics import isolated_target

    with pytest.raises(ValueError, match='invalid isolated') as error:
        isolated_target(dsn)
    assert dsn not in str(error.value)
