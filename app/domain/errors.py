"""Public failure codes. Every code is safe to show to a visitor and to log."""

from __future__ import annotations

from enum import StrEnum


class FailureCode(StrEnum):
    INVALID_REQUEST = 'invalid_request'
    ORIGIN_DENIED = 'origin_denied'
    CSRF_FAILED = 'csrf_failed'
    SESSION_EXPIRED = 'session_expired'
    RATE_LIMITED = 'rate_limited'
    BUSY = 'busy'
    RUN_IN_PROGRESS = 'run_in_progress'
    IDEMPOTENCY_CONFLICT = 'idempotency_conflict'
    RUN_NOT_FOUND = 'run_not_found'
    BUDGET_EXHAUSTED = 'budget_exhausted'
    ASSISTANT_DISABLED = 'assistant_disabled'
    CATALOG_UNAVAILABLE = 'catalog_unavailable'
    PROVIDER_UNAVAILABLE = 'provider_unavailable'
    GENERATION_FAILED = 'generation_failed'
    TIMEOUT = 'timeout'
    DEPENDENCY_UNAVAILABLE = 'dependency_unavailable'


RETRYABLE = frozenset(
    {
        FailureCode.BUSY,
        FailureCode.PROVIDER_UNAVAILABLE,
        FailureCode.GENERATION_FAILED,
        FailureCode.TIMEOUT,
        FailureCode.DEPENDENCY_UNAVAILABLE,
        FailureCode.CATALOG_UNAVAILABLE,
    }
)


class RejectedError(Exception):
    """A request refused for a public, documented reason."""

    def __init__(self, code: FailureCode) -> None:
        super().__init__(code.value)
        self.code = code
