"""Bounded received-event aggregation; independent of visitor history and accounting."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from app.domain.product_analytics import Event, Selection, window


class QuotaExceededError(Exception):
    """The global accepted-event allowance is exhausted, without identifying a visitor."""


@dataclass(frozen=True, slots=True)
class Bucket:
    day: datetime
    name: str
    x: int
    y: int
    count: int
    first: datetime
    last: datetime


class AnalyticsRepository(Protocol):
    async def ingest(self, event: Event, now: datetime) -> bool: ...
    async def rows(self, start: datetime, end: datetime, selection: Selection) -> tuple[Bucket, ...]: ...
    async def ready(self) -> bool: ...


class AnalyticsService:
    def __init__(self, repository: AnalyticsRepository, *, synthetic: bool) -> None:
        self.repository = repository
        self.synthetic = synthetic

    async def ingest(self, event: Event, now: datetime) -> bool:
        return await self.repository.ingest(event, now)

    async def report(self, now: datetime, selection: Selection) -> dict[str, object]:
        start, end = window(now, selection)
        rows = await self.repository.rows(start, end, selection)
        last_observed = max((row.last for row in rows), default=None)
        # Rows can commit after the request clock was captured, or after a clock rollback.
        # Only an observation inside the already selected window can advance its watermark.
        generated_at = (
            max(now, last_observed) if last_observed is not None and start <= last_observed < end else now
        )
        names = {'page_view': 'page_views', 'section_view': 'section_views', 'public_click': 'public_clicks'}
        totals = dict.fromkeys(names.values(), 0)
        daily: dict[str, dict[str, int]] = {}
        cells: dict[tuple[int, int], int] = defaultdict(int)
        for row in rows:
            key = names[row.name]
            totals[key] += row.count
            day = row.day.astimezone(UTC).date().isoformat()
            daily.setdefault(day, dict.fromkeys(names.values(), 0))[key] += row.count
            if row.name == 'public_click':
                cells[row.x, row.y] += row.count
        available = selection.route != 'all' and selection.section_id != 'all'
        visible = (
            [{'x': x, 'y': y, 'count': count} for (x, y), count in sorted(cells.items()) if count >= 3]
            if available
            else []
        )
        visible_count = sum(cell['count'] for cell in visible)
        total = sum(totals.values())
        return {
            'synthetic': self.synthetic,
            'generated_at': generated_at,
            'selection': {
                'period': selection.period,
                'offset': selection.offset,
                'route': selection.route,
                'section_id': selection.section_id,
                'viewport_bucket': selection.viewport_bucket,
                'locale': selection.locale,
            },
            'start': start,
            'end': end,
            'partial': start <= generated_at < end,
            'first_observed_at': min((row.first for row in rows), default=None),
            'last_observed_at': last_observed,
            'totals': totals,
            'daily': [{'day': day, **counts} for day, counts in sorted(daily.items())],
            'countries': [{'code': 'unknown' if total >= 3 else 'withheld', 'count': total}] if total else [],
            'grid': {
                'available': available,
                'visible_clicks': visible_count,
                'withheld_clicks': totals['public_clicks'] - visible_count if available else 0,
                'unselected_clicks': 0 if available else totals['public_clicks'],
                'cells': visible,
            },
        }
