"""Report snapshot clocks: real output validation and HTTP, no sockets/PG/provider."""

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.application.product_analytics import AnalyticsService, Bucket
from app.domain.product_analytics import Event, Period, Selection, window
from app.presentation.product_analytics import ReportOut, build_router


def timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


class SnapshotRows:
    def __init__(self, rows: tuple[Bucket, ...] = ()) -> None:
        self.value = rows

    async def rows(self, start: datetime, end: datetime, selection: Selection) -> tuple[Bucket, ...]:
        return self.value

    async def ready(self) -> bool:
        return True

    async def ingest(self, event: Event, now: datetime) -> bool:
        raise AssertionError('report reads must not ingest')


class CommittedWhileAwaiting(SnapshotRows):
    def __init__(self, buckets: tuple[Bucket, ...]) -> None:
        super().__init__(buckets)
        self.windows: list[tuple[datetime, datetime, Selection]] = []

    async def rows(self, start: datetime, end: datetime, selection: Selection) -> tuple[Bucket, ...]:
        self.windows.append((start, end, selection))
        # The request clock was captured before this await; these committed rows can be newer.
        await asyncio.sleep(0)
        return self.value


@pytest.mark.parametrize(
    ('captured', 'received', 'period'),
    [
        ('2026-10-18T12:00:00', '2026-10-18T12:00:00.000001', 'day'),
        ('2026-10-18T23:59:59.999998', '2026-10-18T23:59:59.999999', 'day'),
        ('2026-10-18T23:59:59.999998', '2026-10-18T23:59:59.999999', 'week'),
        ('2026-10-31T23:59:59.999998', '2026-10-31T23:59:59.999999', 'month'),
        ('2026-12-31T23:59:59.999998', '2026-12-31T23:59:59.999999', 'month'),
        # A backward clock within the selected interval must not invalidate already received data.
        ('2026-10-18T11:58:00', '2026-10-18T12:00:00', 'day'),
    ],
)
def test_concurrent_receipt_watermark_preserves_selected_calendar_and_counts(
    captured: str, received: str, period: Period
) -> None:
    now, last = timestamp(captured), timestamp(received)
    selection = Selection(period=period)
    bucket = Bucket(
        last.replace(hour=0, minute=0, second=0, microsecond=0), 'page_view', -1, -1, 2, now, last
    )
    repo = CommittedWhileAwaiting((bucket,))
    value = asyncio.run(AnalyticsService(repo, synthetic=True).report(now, selection))
    report = ReportOut.model_validate(value)
    assert report.generated_at == last
    assert (report.start, report.end) == window(now, selection)
    assert repo.windows == [(*window(now, selection), selection)]
    assert report.partial
    assert report.first_observed_at == now and report.last_observed_at == last
    assert report.totals.page_views == 2 and report.countries[0].count == 2
    assert report.daily[0].page_views == 2


@pytest.mark.parametrize('period', ['day', 'week', 'month'])
def test_historical_window_and_empty_report_keep_request_clock(period: Period) -> None:
    now = timestamp('2026-11-01T00:00:00')
    selection = Selection(period=period, offset=1)
    start, end = window(now, selection)
    last = end - timedelta(microseconds=1)
    repo = SnapshotRows(
        (
            Bucket(
                last.replace(hour=0, minute=0, second=0, microsecond=0), 'section_view', -1, -1, 1, last, last
            ),
        )
    )
    report = ReportOut.model_validate(
        asyncio.run(AnalyticsService(repo, synthetic=True).report(now, selection))
    )
    assert report.generated_at == now and not report.partial
    assert (report.start, report.end) == (start, end)
    empty = ReportOut.model_validate(
        asyncio.run(AnalyticsService(SnapshotRows(), synthetic=True).report(now, selection))
    )
    assert empty.generated_at == now and empty.first_observed_at is None
    assert empty.totals.page_views == empty.totals.section_views == empty.totals.public_clicks == 0


@pytest.mark.parametrize('fault', ['at_end', 'before_start', 'inverted', 'wrong_day', 'negative'])
def test_invalid_snapshot_is_still_rejected(fault: str) -> None:
    now = timestamp('2026-10-18T23:59:59.999998')
    selection = Selection()
    start, end = window(now, selection)
    first = last = now
    day, count = start, 2
    if fault == 'at_end':
        last = end
    elif fault == 'before_start':
        first = start - timedelta(microseconds=1)
    elif fault == 'inverted':
        first = now + timedelta(microseconds=1)
    elif fault == 'wrong_day':
        day = start - timedelta(days=1)
    else:
        count = -1
    repo = SnapshotRows((Bucket(day, 'page_view', -1, -1, count, first, last),))
    with pytest.raises(ValidationError):
        ReportOut.model_validate(asyncio.run(AnalyticsService(repo, synthetic=True).report(now, selection)))


@dataclass(frozen=True)
class Clock:
    value: datetime

    def now(self) -> datetime:
        return self.value


@pytest.mark.parametrize('invalid', [False, True])
def test_private_http_concurrent_receipt_serves_valid_snapshot_but_rejects_outside_window(
    invalid: bool,
) -> None:
    now = timestamp('2026-10-18T12:00:00')
    last = window(now, Selection())[1] if invalid else now + timedelta(microseconds=1)
    repo = CommittedWhileAwaiting((Bucket(now.replace(hour=0), 'page_view', -1, -1, 2, now, last),))
    token = 'synthetic-clock-report-token'
    app = FastAPI()
    app.include_router(
        build_router(
            AnalyticsService(repo, synthetic=True),
            enabled=True,
            token_digest=hashlib.sha256(token.encode()).digest(),
            origins=('http://localhost:3108',),
            clock=Clock(now),
        )
    )
    with TestClient(app) as client:
        response = client.get(
            '/internal/v1/ops/product-analytics', headers={'Authorization': f'Bearer {token}'}
        )
    assert response.status_code == (503 if invalid else 200)
    if not invalid:
        report = ReportOut.model_validate(response.json())
        assert report.generated_at == last and report.totals.page_views == 2
