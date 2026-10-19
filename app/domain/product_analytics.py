"""Content-free Peque site profile and UTC aggregate vocabulary (no collection authority)."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal

PROFILE_SOURCE: Final = '88d6d0add414261e5ccf5bd3e2b21285e1a33179'
LAYOUT: Final = 'pequeverso-v1'
PROFILE = {
    '/': ('hero', 'leer', 'bebe', 'preguntas'),
    '/grafismo-fonetico/': ('hero', 'incluye', 'metodo', 'preguntas'),
}
EventName = Literal['page_view', 'section_view', 'public_click']
Viewport = Literal['mobile', 'tablet', 'desktop']
Period = Literal['day', 'week', 'month']


@dataclass(frozen=True, slots=True)
class Event:
    digest: str
    name: EventName
    route: str
    section: str
    viewport: Viewport
    cell_x: int | None = None
    cell_y: int | None = None
    country: str = 'unknown'


@dataclass(frozen=True, slots=True)
class Selection:
    period: Period = 'day'
    offset: int = 0
    route: str = 'all'
    section_id: str = 'all'
    viewport_bucket: str = 'all'
    locale: str = 'es'

    def __post_init__(self) -> None:
        if (
            self.period not in ('day', 'week', 'month')
            or type(self.offset) is not int
            or not 0 <= self.offset <= 2
        ):
            raise ValueError('invalid calendar selection')
        if self.locale != 'es' or self.viewport_bucket not in ('all', 'mobile', 'tablet', 'desktop'):
            raise ValueError('invalid profile selection')
        if self.route != 'all' and self.route not in PROFILE:
            raise ValueError('unknown public route')
        sections = set(sum(PROFILE.values(), ())) if self.route == 'all' else set(PROFILE[self.route])
        if self.section_id != 'all' and self.section_id not in sections:
            raise ValueError('unknown route/section pair')


def window(now: datetime, selection: Selection) -> tuple[datetime, datetime]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('aware UTC clock required')
    start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    if selection.period == 'day':
        start -= timedelta(days=selection.offset)
        return start, start + timedelta(days=1)
    if selection.period == 'week':
        start -= timedelta(days=start.weekday() + selection.offset * 7)
        return start, start + timedelta(days=7)
    number = start.year * 12 + start.month - 1 - selection.offset
    year, month = divmod(number, 12)
    start = start.replace(year=year, month=month + 1, day=1)
    return start, start + timedelta(days=calendar.monthrange(year, month + 1)[1])
