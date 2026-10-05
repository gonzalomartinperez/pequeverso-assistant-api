"""Private, server-to-server operations API for the backoffice. Not under the public `/api`
prefix: the proxy must not route `/internal/*`, and every request needs the bearer token. The
token is compared as a SHA-256 digest in constant time; without a configured token the routes
answer 404 as if they did not exist.
"""

import hashlib
import hmac
from datetime import datetime
from typing import Annotated, Literal, Self

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.application.operations import OperationsService, Summary
from app.presentation.middleware import request_id_of


class _Out(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class ServiceOut(_Out):
    environment: str
    revision: str | None
    provider: Literal['fixture', 'openai']
    model: str
    reasoning_effort: str
    assistant_enabled: bool
    started_at: datetime
    synthetic: bool = Field(description='True in fixture mode: every number comes from simulated answers.')


class OpsAvailabilityOut(_Out):
    status: Literal['available', 'unavailable']
    reason: str | None


class CatalogOut(_Out):
    status: Literal['active', 'missing']
    source: Literal['bundled', 'live']
    revision: str | None
    sha256: str | None
    generated_at: datetime | None
    verified_at: datetime | None
    activated_at: datetime | None
    price_status: Literal['verified', 'unverified'] | None
    price_max_age_hours: int
    last_attempt_at: datetime | None
    last_failure: str | None
    last_failure_at: datetime | None
    products: int | None
    documents: int | None


class SpendOut(_Out):
    confirmed: str = Field(description='USD settled to provider-reported usage.')
    estimated: str = Field(
        description='USD kept as worst-case estimate: the run ended without a usage report.'
    )
    pending: str = Field(description='USD reserved by runs still in progress.')


class BudgetOut(_Out):
    month: str
    day: str
    monthly_limit: str
    monthly_cutoff: str
    daily_limit: str
    month_spend: SpendOut
    day_spend: SpendOut
    remaining_month: str


class RunCountsOut(_Out):
    completed: int
    failed: int
    cancelled: int
    interrupted: int
    refused: int


class PercentilesOut(_Out):
    p50: int
    p95: int
    count: int


class LatencyOut(_Out):
    first_delta: PercentilesOut | None = Field(
        description='Request accepted → first answer text (model runs).'
    )
    total: PercentilesOut | None = Field(
        description='Request accepted → authoritative answer (completed model runs).'
    )


class TokensOut(_Out):
    input: int
    cached_input: int
    output: int
    reasoning: int
    runs_with_usage: int


class WindowOut(_Out):
    hours: int
    runs: RunCountsOut
    replaced: int
    failures: dict[str, int]
    latency_ms: LatencyOut
    tokens: TokensOut


class DailyOut(_Out):
    day: str
    completed: int
    failed: int
    cancelled: int
    interrupted: int
    refused: int
    confirmed: str
    estimated: str
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int


class OpsSummaryOut(_Out):
    schema_version: Literal['1'] = '1'
    generated_at: datetime
    service: ServiceOut
    availability: OpsAvailabilityOut
    catalog: CatalogOut
    budget: BudgetOut
    windows: list[WindowOut]
    daily: list[DailyOut] = Field(description='Only days with records (no zero-filled gaps), oldest first.')
    metrics_since: datetime | None = Field(description='First recorded run; earlier periods are unknown.')

    @classmethod
    def of(cls, summary: Summary) -> Self:
        info = summary.service
        return cls.model_validate(
            {
                'generated_at': summary.generated_at,
                'service': {
                    'environment': info.environment,
                    'revision': info.revision,
                    'provider': info.provider,
                    'model': info.model,
                    'reasoning_effort': info.reasoning_effort,
                    'assistant_enabled': info.assistant_enabled,
                    'started_at': info.started_at,
                    'synthetic': info.synthetic,
                },
                'availability': {
                    'status': 'available' if summary.availability is None else 'unavailable',
                    'reason': summary.availability.value if summary.availability else None,
                },
                'catalog': summary.catalog,
                'budget': summary.budget,
                'windows': summary.windows,
                'daily': summary.daily,
                'metrics_since': summary.metrics_since,
            }
        )


def _unauthorized(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            'error': {
                'code': 'unauthorized',
                'message': 'Missing or invalid operations token.',
                'retryable': False,
                'request_id': request_id_of(request.scope),
            }
        },
        status_code=401,
        headers={'WWW-Authenticate': 'Bearer'},
    )


def build_router(service: OperationsService, token_digest: bytes) -> APIRouter:
    router = APIRouter(prefix='/internal/v1/ops', include_in_schema=False)

    def authorized(authorization: Annotated[str | None, Header()] = None) -> bool:
        scheme, _, value = (authorization or '').partition(' ')
        if scheme.lower() != 'bearer' or not value:
            return False
        return hmac.compare_digest(hashlib.sha256(value.encode()).digest(), token_digest)

    @router.get('/summary', response_model=OpsSummaryOut)
    async def summary(
        request: Request, ok: Annotated[bool, Depends(authorized)]
    ) -> OpsSummaryOut | JSONResponse:
        if not ok:
            return _unauthorized(request)
        return OpsSummaryOut.of(await service.summary())

    return router
