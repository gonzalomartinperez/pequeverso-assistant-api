"""Spend policy in integer micro-dollars (1 USD = 1_000_000 µUSD).

A run reserves its worst-case cost before the provider is called and settles to the reported
usage afterwards. A missing usage report keeps the reservation: absence never implies a refund.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

MICRO = Decimal(1_000_000)
PER_MILLION = Decimal(1_000_000)


def to_micro(usd: Decimal) -> int:
    return int((usd * MICRO).to_integral_value(rounding=ROUND_CEILING))


def from_micro(micro: int) -> Decimal:
    return Decimal(micro) / MICRO


@dataclass(frozen=True, slots=True)
class Pricing:
    """USD per one million tokens."""

    input: Decimal
    cached_input: Decimal
    cache_write: Decimal
    output: Decimal

    def __post_init__(self) -> None:
        for name in ('input', 'cached_input', 'cache_write', 'output'):
            value = getattr(self, name)
            if not value.is_finite() or value < 0:
                raise ValueError(f'pricing.{name} must be a finite, non-negative amount')


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0

    def __post_init__(self) -> None:
        if min(self.input_tokens, self.output_tokens, self.cached_input_tokens, self.cache_write_tokens) < 0:
            raise ValueError('token counts cannot be negative')
        if self.cached_input_tokens + self.cache_write_tokens > self.input_tokens:
            raise ValueError('cached and cache-write tokens are part of the input tokens')


def cost_micro(usage: Usage, pricing: Pricing) -> int:
    uncached = usage.input_tokens - usage.cached_input_tokens - usage.cache_write_tokens
    usd = (
        Decimal(uncached) * pricing.input
        + Decimal(usage.cached_input_tokens) * pricing.cached_input
        + Decimal(usage.cache_write_tokens) * pricing.cache_write
        + Decimal(usage.output_tokens) * pricing.output
    ) / PER_MILLION
    return to_micro(usd)


def worst_case_micro(max_input_tokens: int, max_output_tokens: int, pricing: Pricing) -> int:
    """Upper bound of one call: every input token at the most expensive input rate."""
    input_rate = max(pricing.input, pricing.cache_write)
    usd = (Decimal(max_input_tokens) * input_rate + Decimal(max_output_tokens) * pricing.output) / PER_MILLION
    return to_micro(usd)


@dataclass(frozen=True, slots=True)
class BudgetPolicy:
    monthly_limit_micro: int
    safety_margin: Decimal
    daily_limit_micro: int

    def __post_init__(self) -> None:
        if self.monthly_limit_micro <= 0 or self.daily_limit_micro <= 0:
            raise ValueError('budget limits must be positive')
        if not Decimal(0) <= self.safety_margin < Decimal(1):
            raise ValueError('safety margin must be in [0, 1)')

    @property
    def monthly_cutoff_micro(self) -> int:
        return int(Decimal(self.monthly_limit_micro) * (Decimal(1) - self.safety_margin))

    @property
    def daily_cutoff_micro(self) -> int:
        return min(self.daily_limit_micro, self.monthly_cutoff_micro)

    def allows(self, *, month_spent: int, day_spent: int, reservation: int) -> bool:
        return (
            month_spent + reservation <= self.monthly_cutoff_micro
            and day_spent + reservation <= self.daily_cutoff_micro
        )
