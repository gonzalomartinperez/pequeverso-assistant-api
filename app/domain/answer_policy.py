"""Deterministic checks on a completed answer. The system prompt is guidance; these rules are the
boundary: an answer that breaks one is replaced before it is stored or presented as final.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from urllib.parse import urlsplit, urlunsplit


class Violation(StrEnum):
    UNLISTED_URL = 'unlisted_url'
    UNLISTED_EMAIL = 'unlisted_email'
    UNKNOWN_PRICE = 'unknown_price'
    UNVERIFIED_PRICE = 'unverified_price'
    DISCOUNT_CLAIM = 'discount_claim'
    FORBIDDEN_TERM = 'forbidden_term'
    PRESSURE_CLAIM = 'pressure_claim'
    PAYMENT_DATA_REQUEST = 'payment_data_request'
    UNAUTHORIZED_ACTION_CLAIM = 'unauthorized_action_claim'
    UNSUPPORTED_OUTCOME_CLAIM = 'unsupported_outcome_claim'


_URL = re.compile(
    r'(?:https?://|www\.)[^\s)>\]]+|\b(?:[a-z0-9-]+\.)+(?:com|net|org|io|ar|es|mx|co|br|ai|app|link|ly)\b(?:/[^\s)>\]]*)?',
    re.IGNORECASE,
)
_EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
_NUMBER = r'[+-]?[0-9](?:[0-9.,_]*[0-9])?(?:[eE][+-]?[0-9]+)?'
_CURRENCY = r'US\$|U\$S|R\$|USD|EUR|ARS|MXN|BRL|GBP|JPY|CLP|COP|PEN|UYU|CHF|CAD|AUD|\$|€|£|¥'
_CURRENCY_SUFFIX = rf'{_CURRENCY}|d[oó]lares|dollars|euros|pesos|reales|yen|pounds|libras'
_MONEY = re.compile(
    rf'(?P<prefix>{_CURRENCY})\s*(?P<a>{_NUMBER})'
    rf'(?:\s*(?P<trailing>{_CURRENCY_SUFFIX})(?![A-Za-z]))?'
    rf'|(?P<b>{_NUMBER})\s*(?P<suffix>{_CURRENCY_SUFFIX})(?![A-Za-z])',
    re.IGNORECASE,
)
_DECIMAL_PRICE = re.compile(r'[0-9]{1,6}(?:[.,][0-9]{1,2})?\Z')
_DISCOUNT = re.compile(
    r'\b(?:c[oó]digo|cup[oó]n)\s+(?:de\s+descuento\s+)?["“]?[A-Z0-9]{4,}\b'
    r'|\d{1,2}\s?%\s?(?:de\s+)?(?:descuento|off|rebaja)'
    r'|(?:descuento|rebaja)\s+(?:del?\s+)?\d{1,2}\s?%'
    r'|\b(?:discount|promo|coupon)\s+code\b'
    r'|\d{1,2}\s?%\s?(?:discount|off)\b',
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
    'last units',
    'only today',
    'today only',
    'offer ends',
    'selling out',
    'before it sells out',
    'best seller',
    'best-selling',
    'thousands of families',
    'hundreds of families',
)
_PAYMENT_REQUEST = re.compile(
    r'\b(?:env[ií]a(?:me)?|escrib[ei](?:me)?|comparte|dime|indica(?:me)?|pasa(?:me)?)\b[^.?!]{0,40}'
    r'\b(?:tarjeta|cvv|cvc|n[uú]mero de (?:la )?tarjeta|contraseña|clave)\b',
    re.IGNORECASE,
)
_PAYMENT_REQUEST_EN = re.compile(
    r'\b(?:send|give|share|tell|type|write)\b[^.?!]{0,40}\b(?:card number|credit card|debit card|cvv|cvc|password)\b',
    re.IGNORECASE,
)

# These bounded positive-claim recognizers protect common failure modes, not all semantic
# assertions. Published instructions and explicit refusals remain valid; no tool can execute
# the transactions described below. General citation entailment still needs quality review.
_ACTION_CLAIM = re.compile(
    r'\b(?:he|hemos)\s+(?:ya\s+)?(?:procesado|emitido|realizado|enviado|modificado|cancelado|'
    r'reservado|comprado|cobrado|devuelto|reembolsado)\b[^.!?;\n]{0,60}?'
    r'\b(?:reembolso|devoluci[oó]n|pedido|compra|dinero|pago|tarjeta|reserva|correo|mensaje)\b'
    r'|\b(?:procesé|reembolsé|devolví|cobré|reservé|compré|envié|modifiqué|cancelé|pagué)\b'
    r'[^.!?;\n]{0,60}?\b(?:reembolso|devoluci[oó]n|pedido|compra|dinero|pago|tarjeta|reserva|correo|mensaje)\b'
    r'|\b(?:ya|yo)\s+(?:procese|reembolse|devolvi|cobre|reserve|compre|envie|modifique|cancele|pague)\b'
    r'[^.!?;\n]{0,60}?\b(?:reembolso|devoluci[oó]n|pedido|compra|dinero|pago|tarjeta|reserva|correo|mensaje)\b'
    r'|\b(?:i|we)\s+(?:(?:have|already|just)\s+)*(?:processed|issued|sent|refunded|charged|'
    r'purchased|reserved|cancelled|canceled|modified|updated|placed)\b[^.!?;\n]{0,60}?'
    r'\b(?:refund|money|order|payment|card|purchase|booking|reservation|email|message)\b'
    r'|\b(?:he|hemos)\s+(?:ya\s+)?reembolsado\b'
    r'|\b(?:i|we)\s+(?:(?:have|already|just)\s+)*refunded\b',
    re.IGNORECASE,
)
_OUTCOME_CLAIM = re.compile(
    r'\b(?:garantiza(?:mos|n)?|garantizado|garantizada|asegura(?:mos|n)?|guarantees?|'
    r'guaranteed|ensures?|will certainly|definitely)\b[^.!?;\n]{0,100}?'
    r'\b(?:leer|lectura|escribir|aprend\w*|read(?:ing)?|learn\w*|cure|curar|trat\w*)\b'
    r'|\b(?:aprendera(?:n)?|will learn|will be reading)\b[^.!?;\n]{0,50}?'
    r'\b(?:en|in|within|after)\s+(?:\w+\s+){0,3}(?:dias?|days?|semanas?|weeks?|meses?|months?)\b'
    r'|\b(?:cura|cures?|trata|treats?)\b[^.!?;\n]{0,50}?'
    r'\b(?:dislexia|dyslexia|tdah|adhd|autismo|autism|trastorno|disorder)\b'
)
_NEGATED_CLAIM_PREFIX = re.compile(
    r"(?:\bno|\bnunca|\bnot|\bnever|\bcannot|\bcan't|\bdidn't|\bhaven't|\bunable to)"
    r'\s+(?:\w+\s+){0,5}$'
)
_CONDITIONAL_CLAIM_PREFIX = re.compile(r'\b(?:si|if|cuando|when)\s+(?:\w+\s+){0,5}$')


def fold(text: str) -> str:
    """Lowercase, accent-free form used for term matching."""
    decomposed = unicodedata.normalize('NFKD', text.lower())
    return ''.join(char for char in decomposed if not unicodedata.combining(char))


def _url_key(candidate: str) -> str | None:
    """Compare exact authorized paths, queries and fragments, never a host wildcard.

    Bare domains use https for prose like 'consumer.hotmart.com'. Sentence punctuation and
    host casing are normalized; encoded paths, extra parameters and userinfo are not aliases.
    """
    candidate = candidate.rstrip('.,;:!?\'"”')
    if not re.match(r'^https?://', candidate, re.IGNORECASE):
        candidate = f'https://{candidate}'
    try:
        parts = urlsplit(candidate)
        if parts.scheme.lower() != 'https' or not parts.hostname or parts.username or parts.password:
            return None
        if parts.port is not None:
            return None
    except ValueError:
        return None
    return urlunsplit(('https', parts.hostname.lower(), parts.path or '/', parts.query, parts.fragment))


def _amount(raw: str) -> Decimal | None:
    # Match the complete numeric token. A prefix of '14,990' must not become 14.99; grouped,
    # scientific, signed and over-precision formats are not authoritative catalog displays.
    if not _DECIMAL_PRICE.fullmatch(raw):
        return None
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
    allowed_urls: frozenset[str] = frozenset()
    known_price_pairs: frozenset[tuple[Decimal, str]] = frozenset()


def check_answer(text: str, rules: AnswerRules) -> list[Violation]:
    violations: list[Violation] = []
    emails = {match.group().lower() for match in _EMAIL.finditer(text)}
    if emails - {email.lower() for email in rules.allowed_emails}:
        violations.append(Violation.UNLISTED_EMAIL)
    without_emails = _EMAIL.sub(' ', text)
    urls = {_url_key(match.group()) for match in _URL.finditer(without_emails)}
    allowed_urls = {_url_key(url) for url in rules.allowed_urls}
    if None in urls or any(url not in allowed_urls for url in urls):
        violations.append(Violation.UNLISTED_URL)
    prices: list[tuple[Decimal | None, str]] = []
    for match in _MONEY.finditer(text):
        amount = _amount(match.group('a') or match.group('b'))
        currency = _currency(match.group('prefix') or match.group('suffix'))
        if match.group('trailing') and _currency(match.group('trailing')) != currency:
            amount = None
        prices.append((amount, currency))
    if prices:
        if not rules.prices_verified:
            violations.append(Violation.UNVERIFIED_PRICE)
        elif any(
            amount is None or (amount, currency) not in rules.known_price_pairs for amount, currency in prices
        ):
            violations.append(Violation.UNKNOWN_PRICE)
    if _DISCOUNT.search(text):
        violations.append(Violation.DISCOUNT_CLAIM)
    folded = fold(text)
    if any(fold(term) in folded for term in rules.forbidden_terms):
        violations.append(Violation.FORBIDDEN_TERM)
    if any(phrase in folded for phrase in _PRESSURE):
        violations.append(Violation.PRESSURE_CLAIM)
    if _PAYMENT_REQUEST.search(text) or _PAYMENT_REQUEST_EN.search(text):
        violations.append(Violation.PAYMENT_DATA_REQUEST)
    if _positive_claim(_ACTION_CLAIM, text):
        violations.append(Violation.UNAUTHORIZED_ACTION_CLAIM)
    if _positive_claim(_OUTCOME_CLAIM, folded):
        violations.append(Violation.UNSUPPORTED_OUTCOME_CLAIM)
    return violations


def _currency(raw: str) -> str:
    folded = fold(raw)
    if folded in {'us$', 'u$s', 'usd', '$', 'dolares', 'dollars'}:
        return 'USD'
    if folded in {'eur', '€', 'euros'}:
        return 'EUR'
    if folded in {'brl', 'r$', 'reales'}:
        return 'BRL'
    if folded in {'gbp', '£', 'pounds', 'libras'}:
        return 'GBP'
    if folded in {'jpy', '¥', 'yen'}:
        return 'JPY'
    return folded.upper()


def _positive_claim(pattern: re.Pattern[str], text: str) -> bool:
    for match in pattern.finditer(text):
        prefix = fold(text[max(0, match.start() - 100) : match.start()])
        # A negation in a previous sentence/contrast must not hide a new positive claim.
        prefix = re.split(r'[.!?;,\n]|\b(?:pero|but|however|sin embargo|and|y)\b', prefix)[-1]
        if not _NEGATED_CLAIM_PREFIX.search(prefix) and not _CONDITIONAL_CLAIM_PREFIX.search(prefix):
            return True
    return False
