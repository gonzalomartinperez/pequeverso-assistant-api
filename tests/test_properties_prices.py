"""Answer price grounding."""

from decimal import Decimal

from hypothesis import example, given
from hypothesis import strategies as st

from app.domain.answer_policy import AnswerRules, Violation, check_answer


@given(
    cents=st.integers(0, 99_999_999),
    currency=st.sampled_from(["USD", "EUR", "ARS", "MXN"]),
    prefix=st.text(alphabet="abc áñ!?\n", max_size=40),
    suffix=st.text(alphabet="xyz éú!?\n", max_size=40),
)
@example(cents=1499, currency="EUR", prefix="Precio: ", suffix=".")
def test_unknown_price_pair_is_rejected(cents, currency, prefix, suffix):
    """Row 2: even known amounts in an unlisted currency cannot pass grounding."""
    amount = Decimal(cents) / 100
    other = "USD" if currency != "USD" else "EUR"
    pairs = frozenset({(amount, other), (amount + 1, currency)})
    rules = AnswerRules(
        frozenset(), frozenset(), frozenset({amount, amount + 1}), True, (), known_price_pairs=pairs
    )
    assert (amount, currency) not in pairs
    assert Violation.UNKNOWN_PRICE in check_answer(
        f"{prefix} {amount:.2f} {currency} {suffix}", rules
    )


@given(cents=st.integers(1, 99_999_999), currency=st.sampled_from(["USD", "EUR", "ARS", "MXN"]))
@example(cents=1499, currency="USD")
def test_listed_price_pair_is_accepted_and_unknown_amount_rejected(cents, currency):
    """Row 2 positive control: the listed pair passes; the same currency with another amount fails."""
    amount = Decimal(cents) / 100
    rules = AnswerRules(
        frozenset(),
        frozenset(),
        frozenset({amount}),
        True,
        (),
        known_price_pairs=frozenset({(amount, currency)}),
    )
    assert Violation.UNKNOWN_PRICE not in check_answer(f"Cuesta {amount:.2f} {currency}.", rules)
    assert Violation.UNKNOWN_PRICE in check_answer(f"Cuesta {amount + 1:.2f} {currency}.", rules)
