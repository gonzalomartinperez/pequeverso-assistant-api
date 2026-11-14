"""Amount parsing across display formats."""

from decimal import Decimal

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from app.domain.answer_policy import _amount


@given(cents=st.integers(0, 99_999_999))
@example(cents=129900)
def test_plain_amount_round_trip(cents):
    """Row 1: plain dot/comma decimal formats preserve exact cents."""
    amount = Decimal(cents) / 100
    plain = f"{amount:.2f}"
    assert _amount(plain) == amount
    assert _amount(plain.replace(".", ",")) == amount


@pytest.mark.xfail(
    strict=True, reason="_amount rejects grouped es-ES/en amounts such as 1.299,00 and 1,299.00"
)
@given(cents=st.integers(100_000, 99_999_999))
@example(cents=129900)
def test_grouped_amount_round_trip(cents):
    """Row 1: grouped es-ES and English displays should preserve exact cents."""
    amount = Decimal(cents) / 100
    english = f"{amount:,.2f}"
    spanish = english.translate(str.maketrans({",": ".", ".": ","}))
    for display in (spanish, english):
        assert _amount(display) == amount
