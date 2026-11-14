"""Amount parsing across display formats."""

from decimal import Decimal

from hypothesis import example, given
from hypothesis import strategies as st

from app.domain.answer_policy import AnswerRules, Violation, _amount, check_answer


@given(cents=st.integers(0, 99_999_999))
@example(cents=129900)
def test_plain_amount_round_trip(cents):
    """Row 1: plain dot/comma decimal formats preserve exact cents."""
    amount = Decimal(cents) / 100
    plain = f"{amount:.2f}"
    assert _amount(plain) == amount
    assert _amount(plain.replace(".", ",")) == amount


@given(cents=st.integers(100_000, 99_999_999))
@example(cents=129900)
def test_grouped_amounts_are_not_authoritative_and_fail_closed(cents):
    """Row 1 (current contract): grouped displays (1.299,00 / 1,299.00) are not parsed.

    `_amount` documents grouped formats as non-authoritative catalog displays, so a grouped price
    is never accepted as grounded: the answer is replaced (a false rejection, never a false
    acceptance). Revisit if the catalog ever lists prices of 1000 or more.
    """
    amount = Decimal(cents) / 100
    english = f"{amount:,.2f}"
    spanish = english.translate(str.maketrans({",": ".", ".": ","}))
    rules = AnswerRules(
        frozenset(),
        frozenset(),
        frozenset({amount}),
        True,
        (),
        known_price_pairs=frozenset({(amount, "EUR")}),
    )
    for display in (spanish, english):
        assert _amount(display) is None
        assert Violation.UNKNOWN_PRICE in check_answer(f"Cuesta {display} EUR.", rules)
