"""Pin the fail-closed configuration rules and their precedence."""

from __future__ import annotations

import os
import re
from typing import Any

import pytest
from pydantic import ValidationError

from app.bootstrap.config import _FAIL_CLOSED_RULES, DEV_CLIENT_HASH_KEY, Settings

_OPENAI = {
    "ai_provider": "openai",
    "allow_paid_ai": True,
    "openai_api_key": "sk-test-not-a-real-key",
}
_PRODUCTION = {
    "environment": "production",
    "assistant_enabled": False,
    "session_cookie_secure": True,
    "allowed_origins": ["https://pequeverso.com"],
    "client_hash_key": "test-only-client-hash-key-0000000000",
}
_GRAPHRAG = {
    "application_storage": "postgres",
    "knowledge_backend": "graphrag",
    "postgres_private_dsn": "postgresql://postgres/assistant",
    "postgres_knowledge_dsn": "postgresql://postgres/knowledge",
    "neo4j_uri": "bolt://neo4j:7687",
    "neo4j_password": "test-only-password",
}


@pytest.fixture(autouse=True)
def _no_ambient_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(os.environ):
        if name.lower() in Settings.model_fields or name.startswith("OTEL_"):
            monkeypatch.delenv(name)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        pytest.param(
            # The unsupported model also violates the general OpenAI model rule.
            _OPENAI | {"official_help_enabled": True, "openai_model": "unsupported-model"},
            "official help requires gpt-6-luna with medium reasoning",
            id="official-help-model",
        ),
        pytest.param(
            {"telemetry_otlp_endpoint": "https://collector.example/v1/traces"},
            "OTLP requires enabled observability and an explicit safe /v1/traces endpoint",
            id="otlp-endpoint",
        ),
        pytest.param(
            {
                "observability_enabled": True,
                "telemetry_otlp_endpoint": "http://collector.example/v1/traces",
            },
            "plain HTTP OTLP is restricted to a private single-label service or loopback",
            id="plain-http-otlp",
        ),
        pytest.param(
            {"ai_provider": "openai"},
            "AI_PROVIDER=openai requires ALLOW_PAID_AI=true and OPENAI_API_KEY",
            id="paid-ai-opt-in",
        ),
        pytest.param(
            _OPENAI | {"openai_reasoning_effort": "low"},
            "OpenAI answers require gpt-6-luna with medium reasoning; no fallback",
            id="openai-model",
        ),
        pytest.param(
            _PRODUCTION | {"assistant_enabled": True},
            "production cannot serve fixture answers; set AI_PROVIDER=openai or disable the assistant",
            id="production-fixture",
        ),
        pytest.param(
            {"daily_budget_usd": "11"},
            "DAILY_BUDGET_USD cannot exceed MONTHLY_BUDGET_USD",
            id="daily-budget",
        ),
        pytest.param(
            {"allowed_origins": ["https://pequeverso.com/path"]},
            "ALLOWED_ORIGINS entries must be bare origins like https://host",
            id="bare-origins",
        ),
        pytest.param(
            {"trusted_proxy_cidrs": ["invalid-cidr"]},
            "'invalid-cidr' does not appear to be an IPv4 or IPv6 network",
            id="trusted-proxy-cidrs",
        ),
        pytest.param(
            _PRODUCTION | {"session_cookie_secure": False},
            "production requires SESSION_COOKIE_SECURE=true",
            id="production-cookie",
        ),
        pytest.param(
            _PRODUCTION | {"allowed_origins": ["http://pequeverso.com"]},
            "production ALLOWED_ORIGINS must be https and not localhost",
            id="production-origins",
        ),
        pytest.param(
            _PRODUCTION | {"ops_read_token": "short-test-token"},
            "OPS_READ_TOKEN must be at least 32 characters",
            id="production-ops-token",
        ),
        pytest.param(
            _PRODUCTION | {"client_hash_key": DEV_CLIENT_HASH_KEY},
            "production requires a CLIENT_HASH_KEY of at least 32 characters",
            id="production-hash-key",
        ),
        pytest.param(
            _PRODUCTION | _OPENAI | {"assistant_enabled": True},
            "production answers require PostgreSQL application storage and GraphRAG",
            id="production-answer-storage",
        ),
        pytest.param(
            {"product_analytics_country_enabled": True},
            "country attribution requires exact trusted proxy IP addresses",
            id="country-attribution",
        ),
        pytest.param(
            {"product_analytics_enabled": True},
            "product analytics requires PostgreSQL application storage",
            id="analytics-storage",
        ),
        pytest.param(
            _GRAPHRAG | {"postgres_private_dsn": None},
            "PostgreSQL application storage requires POSTGRES_PRIVATE_DSN",
            id="private-postgres-dsn",
        ),
        pytest.param(
            _GRAPHRAG | {"neo4j_password": None},
            "GraphRAG requires explicit PostgreSQL and authenticated Neo4j configuration",
            id="graphrag-credentials",
        ),
        pytest.param(
            _GRAPHRAG | {"knowledge_backend": "sqlite"},
            "PostgreSQL application storage and GraphRAG must be selected together",
            id="storage-pair",
        ),
        pytest.param(
            _GRAPHRAG | {"postgres_private_dsn": "https://postgres/assistant"},
            "PostgreSQL DSNs must be explicit database URIs",
            id="postgres-dsn-uris",
        ),
        pytest.param(
            _GRAPHRAG | {"neo4j_uri": "bolt://neo4j:7687/path"},
            "Neo4j requires a bare Bolt URI; credentials use private fields",
            id="neo4j-uri",
        ),
    ],
)
def test_fail_closed_rule(overrides: dict[str, Any], message: str) -> None:
    """Reject an invalid configuration with the original error."""
    with pytest.raises(ValidationError, match=re.escape(message)) as error:
        Settings(_env_file=None, **overrides)
    assert str(error.value.errors()[0]["ctx"]["error"]) == message


def test_fail_closed_rejects_ambient_otel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reject ambient OTEL settings even with a valid explicit endpoint."""
    monkeypatch.setenv("OTEL_SERVICE_NAME", "fixture")
    message = (
        "ambient OTEL configuration is unsupported; use explicit application telemetry settings"
    )
    with pytest.raises(ValidationError, match=re.escape(message)) as error:
        Settings(
            _env_file=None,
            observability_enabled=True,
            telemetry_otlp_endpoint="https://collector.example/v1/traces",
        )
    assert str(error.value.errors()[0]["ctx"]["error"]) == message


def test_fail_closed_rule_order() -> None:
    """Keep the original first-error precedence."""
    assert tuple(rule.__name__ for rule in _FAIL_CLOSED_RULES) == (
        "_check_official_help_model",
        "_check_ambient_otel",
        "_check_otlp_endpoint",
        "_check_plain_http_otlp",
        "_check_paid_ai_opt_in",
        "_check_openai_model",
        "_check_production_fixture",
        "_check_daily_budget",
        "_check_bare_origins",
        "_check_trusted_proxy_cidrs",
        "_check_production_cookie",
        "_check_production_origins",
        "_check_production_ops_token",
        "_check_production_hash_key",
        "_check_production_answer_storage",
        "_check_country_attribution",
        "_check_analytics_storage",
        "_check_private_postgres_dsn",
        "_check_graphrag_credentials",
        "_check_storage_pair",
        "_check_postgres_dsn_uris",
        "_check_neo4j_uri",
    )


def test_fail_closed_accepts_default_fixture_settings() -> None:
    """Accept default fixture settings and return the same instance."""
    settings = Settings(_env_file=None)
    assert settings.ai_provider == "fixture"
    assert settings.fail_closed() is settings


@pytest.mark.parametrize(
    "endpoint",
    ["http://localhost/v1/traces", "http://collector/v1/traces", "http://[::1]/v1/traces"],
)
def test_plain_http_otlp_accepts_loopback_and_single_label_services(endpoint: str) -> None:
    """Accept plain HTTP only for loopback or a private single-label service."""
    settings = Settings(
        _env_file=None, observability_enabled=True, telemetry_otlp_endpoint=endpoint
    )
    assert settings.telemetry_otlp_endpoint == endpoint


def test_earlier_rule_wins_when_two_rules_fail() -> None:
    """Report the first failing rule in table order, not a later one."""
    message = "DAILY_BUDGET_USD cannot exceed MONTHLY_BUDGET_USD"
    with pytest.raises(ValidationError, match=re.escape(message)) as error:
        Settings(
            _env_file=None,
            **_PRODUCTION
            | {"session_cookie_secure": False, "daily_budget_usd": 20, "monthly_budget_usd": 10},
        )
    assert str(error.value.errors()[0]["ctx"]["error"]) == message
