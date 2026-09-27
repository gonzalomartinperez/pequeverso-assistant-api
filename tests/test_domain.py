from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.answer_policy import AnswerRules, Violation, check_answer
from app.domain.budget import BudgetPolicy, Pricing, Usage, cost_micro, to_micro, worst_case_micro
from app.domain.catalog import ActiveCatalog, PriceStatus
from app.domain.redaction import contains_card_number, redact_contact_data

LUNA = Pricing(Decimal('0.10'), Decimal('0.01'), Decimal('0.125'), Decimal('0.50'))
RULES = AnswerRules(
    allowed_hosts=frozenset({'pequeverso.com', 'consumer.hotmart.com', 'refund.hotmart.com'}),
    allowed_emails=frozenset({'somospequeverso@gmail.com'}),
    known_prices=frozenset({Decimal('14.99')}),
    prices_verified=True,
    forbidden_terms=('Pack Imprime y Juega', 'Imprime y Juega'),
)


def test_cost_distinguishes_cached_and_cache_write_tokens() -> None:
    usage = Usage(
        input_tokens=10_000, output_tokens=1_000, cached_input_tokens=6_000, cache_write_tokens=2_000
    )
    # 2000*0.10 + 6000*0.01 + 2000*0.125 + 1000*0.50 = 200+60+250+500 = 1010 per 1M → 0.00101 USD
    assert cost_micro(usage, LUNA) == 1010


def test_worst_case_bounds_any_real_usage() -> None:
    bound = worst_case_micro(24_000, 1_200, LUNA)
    for cached in (0, 12_000, 24_000):
        usage = Usage(24_000, 1_200, cached_input_tokens=cached, cache_write_tokens=24_000 - cached)
        assert cost_micro(usage, LUNA) <= bound


def test_usage_rejects_inconsistent_counts() -> None:
    with pytest.raises(ValueError, match='part of the input'):
        Usage(input_tokens=10, output_tokens=1, cached_input_tokens=11)


def test_budget_policy_applies_margin_and_daily_cap() -> None:
    policy = BudgetPolicy(to_micro(Decimal(10)), Decimal('0.10'), to_micro(Decimal(1)))
    assert policy.monthly_cutoff_micro == 9_000_000
    assert policy.allows(month_spent=0, day_spent=999_000, reservation=1_000)
    assert not policy.allows(month_spent=0, day_spent=999_001, reservation=1_000)
    assert not policy.allows(month_spent=8_999_500, day_spent=0, reservation=1_000)


@pytest.mark.parametrize(
    ('text', 'expected'),
    [
        ('mi tarjeta es 4111 1111 1111 1111', True),
        ('4111-1111-1111-1111', True),
        ('4111 1111 1111 1112', False),  # fails Luhn
        ('el kit tiene 414 páginas y 9 PDF', False),
        ('mi pedido HP1234567890123', False),
    ],
)
def test_card_numbers_are_detected_with_luhn(text: str, expected: bool) -> None:
    assert contains_card_number(text) is expected


def test_contact_data_is_redacted() -> None:
    redacted = redact_contact_data('Escríbanme a ana.perez@example.com o al +54 9 291 555-1234, gracias')
    assert 'example.com' not in redacted.text and '555' not in redacted.text
    assert redacted.redactions == 2
    assert redact_contact_data('Mi hijo tiene 5 años y quiere 10 minutos').redactions == 0


@pytest.mark.parametrize(
    ('answer', 'violation'),
    [
        ('Cuesta US$14,99 y Hotmart lo convierte a tu moneda.', None),
        ('Cuesta US$9,99 por tiempo limitado.', Violation.UNKNOWN_PRICE),
        ('Usa el código PEQUE20 para un descuento.', Violation.DISCOUNT_CLAIM),
        ('Hoy tiene 30% de descuento.', Violation.DISCOUNT_CLAIM),
        ('Mira https://evil.example/pago para pagar.', Violation.UNLISTED_URL),
        ('Entra en consumer.hotmart.com con tu correo.', None),
        ('Escribe a ventas@otra-tienda.com.', Violation.UNLISTED_EMAIL),
        ('Escríbenos a somospequeverso@gmail.com.', None),
        ('También está el Pack Imprime y Juega.', Violation.FORBIDDEN_TERM),
        ('¡Últimas unidades, solo por hoy!', Violation.PRESSURE_CLAIM),
        ('Envíame el número de tu tarjeta y lo proceso.', Violation.PAYMENT_DATA_REQUEST),
        ('Es 100% digital: no se envía nada físico.', None),
    ],
)
def test_answer_rules(answer: str, violation: Violation | None) -> None:
    violations = check_answer(answer, RULES)
    assert violations == ([] if violation is None else [violation])


def test_unverified_prices_cannot_be_quoted() -> None:
    rules = AnswerRules(RULES.allowed_hosts, RULES.allowed_emails, RULES.known_prices, False, ())
    assert check_answer('Cuesta US$14,99.', rules) == [Violation.UNVERIFIED_PRICE]
    assert check_answer('El precio actual está en la página del kit.', rules) == []


def test_price_status_follows_verification_age() -> None:
    verified = datetime(2026, 9, 27, tzinfo=UTC)
    active = ActiveCatalog(catalog=None, sha256='x', verified_at=verified, max_price_age=timedelta(hours=168))  # type: ignore[arg-type]
    assert active.price_status(verified + timedelta(days=6)) is PriceStatus.VERIFIED
    assert active.price_status(verified + timedelta(days=8)) is PriceStatus.UNVERIFIED
