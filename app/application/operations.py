"""Private operations summary for the backoffice: health, catalog freshness, runs, latency,
tokens and spend. Aggregates only: no session ids, messages, prompts, client keys or secrets.
Unknown values stay None (rendered as "not available"), never a fabricated zero.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from app.application.ports import CatalogView, Clock
from app.domain.budget import BudgetPolicy, from_micro
from app.domain.errors import FailureCode

WINDOWS_HOURS = (24, 720)
DAILY_DAYS = 30


@dataclass(frozen=True, slots=True)
class Spend:
    """Micro-dollars. confirmed: settled to provider usage; estimated: run ended without a usage
    report, the reservation is kept; pending: reservation of a run still in progress."""

    confirmed: int = 0
    estimated: int = 0
    pending: int = 0

    @property
    def total(self) -> int:
        return self.confirmed + self.estimated + self.pending


@dataclass(frozen=True, slots=True)
class Tokens:
    input: int = 0
    cached_input: int = 0
    output: int = 0
    reasoning: int = 0
    runs_with_usage: int = 0


@dataclass(frozen=True, slots=True)
class RunWindow:
    counts: dict[str, int]
    failures: dict[str, int]
    replaced: int
    first_delta_ms: Sequence[int]
    total_ms: Sequence[int]


@dataclass(frozen=True, slots=True)
class DailyRow:
    day: str
    counts: dict[str, int]
    spend: Spend
    tokens: Tokens


@dataclass(frozen=True, slots=True)
class CatalogState:
    activated_at: datetime | None
    last_attempt_at: datetime | None
    last_failure: str | None
    last_failure_at: datetime | None


class OperationsQueries(Protocol):
    async def spend(self, column: str, value: str) -> Spend: ...
    async def tokens(self, since: datetime) -> Tokens: ...
    async def run_window(self, since: datetime) -> RunWindow: ...
    async def daily(self, since_day: str) -> list[DailyRow]: ...
    async def metrics_since(self) -> datetime | None: ...
    async def catalog_state(self) -> CatalogState: ...


@dataclass(frozen=True, slots=True)
class ServiceInfo:
    environment: str
    revision: str | None
    provider: str
    model: str
    reasoning_effort: str
    assistant_enabled: bool
    started_at: datetime
    price_max_age_hours: int

    @property
    def synthetic(self) -> bool:
        return self.provider == 'fixture'


@dataclass(frozen=True, slots=True)
class Percentiles:
    p50: int
    p95: int
    count: int


def percentiles(values: Sequence[int]) -> Percentiles | None:
    """Nearest-rank p50/p95; None without data (an empty window has no latency)."""
    if not values:
        return None
    ordered = sorted(values)

    def rank(p: float) -> int:
        return ordered[max(0, math.ceil(p * len(ordered)) - 1)]

    return Percentiles(rank(0.50), rank(0.95), len(ordered))


@dataclass(frozen=True, slots=True)
class Summary:
    generated_at: datetime
    service: ServiceInfo
    availability: FailureCode | None
    catalog: dict[str, object]
    budget: dict[str, object]
    windows: list[dict[str, object]]
    daily: list[dict[str, object]]
    metrics_since: datetime | None
    notes: list[str] = field(default_factory=list)


def usd(micro: int) -> str:
    return f'{from_micro(micro):.6f}'


def _spend(spend: Spend) -> dict[str, str]:
    return {
        'confirmed': usd(spend.confirmed),
        'estimated': usd(spend.estimated),
        'pending': usd(spend.pending),
    }


def _tokens(tokens: Tokens) -> dict[str, int]:
    return {
        'input': tokens.input,
        'cached_input': tokens.cached_input,
        'output': tokens.output,
        'reasoning': tokens.reasoning,
        'runs_with_usage': tokens.runs_with_usage,
    }


class OperationsService:
    def __init__(
        self,
        queries: OperationsQueries,
        catalog: CatalogView,
        live_catalog: bool,
        clock: Clock,
        budget: BudgetPolicy,
        info: ServiceInfo,
        availability: AvailabilityCheck,
    ) -> None:
        self._queries = queries
        self._catalog = catalog
        self._live = live_catalog
        self._clock = clock
        self._budget = budget
        self._info = info
        self._availability = availability

    async def summary(self) -> Summary:
        now = self._clock.now()
        month, day = now.strftime('%Y-%m'), now.strftime('%Y-%m-%d')
        month_spend = await self._queries.spend('month', month)
        day_spend = await self._queries.spend('day', day)
        windows: list[dict[str, object]] = []
        for hours in WINDOWS_HOURS:
            since = now - timedelta(hours=hours)
            window = await self._queries.run_window(since)
            first, total = percentiles(window.first_delta_ms), percentiles(window.total_ms)
            windows.append(
                {
                    'hours': hours,
                    'runs': window.counts,
                    'replaced': window.replaced,
                    'failures': window.failures,
                    'latency_ms': {
                        'first_delta': None if first is None else vars_of(first),
                        'total': None if total is None else vars_of(total),
                    },
                    'tokens': _tokens(await self._queries.tokens(since)),
                }
            )
        since_day = (now - timedelta(days=DAILY_DAYS - 1)).strftime('%Y-%m-%d')
        daily = [
            {
                'day': row.day,
                **row.counts,
                'confirmed': usd(row.spend.confirmed),
                'estimated': usd(row.spend.estimated),
                'input_tokens': row.tokens.input,
                'output_tokens': row.tokens.output,
                'reasoning_tokens': row.tokens.reasoning,
            }
            for row in await self._queries.daily(since_day)
        ]
        return Summary(
            generated_at=now,
            service=self._info,
            availability=await self._availability(),
            catalog=await self._catalog_status(now),
            budget={
                'month': month,
                'day': day,
                'monthly_limit': usd(self._budget.monthly_limit_micro),
                'monthly_cutoff': usd(self._budget.monthly_cutoff_micro),
                'daily_limit': usd(self._budget.daily_cutoff_micro),
                'month_spend': _spend(month_spend),
                'day_spend': _spend(day_spend),
                'remaining_month': usd(max(0, self._budget.monthly_cutoff_micro - month_spend.total)),
            },
            windows=windows,
            daily=daily,
            metrics_since=await self._queries.metrics_since(),
        )

    async def _catalog_status(self, now: datetime) -> dict[str, object]:
        state = await self._queries.catalog_state()
        active = self._catalog.active
        common: dict[str, object] = {
            'source': 'live' if self._live else 'bundled',
            'price_max_age_hours': self._info.price_max_age_hours,
            'activated_at': state.activated_at,
            'last_attempt_at': state.last_attempt_at,
            'last_failure': state.last_failure,
            'last_failure_at': state.last_failure_at,
        }
        if active is None:
            return {
                'status': 'missing',
                **common,
                'revision': None,
                'sha256': None,
                'generated_at': None,
                'verified_at': None,
                'price_status': None,
                'products': None,
                'documents': None,
            }
        catalog = active.catalog
        return {
            'status': 'active',
            **common,
            'revision': catalog.source_revision,
            'sha256': active.sha256,
            'generated_at': catalog.generated_at,
            'verified_at': active.verified_at,
            'price_status': active.price_status(now).value,
            'products': len(catalog.products),
            'documents': len(catalog.documents),
        }


def vars_of(p: Percentiles) -> dict[str, int]:
    return {'p50': p.p50, 'p95': p.p95, 'count': p.count}


class AvailabilityCheck(Protocol):
    async def __call__(self) -> FailureCode | None: ...
