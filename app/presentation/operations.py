"""Serve the backoffice operations API on private routes.

The proxy must keep /internal/* private. Require bearer authentication and compare
token digests in constant time. Return 404 when operations authentication is unconfigured.
"""

import hashlib
import hmac
from datetime import datetime
from typing import Annotated, Literal, Self

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from app.application.operations import OperationsService, Summary
from app.application.telemetry import TelemetryPort
from app.presentation.middleware import request_id_of
from app.presentation.schemas import ErrorOut
from app.presentation.telemetry import OpsTelemetryOut


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ServiceOut(_Out):
    """Describe the running service, model configuration, and fixture status."""

    environment: str
    revision: str | None
    provider: Literal["fixture", "openai"]
    model: str
    reasoning_effort: str
    assistant_enabled: bool
    started_at: datetime
    synthetic: bool = Field(
        description="True in fixture mode: every number comes from simulated answers."
    )


class OpsAvailabilityOut(_Out):
    """Report whether the assistant accepts questions and give the reason if unavailable."""

    status: Literal["available", "unavailable"]
    reason: str | None


class CatalogOut(_Out):
    """Report catalog provenance, freshness, and the latest synchronization status."""

    status: Literal["active", "missing"]
    source: Literal["bundled", "live"]
    revision: str | None
    sha256: str | None
    generated_at: datetime | None
    verified_at: datetime | None
    activated_at: datetime | None
    price_status: Literal["verified", "unverified"] | None
    price_max_age_hours: int
    last_attempt_at: datetime | None
    last_failure: str | None
    last_failure_at: datetime | None
    products: int | None
    documents: int | None


class SpendOut(_Out):
    """Break down spend in USD into confirmed, estimated, and pending amounts."""

    confirmed: str = Field(description="USD settled to provider-reported usage.")
    estimated: str = Field(
        description="USD kept as worst-case estimate: the run ended without a usage report."
    )
    pending: str = Field(description="USD reserved by runs still in progress.")


class BudgetOut(_Out):
    """Report daily and monthly limits, spend, and remaining monthly budget."""

    month: str
    day: str
    monthly_limit: str
    monthly_cutoff: str
    daily_limit: str
    month_spend: SpendOut
    day_spend: SpendOut
    remaining_month: str


class RunCountsOut(_Out):
    """Count runs by their reported outcome."""

    completed: int
    failed: int
    cancelled: int
    interrupted: int
    refused: int


class PercentilesOut(_Out):
    """Report median and 95th-percentile latency with the sample count."""

    p50: int
    p95: int
    count: int


class LatencyOut(_Out):
    """Report time to first answer text and time to final answer in milliseconds."""

    first_delta: PercentilesOut | None = Field(
        description="Request accepted → first answer text (model runs)."
    )
    total: PercentilesOut | None = Field(
        description="Request accepted → authoritative answer (completed model runs)."
    )


class TokensOut(_Out):
    """Summarize token usage and the number of runs with usage reports."""

    input: int
    cached_input: int
    output: int
    reasoning: int
    runs_with_usage: int


class WindowOut(_Out):
    """Summarize run outcomes, failures, latency, and tokens over a time window."""

    hours: int
    runs: RunCountsOut
    replaced: int
    failures: dict[str, int]
    latency_ms: LatencyOut
    tokens: TokensOut


class DailyOut(_Out):
    """Report outcomes, settled and estimated spend, and token totals for one day."""

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


class PricingOut(_Out):
    """Describe the model rates and revision used for cost estimates."""

    revision: str = Field(
        description="Source of the rates used for estimates; not the provider invoice."
    )
    model: str
    input_per_million: str
    cached_input_per_million: str
    cache_write_per_million: str
    output_per_million: str = Field(description="Also applies to reasoning tokens.")


class RecentRunOut(_Out):
    """Summarize a recent run's outcome, timing, and answer metadata."""

    id: str = Field(
        description="Opaque: a digest of the run id, not usable against the public API."
    )
    started_at: datetime
    outcome: Literal["completed", "failed", "cancelled", "interrupted", "refused"]
    code: str | None
    model_call: bool
    replaced: bool
    language: Literal["es", "en"] | None
    first_delta_ms: int | None
    total_ms: int


class OpsSummaryOut(_Out):
    """Report service status, catalog freshness, and assistant usage and spend."""

    schema_version: Literal["1"] = "1"
    generated_at: datetime
    service: ServiceOut
    availability: OpsAvailabilityOut
    catalog: CatalogOut
    budget: BudgetOut
    windows: list[WindowOut]
    daily: list[DailyOut] = Field(
        description="Only days with records (no zero-filled gaps), oldest first."
    )
    metrics_since: datetime | None = Field(
        description="First recorded run; earlier periods are unknown."
    )
    pricing: PricingOut
    recent: list[RecentRunOut] = Field(description="Up to 50 latest runs, newest first.")

    @classmethod
    def of(cls, summary: Summary) -> Self:
        """Convert the application summary to its wire representation."""
        info = summary.service
        return cls.model_validate(
            {
                "generated_at": summary.generated_at,
                "service": {
                    "environment": info.environment,
                    "revision": info.revision,
                    "provider": info.provider,
                    "model": info.model,
                    "reasoning_effort": info.reasoning_effort,
                    "assistant_enabled": info.assistant_enabled,
                    "started_at": info.started_at,
                    "synthetic": info.synthetic,
                },
                "availability": {
                    "status": "available" if summary.availability is None else "unavailable",
                    "reason": summary.availability.value if summary.availability else None,
                },
                "catalog": summary.catalog,
                "budget": summary.budget,
                "windows": summary.windows,
                "daily": summary.daily,
                "metrics_since": summary.metrics_since,
                "pricing": info.pricing,
                "recent": [
                    {
                        "id": r.id,
                        "started_at": r.started_at,
                        "outcome": r.outcome,
                        "code": r.code,
                        "model_call": r.model_call,
                        "replaced": r.replaced,
                        "language": r.language,
                        "first_delta_ms": r.first_delta_ms,
                        "total_ms": r.total_ms,
                    }
                    for r in summary.recent
                ],
            }
        )


def _unauthorized(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "error": {
                "code": "unauthorized",
                "message": "Missing or invalid operations token.",
                "retryable": False,
                "request_id": request_id_of(request.scope),
            }
        },
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
    )


def build_router(
    service: OperationsService,
    token_digest: bytes,
    telemetry: TelemetryPort | None = None,
) -> APIRouter:
    """Build authenticated operations routes with optional runtime telemetry."""
    router = APIRouter(prefix="/internal/v1/ops", include_in_schema=False)
    unauthorized_response = {
        "model": ErrorOut,
        "description": "Missing or invalid operations token",
        "headers": {"WWW-Authenticate": {"schema": {"type": "string", "const": "Bearer"}}},
    }

    def authorized(authorization: Annotated[str | None, Header()] = None) -> bool:
        scheme, _, value = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not value:
            return False
        return hmac.compare_digest(hashlib.sha256(value.encode()).digest(), token_digest)

    @router.get("/summary", response_model=OpsSummaryOut, responses={401: unauthorized_response})
    async def summary(
        request: Request, ok: Annotated[bool, Depends(authorized)]
    ) -> OpsSummaryOut | JSONResponse:
        if not ok:
            return _unauthorized(request)
        return OpsSummaryOut.of(await service.summary())

    if telemetry is not None:

        @router.get(
            "/telemetry", response_model=OpsTelemetryOut, responses={401: unauthorized_response}
        )
        async def runtime_telemetry(
            request: Request,
            ok: Annotated[bool, Depends(authorized)],
        ) -> OpsTelemetryOut | JSONResponse:
            if not ok:
                return _unauthorized(request)
            return OpsTelemetryOut.of(await telemetry.snapshot())

        @router.get(
            "/metrics",
            response_class=Response,
            responses={
                200: {
                    "description": "Prometheus exposition format",
                    "content": {"text/plain": {"schema": {"type": "string"}}},
                },
                401: unauthorized_response,
            },
        )
        async def metrics(request: Request, ok: Annotated[bool, Depends(authorized)]) -> Response:
            if not ok:
                return _unauthorized(request)
            return Response(
                await telemetry.prometheus(),
                media_type="text/plain; version=0.0.4; charset=utf-8",
                headers={"Cache-Control": "no-store"},
            )

    return router
