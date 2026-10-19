"""Independent schema1 analytics contracts; no client-controlled fixture classification."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from dataclasses import fields
from datetime import datetime, timedelta
from typing import Any, Final, Literal, Self

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import UUID4, BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from starlette.types import Receive, Scope, Send

from app.application.ports import Clock
from app.application.product_analytics import AnalyticsService, QuotaExceededError
from app.domain.analytics_country import COUNTRIES
from app.domain.product_analytics import LAYOUT, PROFILE, PROFILE_SOURCE, Event, Selection, window
from app.presentation.analytics_country import country_from_edge
from app.presentation.middleware import BodyLimitMiddleware

PUBLIC_PATH: Final = '/api/v1/analytics/events'


class AnalyticsBodyLimitMiddleware(BodyLimitMiddleware):
    """One streaming-owned endpoint; every other unsafe request retains the global buffer."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] == 'http' and scope['method'] == 'POST' and scope['path'] == PUBLIC_PATH:
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


Route = Literal['/', '/grafismo-fonetico/']
Section = Literal['hero', 'leer', 'bebe', 'preguntas', 'incluye', 'metodo']
Viewport = Literal['mobile', 'tablet', 'desktop']


def _profile_schema(schema: dict[str, Any]) -> None:
    schema['allOf'] = [
        {
            'if': {'properties': {'route': {'const': route}}},
            'then': {'properties': {'section_id': {'enum': list(sections)}}},
        }
        for route, sections in PROFILE.items()
    ] + [
        {
            'if': {'properties': {'event_name': {'const': 'public_click'}}},
            'then': {
                'required': ['cell_x', 'cell_y'],
                'properties': {'cell_x': {'type': 'integer'}, 'cell_y': {'type': 'integer'}},
            },
            'else': {'not': {'anyOf': [{'required': ['cell_x']}, {'required': ['cell_y']}]}},
        }
    ]


class _Closed(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class EventIn(_Closed):
    model_config = ConfigDict(extra='forbid', frozen=True, json_schema_extra=_profile_schema)
    schema_version: Literal[1]
    project: Literal['pequeverso']
    source: Literal['site']
    event_id: UUID4
    event_name: Literal['page_view', 'section_view', 'public_click']
    route: Route
    layout_revision: Literal['pequeverso-v1']
    section_id: Section
    viewport_bucket: Viewport
    locale: Literal['es']
    cell_x: int | None = Field(default=None, strict=True, ge=0, le=7)
    cell_y: int | None = Field(default=None, strict=True, ge=0, le=7)

    @field_validator('schema_version', mode='before')
    @classmethod
    def integer_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError('integer schema version required')
        return value

    @model_validator(mode='after')
    def profile(self) -> Self:
        if self.section_id not in PROFILE[self.route]:
            raise ValueError('unknown route/section pair')
        if self.event_name == 'public_click':
            if self.cell_x is None or self.cell_y is None:
                raise ValueError('pointer clicks require both grid cells')
        elif {'cell_x', 'cell_y'} & self.model_fields_set:
            raise ValueError('non-click events cannot contain coordinates')
        return self

    def event(self, *, country: str = 'unknown') -> Event:
        return Event(
            hashlib.sha256(self.event_id.bytes).hexdigest(),
            self.event_name,
            self.route,
            self.section_id,
            self.viewport_bucket,
            self.cell_x,
            self.cell_y,
            country,
        )


class SelectionOut(_Closed):
    period: Literal['day', 'week', 'month']
    offset: int = Field(strict=True, ge=0, le=2)
    route: Literal['all', '/', '/grafismo-fonetico/']
    section_id: Literal['all', 'hero', 'leer', 'bebe', 'preguntas', 'incluye', 'metodo']
    viewport_bucket: Literal['all', 'mobile', 'tablet', 'desktop']
    locale: Literal['es']

    @model_validator(mode='after')
    def valid_selection(self) -> Self:
        Selection(**self.model_dump())
        return self


class Counts(_Closed):
    page_views: int = Field(strict=True, ge=0, le=310000)
    section_views: int = Field(strict=True, ge=0, le=310000)
    public_clicks: int = Field(strict=True, ge=0, le=310000)


class Daily(Counts):
    day: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')


class Cell(_Closed):
    x: int = Field(strict=True, ge=0, le=7)
    y: int = Field(strict=True, ge=0, le=7)
    count: int = Field(strict=True, ge=3, le=310000)


class Grid(_Closed):
    available: bool
    visible_clicks: int = Field(strict=True, ge=0, le=310000)
    withheld_clicks: int = Field(strict=True, ge=0, le=310000)
    unselected_clicks: int = Field(strict=True, ge=0, le=310000)
    cells: list[Cell] = Field(max_length=64)


class Country(_Closed):
    code: str = Field(json_schema_extra={'enum': [*sorted(COUNTRIES), 'unknown', 'withheld']})
    count: int = Field(strict=True, ge=1, le=310000)

    @model_validator(mode='after')
    def valid_country(self) -> Self:
        if self.code not in COUNTRIES | {'unknown', 'withheld'}:
            raise ValueError('unknown country label')
        if self.code != 'withheld' and self.count < 3:
            raise ValueError('small country bucket must be withheld')
        return self


class ReportOut(_Closed):
    model_config = ConfigDict(extra='forbid', frozen=True, json_schema_serialization_defaults_required=True)
    schema_version: Literal[1] = 1
    project: Literal['pequeverso'] = 'pequeverso'
    layout_revision: Literal['pequeverso-v1'] = LAYOUT
    profile_source_revision: Literal['88d6d0add414261e5ccf5bd3e2b21285e1a33179'] = PROFILE_SOURCE
    synthetic: bool = Field(strict=True)
    coverage: Literal['received_events_only'] = 'received_events_only'
    timezone: Literal['UTC'] = 'UTC'
    country_collection: Literal['disabled', 'trusted_proxy_header'] = 'disabled'
    retention_days: Literal[93] = 93
    min_bucket: Literal[3] = 3
    generated_at: datetime
    selection: SelectionOut
    start: datetime
    end: datetime
    partial: bool
    first_observed_at: datetime | None
    last_observed_at: datetime | None
    totals: Counts
    daily: list[Daily] = Field(max_length=31)
    countries: list[Country] = Field(max_length=250)
    grid: Grid

    @model_validator(mode='after')
    def consistent(self) -> Self:
        times = [self.generated_at, self.start, self.end, self.first_observed_at, self.last_observed_at]
        if any(
            value is not None and (value.tzinfo is None or value.utcoffset() != timedelta(0))
            for value in times
        ):
            raise ValueError('report timestamps must be aware UTC')
        selection = Selection(**self.selection.model_dump())
        start, end = window(self.generated_at, selection)
        if (self.start, self.end) != (start, end) or self.partial != (start <= self.generated_at < end):
            raise ValueError('inconsistent calendar window')
        daily_days = [row.day for row in self.daily]
        if daily_days != sorted(set(daily_days)):
            raise ValueError('daily buckets must be ordered and unique')
        for row in self.daily:
            day = datetime.fromisoformat(row.day).date()
            if (
                not self.start.date() <= day < self.end.date()
                or sum((row.page_views, row.section_views, row.public_clicks)) > 10000
            ):
                raise ValueError('daily count/window bound violated')
        for name in ('page_views', 'section_views', 'public_clicks'):
            if sum(getattr(row, name) for row in self.daily) != getattr(self.totals, name):
                raise ValueError('daily totals do not reconcile')
        total = sum((self.totals.page_views, self.totals.section_views, self.totals.public_clicks))
        if sum(row.count for row in self.countries) != total:
            raise ValueError('country totals do not reconcile')
        codes = [row.code for row in self.countries]
        if codes != sorted(set(codes) - {'withheld'}) + (['withheld'] if 'withheld' in codes else []):
            raise ValueError('country buckets must be unique and ordered')
        if total == 0:
            if self.first_observed_at is not None or self.last_observed_at is not None:
                raise ValueError('empty report has no observations')
        elif (
            self.first_observed_at is None
            or self.last_observed_at is None
            or not self.start <= self.first_observed_at <= self.last_observed_at < self.end
            or self.last_observed_at > self.generated_at
        ):
            raise ValueError('invalid observed interval')
        grid = self.grid
        available = selection.route != 'all' and selection.section_id != 'all'
        coordinates = [(cell.x, cell.y) for cell in grid.cells]
        if grid.available != available or coordinates != sorted(set(coordinates)):
            raise ValueError('invalid grid selection/order')
        if sum(cell.count for cell in grid.cells) != grid.visible_clicks:
            raise ValueError('cell totals do not reconcile')
        if grid.visible_clicks + grid.withheld_clicks + grid.unselected_clicks != self.totals.public_clicks:
            raise ValueError('click totals do not reconcile')
        if (available and grid.unselected_clicks != 0) or (
            not available and (grid.cells or grid.visible_clicks or grid.withheld_clicks)
        ):
            raise ValueError('unselected regions cannot produce a blended grid')
        return self


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate field')
        result[key] = value
    return result


def build_router(
    service: AnalyticsService | None,
    *,
    enabled: bool,
    token_digest: bytes | None,
    origins: tuple[str, ...],
    clock: Clock,
    country_enabled: bool = False,
    country_proxy_ips: str = '',
) -> APIRouter:
    router = APIRouter()
    headers = {'Cache-Control': 'no-store'}

    @router.post(PUBLIC_PATH, include_in_schema=False)
    async def ingest(request: Request) -> Response:
        if not enabled or service is None:
            return Response(status_code=404, headers=headers)
        if (
            'cookie' in request.headers
            or 'authorization' in request.headers
            or len(request.headers.getlist('origin')) != 1
            or request.headers.get('origin') not in origins
        ):
            return Response(status_code=403, headers=headers)
        content_type = request.headers.get('content-type', '').lower().replace(' ', '')
        if len(request.headers.getlist('content-type')) != 1 or content_type not in (
            'application/json',
            'application/json;charset=utf-8',
        ):
            return Response(status_code=415, headers=headers)
        try:
            async with asyncio.timeout(10):
                body = bytearray()
                async for chunk in request.stream():
                    if len(body) + len(chunk) > 1024:
                        return Response(status_code=413, headers=headers)
                    body.extend(chunk)
                value = json.loads(body.decode('utf-8'), object_pairs_hook=_unique_object)
                event = EventIn.model_validate(value).event(
                    country=country_from_edge(
                        request, enabled=country_enabled, trusted_peers=country_proxy_ips
                    )
                )
                if not await service.repository.ready():
                    return Response(status_code=503, headers=headers)
                await service.ingest(event, clock.now())
                return Response(status_code=204, headers=headers)
        except (ValueError, UnicodeError, ValidationError):
            return Response(status_code=422, headers=headers)
        except QuotaExceededError:
            return Response(status_code=429, headers={**headers, 'Retry-After': '60'})
        except TimeoutError:
            return Response(status_code=408, headers=headers)
        except Exception:  # noqa: BLE001 - database/client failure never exports payload or SQL
            return Response(status_code=503, headers=headers)

    @router.get('/internal/v1/ops/product-analytics', include_in_schema=False)
    async def report(request: Request) -> Response:
        if not enabled or service is None or token_digest is None:
            return Response(status_code=404, headers=headers)
        authorization = request.headers.get('authorization', '')
        if (
            len(request.headers.getlist('authorization')) != 1
            or not authorization.startswith('Bearer ')
            or not hmac.compare_digest(hashlib.sha256(authorization[7:].encode()).digest(), token_digest)
        ):
            return Response(status_code=401, headers=headers)
        pairs = list(request.query_params.multi_items())
        allowed = {field.name for field in fields(Selection)}
        if len({key for key, _ in pairs}) != len(pairs) or any(key not in allowed for key, _ in pairs):
            return Response(status_code=422, headers=headers)
        try:
            values = dict(pairs)
            # No coercion of negative, fractional, whitespace or arbitrarily long integer input.
            offset = values.pop('offset', '0')
            if offset not in ('0', '1', '2'):
                raise ValueError('invalid offset')
            selection = SelectionOut.model_validate(
                {
                    'period': 'day',
                    'route': 'all',
                    'section_id': 'all',
                    'viewport_bucket': 'all',
                    'locale': 'es',
                    **values,
                    'offset': int(offset),
                }
            )
        except (ValueError, ValidationError):
            return Response(status_code=422, headers=headers)
        try:
            async with asyncio.timeout(10):
                if not await service.repository.ready():
                    return Response(status_code=503, headers=headers)
                value = await service.report(clock.now(), Selection(**selection.model_dump()))
                output = ReportOut.model_validate(value)
                return JSONResponse(output.model_dump(mode='json'), headers=headers)
        except Exception:  # noqa: BLE001 - malformed upstream/dependency never exports private details
            return Response(status_code=503, headers=headers)

    return router
