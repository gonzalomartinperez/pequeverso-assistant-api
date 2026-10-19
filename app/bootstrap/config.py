"""Runtime configuration (environment variables, optional `.env.local`). Fails closed: paid
providers need explicit opt-in, production needs https origins, secure cookies and real secrets.
"""

from __future__ import annotations

import ipaddress
import os
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = ROOT / 'catalog' / 'catalog.v1.json'
DEV_CLIENT_HASH_KEY = 'development-only-client-hash-key-000000'


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env.local', extra='ignore', hide_input_in_errors=True)

    environment: Literal['development', 'test', 'production'] = 'development'
    assistant_enabled: bool = True

    # Model provider. Fixture mode is the default and never calls a paid API.
    ai_provider: Literal['fixture', 'openai'] = 'fixture'
    allow_paid_ai: bool = False
    openai_api_key: SecretStr | None = None
    openai_model: str = 'gpt-6-luna'
    # gpt-6-luna accepts none|low|medium|high|xhigh|max (medium is the provider default); the
    # higher two are excluded here on cost grounds. Owner decision 2026-10: medium.
    openai_reasoning_effort: Literal['none', 'low', 'medium', 'high'] = 'medium'
    openai_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    # A timeout can already be billed: one reservation permits exactly one attempt.
    openai_max_retries: int = Field(default=0, ge=0, le=0)
    fixture_chunk_delay_ms: int = Field(default=0, ge=0, le=2000)

    # Pricing in USD per 1M tokens (gpt-6-luna list prices; re-read 2026-10-05, unchanged).
    # PRICING_REVISION names the source the estimates use; it is not the provider invoice.
    pricing_revision: str = 'openai-gpt-6-luna-2026-10-05'
    price_input_per_million: Decimal = Decimal('0.10')
    price_cached_input_per_million: Decimal = Decimal('0.01')
    price_cache_write_per_million: Decimal = Decimal('0.125')
    price_output_per_million: Decimal = Decimal('0.50')

    # Budget (USD). A design target, not a billing setting.
    monthly_budget_usd: Decimal = Field(default=Decimal('10.00'), gt=0)
    daily_budget_usd: Decimal = Field(default=Decimal('1.00'), gt=0)
    budget_safety_margin: Decimal = Field(default=Decimal('0.10'), ge=0, lt=1)

    # Per-request and abuse limits.
    max_message_chars: int = Field(default=600, ge=50, le=2000)
    # Includes reasoning tokens (billed as output). Too low a cap ends a medium-effort answer as
    # `incomplete` before any text; 4000 is a starting point to be tuned from live usage reports.
    max_output_tokens: int = Field(default=4000, ge=200, le=16000)
    max_input_tokens: int = Field(default=24000, ge=4000, le=100000)
    max_evidence_chars: int = Field(default=40000, ge=4000, le=200000)
    history_messages: int = Field(default=12, ge=0, le=40)
    messages_per_session_per_day: int = Field(default=30, ge=1)
    messages_per_client_per_hour: int = Field(default=60, ge=1)
    sessions_per_client_per_hour: int = Field(default=20, ge=1)
    max_concurrent_runs: int = Field(default=4, ge=1, le=64)
    run_timeout_seconds: float = Field(default=60.0, gt=0, le=120)
    heartbeat_seconds: float = Field(default=15.0, gt=0, le=60)
    max_body_bytes: int = Field(default=16 * 1024, ge=1024, le=256 * 1024)

    # Sessions and browser policy.
    session_retention_hours: int = Field(default=24, ge=1, le=24 * 30)
    session_cookie_secure: bool = False
    session_cookie_samesite: Literal['lax', 'strict'] = 'lax'
    allowed_origins: list[str] = ['http://localhost:3000', 'http://127.0.0.1:3000']
    trusted_proxy_cidrs: list[str] = []
    client_hash_key: SecretStr = SecretStr(DEV_CLIENT_HASH_KEY)

    # App-owned observability, disabled until explicitly configured by infrastructure.
    product_analytics_enabled: bool = False
    product_analytics_country_enabled: bool = False
    product_analytics_country_proxy_ips: str = Field(default='', max_length=1024)
    observability_enabled: bool = False
    telemetry_otlp_endpoint: str | None = None
    telemetry_trace_sampling_ratio: float = Field(default=0.1, ge=0, le=1)
    telemetry_export_timeout_seconds: float = Field(default=2.0, gt=0, le=5)

    # Optional server-owned official public help retrieval; fixture mode never uses the network.
    official_help_enabled: bool = False

    # Catalog.
    catalog_url: str | None = None
    catalog_file: Path = DEFAULT_CATALOG
    catalog_allowed_hosts: list[str] = ['pequeverso.com', 'consumer.hotmart.com', 'refund.hotmart.com']
    catalog_refresh_seconds: int = Field(default=900, ge=60)
    catalog_price_max_age_hours: int = Field(default=168, ge=1, le=24 * 60)

    database_path: str = str(ROOT / 'data' / 'assistant.sqlite3')

    # Production GraphRAG uses one relational service with separately privileged schemas.
    # SQLite remains an isolated fixture/legacy profile; changing this never imports old data.
    application_storage: Literal['sqlite', 'postgres'] = 'sqlite'
    knowledge_backend: Literal['sqlite', 'graphrag'] = 'sqlite'
    postgres_private_dsn: SecretStr | None = None
    postgres_knowledge_dsn: SecretStr | None = None
    postgres_private_pool_size: int = Field(default=4, ge=2, le=8)
    postgres_knowledge_pool_size: int = Field(default=2, ge=2, le=4)
    neo4j_uri: str | None = None
    neo4j_username: str = 'neo4j'
    neo4j_password: SecretStr | None = None
    embedding_input_price_per_million: Decimal = Field(default=Decimal('0.02'), gt=0)

    # Private operations API (server-to-server, backoffice). Unset = the endpoint does not exist.
    ops_read_token: SecretStr | None = None
    # Source revision baked into the image (build arg), shown to operators.
    service_revision: str | None = Field(default=None, pattern=r'^[0-9a-f]{7,40}$')

    @field_validator('product_analytics_country_proxy_ips')
    @classmethod
    def exact_country_proxy_ips(cls, value: str) -> str:
        if not value:
            return ''
        addresses = set()
        for item in value.split(','):
            try:
                address = ipaddress.ip_address(item.strip())
            except ValueError:
                raise ValueError('country requires exact proxy IP addresses') from None
            if getattr(address, 'scope_id', None):
                raise ValueError('invalid country proxy IP address')
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
                address = address.ipv4_mapped
            if address.is_unspecified or address.is_multicast:
                raise ValueError('invalid country proxy IP address')
            addresses.add(str(address))
        if len(addresses) > 16:
            raise ValueError('too many country proxy IP addresses')
        return ','.join(sorted(addresses))

    @field_validator(
        'service_revision',
        'ops_read_token',
        'postgres_private_dsn',
        'postgres_knowledge_dsn',
        'neo4j_uri',
        'neo4j_password',
        mode='before',
    )
    @classmethod
    def empty_is_unset(cls, value: object) -> object:
        return None if value in ('', None) else value

    @model_validator(mode='after')
    def fail_closed(self) -> Settings:
        if (
            self.official_help_enabled
            and self.ai_provider == 'openai'
            and (self.openai_model != 'gpt-6-luna' or self.openai_reasoning_effort != 'medium')
        ):
            raise ValueError('official help requires gpt-6-luna with medium reasoning')
        if self.telemetry_otlp_endpoint:
            if any(name.startswith('OTEL_') and value for name, value in os.environ.items()):
                raise ValueError(
                    'ambient OTEL configuration is unsupported; use explicit application telemetry settings'
                )
            parts = urlsplit(self.telemetry_otlp_endpoint)
            if (
                not self.observability_enabled
                or parts.scheme not in ('http', 'https')
                or not parts.hostname
                or parts.username
                or parts.password
                or parts.query
                or parts.fragment
                or parts.path != '/v1/traces'
            ):
                raise ValueError(
                    'OTLP requires enabled observability and an explicit safe /v1/traces endpoint'
                )
            if parts.scheme == 'http' and not (
                '.' not in parts.hostname or parts.hostname in ('localhost', '127.0.0.1', '::1')
            ):
                raise ValueError(
                    'plain HTTP OTLP is restricted to a private single-label service or loopback'
                )

        if self.ai_provider == 'openai' and not (self.allow_paid_ai and self.openai_api_key):
            raise ValueError('AI_PROVIDER=openai requires ALLOW_PAID_AI=true and OPENAI_API_KEY')
        if self.ai_provider == 'openai' and (
            self.openai_model != 'gpt-6-luna' or self.openai_reasoning_effort != 'medium'
        ):
            raise ValueError('OpenAI answers require gpt-6-luna with medium reasoning; no fallback')
        if self.ai_provider == 'fixture' and self.environment == 'production' and self.assistant_enabled:
            raise ValueError(
                'production cannot serve fixture answers; set AI_PROVIDER=openai or disable the assistant'
            )
        if self.daily_budget_usd > self.monthly_budget_usd:
            raise ValueError('DAILY_BUDGET_USD cannot exceed MONTHLY_BUDGET_USD')
        for origin in self.allowed_origins:
            parts = urlsplit(origin)
            if parts.scheme not in ('http', 'https') or not parts.hostname or parts.path or parts.query:
                raise ValueError('ALLOWED_ORIGINS entries must be bare origins like https://host')
        for cidr in self.trusted_proxy_cidrs:
            ipaddress.ip_network(cidr)
        if self.environment == 'production':
            if not self.session_cookie_secure:
                raise ValueError('production requires SESSION_COOKIE_SECURE=true')
            if any(
                urlsplit(o).scheme != 'https' or urlsplit(o).hostname in ('localhost', '127.0.0.1')
                for o in self.allowed_origins
            ):
                raise ValueError('production ALLOWED_ORIGINS must be https and not localhost')
            if self.ops_read_token is not None and len(self.ops_read_token.get_secret_value()) < 32:
                raise ValueError('OPS_READ_TOKEN must be at least 32 characters')
            key = self.client_hash_key.get_secret_value()
            if key == DEV_CLIENT_HASH_KEY or len(key) < 32:
                raise ValueError('production requires a CLIENT_HASH_KEY of at least 32 characters')
            if (
                self.assistant_enabled
                and self.ai_provider == 'openai'
                and (self.application_storage != 'postgres' or self.knowledge_backend != 'graphrag')
            ):
                raise ValueError('production answers require PostgreSQL application storage and GraphRAG')
        if self.product_analytics_country_enabled and not self.product_analytics_country_proxy_ips:
            raise ValueError('country attribution requires exact trusted proxy IP addresses')
        if self.product_analytics_enabled and self.application_storage != 'postgres':
            raise ValueError('product analytics requires PostgreSQL application storage')
        if self.application_storage == 'postgres' and self.postgres_private_dsn is None:
            raise ValueError('PostgreSQL application storage requires POSTGRES_PRIVATE_DSN')
        if self.knowledge_backend == 'graphrag' and not (
            self.postgres_knowledge_dsn and self.neo4j_uri and self.neo4j_password
        ):
            raise ValueError('GraphRAG requires explicit PostgreSQL and authenticated Neo4j configuration')
        if (self.application_storage == 'postgres') != (self.knowledge_backend == 'graphrag'):
            raise ValueError('PostgreSQL application storage and GraphRAG must be selected together')
        for dsn in (self.postgres_private_dsn, self.postgres_knowledge_dsn):
            if dsn is not None:
                parts = urlsplit(dsn.get_secret_value())
                if parts.scheme not in ('postgres', 'postgresql') or not parts.hostname or not parts.path:
                    raise ValueError('PostgreSQL DSNs must be explicit database URIs')
        if self.neo4j_uri:
            parts = urlsplit(self.neo4j_uri)
            if (
                parts.scheme not in ('bolt', 'bolt+s', 'neo4j', 'neo4j+s')
                or not parts.hostname
                or parts.username is not None
                or parts.password is not None
                or parts.path not in ('', '/')
                or parts.query
                or parts.fragment
            ):
                raise ValueError('Neo4j requires a bare Bolt URI; credentials use private fields')
        return self

    @property
    def cookie_name(self) -> str:
        return '__Host-pv_assistant' if self.session_cookie_secure else 'pv_assistant_dev'


@lru_cache
def get_settings() -> Settings:
    return Settings()
