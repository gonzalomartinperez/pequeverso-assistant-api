"""HTTP assembly: FastAPI instance, services state, routers, error handlers, middleware (PVA-M4.1)."""

from __future__ import annotations

import hashlib
import ipaddress
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import iter_route_contexts

from app.presentation.http import (
    CookiePolicy,
    HttpSettings,
    Services,
    health,
    install_error_handlers,
    probes,
    router,
)
from app.presentation.middleware import OriginMiddleware, RequestContextMiddleware
from app.presentation.operations import build_router as build_operations_router
from app.presentation.product_analytics import AnalyticsBodyLimitMiddleware
from app.presentation.product_analytics import build_router as build_analytics_router

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractAsyncContextManager

    from app.bootstrap.config import Settings
    from app.bootstrap.wiring import Wiring


def _ops_digest(settings: Settings) -> bytes | None:
    if settings.ops_read_token is None:
        return None
    return hashlib.sha256(settings.ops_read_token.get_secret_value().encode()).digest()


def _http_settings(settings: Settings, schema_version: str) -> HttpSettings:
    return HttpSettings(
        cookie=CookiePolicy(
            name=settings.cookie_name,
            secure=settings.session_cookie_secure,
            samesite=settings.session_cookie_samesite,
            max_age_seconds=settings.session_retention_hours * 3600,
        ),
        trusted_proxies=tuple(ipaddress.ip_network(c) for c in settings.trusted_proxy_cidrs),
        client_hash_key=settings.client_hash_key.get_secret_value().encode(),
        heartbeat_seconds=settings.heartbeat_seconds,
        max_message_chars=settings.max_message_chars,
        messages_per_day=settings.messages_per_session_per_day,
        version=settings.service_revision or "unknown",
        schema_version=schema_version,
    )


def _include_routers(app: FastAPI, wiring: Wiring) -> None:
    settings = wiring.settings
    app.include_router(router)
    app.include_router(health)
    app.include_router(probes)
    app.include_router(
        build_analytics_router(
            wiring.analytics,
            enabled=settings.product_analytics_enabled,
            country_enabled=settings.product_analytics_country_enabled,
            country_proxy_ips=settings.product_analytics_country_proxy_ips,
            token_digest=_ops_digest(settings),
            origins=tuple(settings.allowed_origins),
            clock=wiring.clock,
        )
    )
    digest = _ops_digest(settings)
    if digest is not None:
        app.include_router(build_operations_router(wiring.operations, digest, wiring.telemetry))


def _install_middleware(app: FastAPI, wiring: Wiring) -> None:
    settings = wiring.settings
    # Outermost first at runtime: context → CORS → origin policy → body limit → routes.
    app.add_middleware(AnalyticsBodyLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(OriginMiddleware, allowed_origins=settings.allowed_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID", "X-Run-ID", "Retry-After"],
        max_age=600,
    )
    if wiring.telemetry is not None:
        from app.adapters.observability.telemetry import TelemetryMiddleware

        # FastAPI includes routers lazily; their top-level entries have no path.
        # Public route contexts enumerate the registered, effective templates.
        routes = frozenset(
            context.path for context in iter_route_contexts(app.routes) if context.path
        )
        private_digest = _ops_digest(settings) if settings.ops_read_token else None
        app.add_middleware(
            TelemetryMiddleware,
            telemetry=wiring.telemetry,
            routes=routes,
            private_token_digest=private_digest,
        )
    app.add_middleware(RequestContextMiddleware)


def build_http_app(
    wiring: Wiring,
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager[None]],
    schema_version: str,
) -> FastAPI:
    """Assemble the FastAPI application around already wired services."""
    settings = wiring.settings
    app = FastAPI(
        title="Pequeverso assistant API",
        version="1",
        lifespan=lifespan,
        # Only the explicit, content-free application telemetry may instrument requests.
        # FastAPI 0.142 introduces native instrumentation enabled by default.
        telemetry={
            "tracing": False,
            "metrics": False,
            "logs": False,
            "operation_spans": False,
            "auto_configure": False,
        },
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json" if settings.environment != "production" else None,
    )
    app.state.services = Services(
        sessions=wiring.sessions,
        chat=wiring.chat,
        catalog=wiring.catalog,
        clock=wiring.clock,
        ready=wiring.ready,
        cleanups=wiring.cleanups,
        settings=_http_settings(settings, schema_version),
    )
    _include_routers(app, wiring)
    install_error_handlers(app)
    _install_middleware(app, wiring)
    return app
