"""Runtime configuration (environment variables, optional `.env.local`). Fails closed: paid
providers need explicit opt-in, production needs https origins, secure cookies and real secrets.
"""

from __future__ import annotations

import ipaddress
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
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
    openai_reasoning_effort: Literal['none', 'low', 'medium'] = 'low'
    openai_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    openai_max_retries: int = Field(default=1, ge=0, le=2)
    fixture_chunk_delay_ms: int = Field(default=0, ge=0, le=2000)

    # Pricing in USD per 1M tokens (gpt-6-luna list prices, read 2026-09-27).
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
    max_output_tokens: int = Field(default=1200, ge=200, le=4000)
    max_input_tokens: int = Field(default=24000, ge=4000, le=100000)
    max_evidence_chars: int = Field(default=40000, ge=4000, le=200000)
    history_messages: int = Field(default=12, ge=0, le=40)
    messages_per_session_per_day: int = Field(default=30, ge=1)
    messages_per_client_per_hour: int = Field(default=60, ge=1)
    sessions_per_client_per_hour: int = Field(default=20, ge=1)
    max_concurrent_runs: int = Field(default=4, ge=1, le=64)
    run_timeout_seconds: float = Field(default=45.0, gt=0, le=180)
    heartbeat_seconds: float = Field(default=15.0, gt=0, le=60)
    max_body_bytes: int = Field(default=16 * 1024, ge=1024, le=256 * 1024)

    # Sessions and browser policy.
    session_retention_hours: int = Field(default=24, ge=1, le=24 * 30)
    session_cookie_secure: bool = False
    session_cookie_samesite: Literal['lax', 'strict'] = 'lax'
    allowed_origins: list[str] = ['http://localhost:3000', 'http://127.0.0.1:3000']
    trusted_proxy_cidrs: list[str] = []
    client_hash_key: SecretStr = SecretStr(DEV_CLIENT_HASH_KEY)

    # Catalog.
    catalog_url: str | None = None
    catalog_file: Path = DEFAULT_CATALOG
    catalog_allowed_hosts: list[str] = ['pequeverso.com', 'consumer.hotmart.com', 'refund.hotmart.com']
    catalog_refresh_seconds: int = Field(default=900, ge=60)
    catalog_price_max_age_hours: int = Field(default=168, ge=1, le=24 * 60)

    database_path: str = str(ROOT / 'data' / 'assistant.sqlite3')

    @model_validator(mode='after')
    def fail_closed(self) -> Settings:
        if self.ai_provider == 'openai' and not (self.allow_paid_ai and self.openai_api_key):
            raise ValueError('AI_PROVIDER=openai requires ALLOW_PAID_AI=true and OPENAI_API_KEY')
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
            key = self.client_hash_key.get_secret_value()
            if key == DEV_CLIENT_HASH_KEY or len(key) < 32:
                raise ValueError('production requires a CLIENT_HASH_KEY of at least 32 characters')
        return self

    @property
    def cookie_name(self) -> str:
        return '__Host-pv_assistant' if self.session_cookie_secure else 'pv_assistant_dev'


@lru_cache
def get_settings() -> Settings:
    return Settings()
