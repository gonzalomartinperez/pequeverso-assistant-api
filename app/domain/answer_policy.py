"""Deterministic checks on a completed answer. The system prompt is guidance; these rules are the
boundary: an answer that breaks one is replaced before it is stored or presented as final.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum


class Violation(StrEnum):
    UNLISTED_URL = 'unlisted_url'
    UNLISTED_EMAIL = 'unlisted_email'
    UNKNOWN_PRICE = 'unknown_price'
    UNVERIFIED_PRICE = 'unverified_price'
    DISCOUNT_CLAIM = 'discount_claim'
    FORBIDDEN_TERM = 'forbidden_term'
    PRESSURE_CLAIM = 'pressure_claim'
    PAYMENT_DATA_REQUEST = 'payment_data_request'


_URL = re.compile(
    r'(?:https?://|www\.)[^\s)>\]]+|\b(?:[a-z0-9-]+\.)+(?:com|net|org|io|ar|es|mx|co|br|ai|app|link|ly)\b(?:/[^\s)>\]]*)?',
    re.IGNORECASE,
)
_EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
_MONEY = re.compile(
    r'(?:US\$|U\$S|USD|\$|€|R\$)\s?(?P<a>\d{1,6}(?:[.,]\d{1,2})?)'
    r'|(?P<b>\d{1,6}(?:[.,]\d{1,2})?)\s?(?:US\$|USD|d[oó]lares|euros|pesos|reales)',
    re.IGNORECASE,
)
_DISCOUNT = re.compile(
    r'\b(?:c[oó]digo|cup[oó]n)\s+(?:de\s+descuento\s+)?["“]?[A-Z0-9]{4,}\b'
    r'|\d{1,2}\s?%\s?(?:de\s+)?(?:descuento|off|rebaja)'
    r'|(?:descuento|rebaja)\s+(?:del?\s+)?\d{1,2}\s?%',
    re.IGNORECASE,
)
_PRESSURE = (
    'ultimas unidades',
    'ultimos cupos',
    'solo por hoy',
    'solo hoy',
    'oferta termina',
    'quedan pocas',
    'quedan pocos',
    'antes de que se agote',
    'el mas vendido',
    'miles de familias',
    'cientos de familias',
)
_PAYMENT_REQUEST = re.compile(
    r'\b(?:env[ií]a(?:me)?|escrib[ei](?:me)?|comparte|dime|indica(?:me)?|pasa(?:me)?)\b[^.?!]{0,40}'
    r'\b(?:tarjeta|cvv|cvc|n[uú]mero de (?:la )?tarjeta|contraseña|clave)\b',
    re.IGNORECASE,
)


def fold(text: str) -> str:
    """Lowercase, accent-free form used for term matching."""
    decomposed = unicodedata.normalize('NFKD', text.lower())
    return ''.join(char for char in decomposed if not unicodedata.combining(char))


def _host(candidate: str) -> str:
    stripped = re.sub(r'^(?:https?://)', '', candidate, flags=re.IGNORECASE)
    return stripped.split('/', 1)[0].split('?', 1)[0].lower().rstrip('.,;:')


def _amount(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(',', '.'))
    except InvalidOperation:
        return None


@dataclass(frozen=True, slots=True)
class AnswerRules:
    allowed_hosts: frozenset[str]
    allowed_emails: frozenset[str]
    known_prices: frozenset[Decimal]
    prices_verified: bool
    forbidden_terms: tuple[str, ...]


def check_answer(text: str, rules: AnswerRules) -> list[Violation]:
    violations: list[Violation] = []
    emails = {match.group().lower() for match in _EMAIL.finditer(text)}
    if emails - {email.lower() for email in rules.allowed_emails}:
        violations.append(Violation.UNLISTED_EMAIL)
    without_emails = _EMAIL.sub(' ', text)
    hosts = {_host(match.group()) for match in _URL.finditer(without_emails)}
    if any(not _host_allowed(host, rules.allowed_hosts) for host in hosts):
        violations.append(Violation.UNLISTED_URL)
    amounts = [_amount(m.group('a') or m.group('b')) for m in _MONEY.finditer(text)]
    if amounts:
        if not rules.prices_verified:
            violations.append(Violation.UNVERIFIED_PRICE)
        elif any(amount is None or amount not in rules.known_prices for amount in amounts):
            violations.append(Violation.UNKNOWN_PRICE)
    if _DISCOUNT.search(text):
        violations.append(Violation.DISCOUNT_CLAIM)
    folded = fold(text)
    if any(fold(term) in folded for term in rules.forbidden_terms):
        violations.append(Violation.FORBIDDEN_TERM)
    if any(phrase in folded for phrase in _PRESSURE):
        violations.append(Violation.PRESSURE_CLAIM)
    if _PAYMENT_REQUEST.search(text):
        violations.append(Violation.PAYMENT_DATA_REQUEST)
    return violations


def _host_allowed(host: str, allowed: Iterable[str]) -> bool:
    return host in allowed
