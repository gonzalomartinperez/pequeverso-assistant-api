"""Public rejection codes and retry semantics."""

import pytest

from app.domain.errors import RETRYABLE, FailureCode, RejectedError


@pytest.mark.parametrize(
    ("code", "retryable"),
    [
        ("invalid_request", False),
        ("origin_denied", False),
        ("csrf_failed", False),
        ("session_expired", False),
        ("rate_limited", False),
        ("busy", True),
        ("run_in_progress", False),
        ("idempotency_conflict", False),
        ("run_not_found", False),
        ("budget_exhausted", False),
        ("assistant_disabled", False),
        ("catalog_unavailable", True),
        ("provider_unavailable", True),
        ("generation_failed", True),
        ("timeout", True),
        ("dependency_unavailable", True),
    ],
)
def test_rejection_preserves_the_public_code_and_retry_classification(code, retryable):
    public_code = FailureCode(code)
    error = RejectedError(public_code)
    assert str(error) == code
    assert error.code is public_code
    assert (error.code in RETRYABLE) is retryable
