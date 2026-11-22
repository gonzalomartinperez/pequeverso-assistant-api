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
    UNLISTED_URL = "unlisted_url"
    UNLISTED_EMAIL = "unlisted_email"
    UNKNOWN_PRICE = "unknown_price"
    UNVERIFIED_PRICE = "unverified_price"
    DISCOUNT_CLAIM = "discount_claim"
    FORBIDDEN_TERM = "forbidden_term"
    PRESSURE_CLAIM = "pressure_claim"
    PAYMENT_DATA_REQUEST = "payment_data_request"
    UNAUTHORIZED_ACTION_CLAIM = "unauthorized_action_claim"
    UNSUPPORTED_OUTCOME_CLAIM = "unsupported_outcome_claim"
    UNSUPPORTED_POLICY_CLAIM = "unsupported_policy_claim"
    UNSUPPORTED_PAGE_CLAIM = "unsupported_page_claim"
    UNSUPPORTED_GUARANTEE_CLAIM = "unsupported_guarantee_claim"


_URL = re.compile(
    r"(?:https?://|www\.)[^\s)>\]]+|\b(?:[a-z0-9-]+\.)+(?:com|net|org|io|ar|es|mx|co|br|ai|app|link|ly)\b(?:/[^\s)>\]]*)?",
    re.IGNORECASE,
)
_MARKDOWN_LINK = re.compile(r"\[[^\]\n]{1,180}\]\(([^)\n]{0,512})\)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_NUMBER = r"[+-]?[0-9](?:[0-9.,_]*[0-9])?(?:[eE][+-]?[0-9]+)?"
_CURRENCY = r"US\$|U\$S|R\$|USD|EUR|ARS|MXN|BRL|GBP|JPY|CLP|COP|PEN|UYU|CHF|CAD|AUD|\$|€|£|¥"
_CURRENCY_SUFFIX = rf"{_CURRENCY}|d[oó]lares|dollars|euros|pesos|reales|yen|pounds|libras"
_MONEY = re.compile(
    rf"(?P<prefix>{_CURRENCY})\s*(?P<a>{_NUMBER})"
    rf"(?:\s*(?P<trailing>{_CURRENCY_SUFFIX})(?![A-Za-z]))?"
    rf"|(?P<b>{_NUMBER})\s*(?P<suffix>{_CURRENCY_SUFFIX})(?![A-Za-z])",
    re.IGNORECASE,
)
_DECIMAL_PRICE = re.compile(r"[0-9]{1,6}(?:[.,][0-9]{1,2})?\Z")
_DISCOUNT = re.compile(
    r'\b(?:c[oó]digo|cup[oó]n)\s+(?:de\s+descuento\s+)?["“]?[A-Z0-9]{4,}\b'
    r"|\d{1,2}\s?%\s?(?:de\s+)?(?:descuento|off|rebaja)"
    r"|(?:descuento|rebaja)\s+(?:del?\s+)?\d{1,2}\s?%"
    r"|\b(?:discount|promo|coupon)\s+code\b"
    r"|\d{1,2}\s?%\s?(?:discount|off)\b",
    re.IGNORECASE,
)
_PRESSURE = (
    "ultimas unidades",
    "ultimos cupos",
    "solo por hoy",
    "solo hoy",
    "oferta termina",
    "quedan pocas",
    "quedan pocos",
    "antes de que se agote",
    "el mas vendido",
    "miles de familias",
    "cientos de familias",
    "last units",
    "only today",
    "today only",
    "offer ends",
    "selling out",
    "before it sells out",
    "best seller",
    "best-selling",
    "thousands of families",
    "hundreds of families",
)
_PAYMENT_REQUEST = re.compile(
    r"\b(?:env[ií]a(?:me)?|escrib[ei](?:me)?|comparte|dime|indica(?:me)?|pasa(?:me)?)\b[^.?!]{0,40}"
    r"\b(?:tarjeta|cvv|cvc|n[uú]mero de (?:la )?tarjeta|contraseña|clave)\b",
    re.IGNORECASE,
)
_PAYMENT_REQUEST_EN = re.compile(
    r"\b(?:send|give|share|tell|type|write)\b[^.?!]{0,40}\b(?:card number|credit card|debit card|cvv|cvc|password)\b",
    re.IGNORECASE,
)

# These bounded positive-claim recognizers protect common failure modes, not all semantic
# assertions. Published instructions and explicit refusals remain valid; no tool can execute
# the transactions described below. General citation entailment still needs quality review.
_ACTION_CLAIM = re.compile(
    r"\b(?:he|hemos)\s+(?:ya\s+)?(?:procesado|emitido|realizado|enviado|modificado|cancelado|"
    r"reservado|comprado|cobrado|devuelto|reembolsado)\b[^.!?;\n]{0,60}?"
    r"\b(?:reembolso|devoluci[oó]n|pedido|compra|dinero|pago|tarjeta|reserva|correo|mensaje)\b"
    r"|\b(?:procesé|reembolsé|devolví|cobré|reservé|compré|envié|modifiqué|cancelé|pagué)\b"
    r"[^.!?;\n]{0,60}?\b(?:reembolso|devoluci[oó]n|pedido|compra|dinero|pago|tarjeta|reserva|correo|mensaje)\b"
    r"|\b(?:ya|yo)\s+(?:procese|reembolse|devolvi|cobre|reserve|compre|envie|modifique|cancele|pague)\b"
    r"[^.!?;\n]{0,60}?\b(?:reembolso|devoluci[oó]n|pedido|compra|dinero|pago|tarjeta|reserva|correo|mensaje)\b"
    r"|\b(?:i|we)\s+(?:(?:have|already|just)\s+)*(?:processed|issued|sent|refunded|charged|"
    r"purchased|reserved|cancelled|canceled|modified|updated|placed)\b[^.!?;\n]{0,60}?"
    r"\b(?:refund|money|order|payment|card|purchase|booking|reservation|email|message)\b"
    r"|\b(?:he|hemos)\s+(?:ya\s+)?reembolsado\b"
    r"|\b(?:i|we)\s+(?:(?:have|already|just)\s+)*refunded\b"
    r"|\b(?:tu|su)\s+(?:reembolso|devoluci[oó]n|pedido|compra|pago|reserva)\s+"
    r"(?:(?:ya|ha|sido|fue|est[aá])\s+){1,4}(?:procesad[oa]|emitid[oa]|realizad[oa]|"
    r"enviad[oa]|modificad[oa]|cancelad[oa]|reservad[oa]|reembolsad[oa]|cobrad[oa]|devuelt[oa])\b"
    r"|\byour\s+(?:order|refund|purchase|payment|booking|reservation)\s+"
    r"(?:(?:has|have|already|just|been|was|is)\s+){1,5}(?:processed|issued|sent|modified|"
    r"updated|canceled|cancelled|refunded|reserved|charged|returned)\b",
    re.IGNORECASE,
)
_OUTCOME_CLAIM = re.compile(
    r"\b(?:garantiz(?:a|o|an|amos)|garantizado|garantizada|asegur(?:a|o|an|amos)|guarantees?|"
    r"guaranteed|ensures?|will certainly|definitely)\b[^.!?;\n]{0,100}?"
    r"\b(?:leer\w*|lectura|escribir|aprend\w*|read(?:ing)?|learn\w*|cure|curar|trat\w*)\b"
    r"|\b(?:aprendera(?:n)?|leera(?:n)?|va(?:n)? a leer|will learn|will read|will be reading)\b"
    r"[^.!?;\n]{0,50}?\b(?:en|in|within|after)\s+(?:\w+\s+){0,3}"
    r"(?:dias?|days?|semanas?|weeks?|mes(?:es)?|months?)\b"
    r"|\b(?:cura|cures?|trata|treats?)\b[^.!?;\n]{0,50}?"
    r"\b(?:dislexia|dyslexia|tdah|adhd|autismo|autism|trastorno|disorder)\b"
    r"|\b(?:cura|cures?|previene|prevents?|evita|treats?|trata|elimina)\b[^.!?;\n]{0,55}?"
    r"\b(?:anemia|alergias?|allergies|allergy|atragantamiento|choking|enfermedad|disease|desnutricion|malnutrition)\b"
)
_NEGATED_CLAIM_PREFIX = re.compile(
    r"(?:\bno|\bnunca|\bnot|\bnever|\bcannot|\bcan't|\bdidn't|\bhaven't|\bunable to)"
    r"\s+(?:\w+\s+){0,5}$"
)
_CONDITIONAL_CLAIM_PREFIX = re.compile(r"\b(?:si|if|cuando|when)\s+(?:\w+\s+){0,5}$")


def fold(text: str) -> str:
    """Lowercase, accent-free form used for term matching."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


_NUMBER_WORDS = {
    "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
    "ocho": 8, "nueve": 9, "diez": 10, "quince": 15, "veinte": 20, "treinta": 30,
    "sesenta": 60, "noventa": 90, "one": 1, "two": 2, "three": 3, "five": 5, "seven": 7,
    "ten": 10, "fifteen": 15, "thirty": 30, "sixty": 60, "ninety": 90,
}  # fmt: skip
_COUNT = r"(\d{1,3}|" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True)) + r")"
_DAY_UNIT = r"\s*-?\s*(?:dias?|days?)\b"
# Keep the bounded matching used by guarantee.days, including adjacent sentences.
_WINDOW = re.compile(
    r"\b(?:garant\w*|reembols\w*|devoluc\w*|refund\w*|guarantee\w*)\b[^\d]{0,60}?\b"
    + _COUNT
    + _DAY_UNIT
    + r"|\b"
    + _COUNT
    + _DAY_UNIT
    + r"\s+(?:de\s+|of\s+)?(?:garant\w*|reembols\w*|devoluc\w*|refund|guarantee)"
)
_PROCESSING = re.compile(
    r"responder|aprobac|aprob|transferencia|tarjeta|tardar|demora|vuelve|acredit|resumen"
)
_WITHDRAWAL = re.compile(r"arrepent|revoca")
_PUBLISHED_DAYS = re.compile(r"\b(\d{1,3})\s*dias\b")


def published_refund_days(policy_texts: tuple[str, ...]) -> frozenset[int]:
    return frozenset(
        int(days) for text in policy_texts for days in _PUBLISHED_DAYS.findall(fold(text))
    )


def unsupported_guarantee_claim(
    answer: str, guarantee_days: frozenset[int], refund_days: frozenset[int]
) -> bool:
    """Check stated guarantee windows against catalog and context-specific allowances."""
    text = fold(answer)
    for match in _WINDOW.finditer(text):
        raw = match.group(1) or match.group(2)
        count = int(raw) if raw.isdigit() else _NUMBER_WORDS[raw]
        allowed = guarantee_days
        # OD-50: the Argentine legal withdrawal window is 10 days.
        if _WITHDRAWAL.search(text[max(0, match.start() - 80) : match.end() + 80]):
            allowed |= {10}
        if _PROCESSING.search(text[max(0, match.start() - 40) : match.end() + 40]):
            allowed |= refund_days
        if count not in allowed:
            return True
    return False


# Bounded checkout-grouping claims, not general entailment. Product destinations do not
# establish whether merchants require separate purchases or permit a shared checkout.
_CHECKOUT_SUBJECT = re.compile(
    r"\b(?:compras?|productos?|pedidos?|pagos?|carritos?|purchases?|products?|orders?|payments?|carts?|checkout|bonos?|bonuses)\b"
)
_CHECKOUT_PREDICATE = re.compile(
    r"\b(?:realiza\w*|completa\w*|compr\w*|pag(?!os?\b)\w*|cuestan?|costs?|vend\w*|requiere\w*|debes?|puede\w*|purchase\w*|buy|bought|paid|pay|sold|sell|requires?|must|can|cannot|share)\b"
)
_CHECKOUT_GROUPING = re.compile(
    r"\b(?:aparte|por separado|separad[oa]s?|separately|separate|individualmente|individually|one at a time|uno a uno|junt[oa]s?|together|combina\w*|combin\w*|single (?:checkout|payment)|un (?:solo|unico) (?:pago|carrito)|same (?:cart|checkout))\b"
)
# One payment for a single product is a payment plan, not a multi-product rule.
_CHECKOUT_SINGLE_PAYMENT = re.compile(r"(?:un (?:solo|unico) pago|single payment)")
_CHECKOUT_MULTIPLE_PRODUCTS = re.compile(
    r"\b(?:ambos|ambas|dos|varios|varias|productos|compras|both|two|multiple|products|purchases)\b"
)
_CHECKOUT_IMPLICIT_SALE = re.compile(r"\b(?:vend\w*|sold|sell|selling)\b")
# A qualifier must concern the grouping proposition, not an unrelated price or action.
_CHECKOUT_UNCERTAIN = re.compile(
    r"\b(?:no (?:puedo|podemos) confirmar|no (?:se|sabemos)|cannot confirm|can't confirm|do not know|don't know|not confirmed|unknown)\s+(?:si|que|whether|if|that)\b"
    r"|\bno (?:tengo|hay) (?:informacion|confirmacion)\s+(?:(?:sobre|de|acerca de)\s+)?(?:si|que)\b"
)
_CHECKOUT_COORDINATE_CLAUSE = re.compile(
    r"\b(?:y|and)\s+(?=(?:(?:los|las|el|la|the|both|ambos|ambas|cada|each|two|dos)\s+)?"
    + _CHECKOUT_SUBJECT.pattern
    + r"|(?:debes?|deben|puedes?|pueden|tienes que|tienen que|you (?:must|can|cannot|need to))\b)"
)
_CHECKOUT_SELF_REFUSAL = re.compile(
    r"^(?:no (?:puedo|podemos)|i (?:cannot|can't)|we (?:cannot|can't))\s+(?:agregar|anadir|combinar|comprar|gestionar|add|combine|buy|manage)\b"
)


def _checkout_claims(text: str) -> frozenset[str]:
    # An independent coordinated product assertion cannot inherit a prior refusal.
    separated = _CHECKOUT_COORDINATE_CLAUSE.sub(";", fold(text))
    clauses = re.split(r"[!?;\n]|[.](?!\d)|\b(?:pero|but|however|porque|because)\b", separated)
    return frozenset(
        clause
        for raw in clauses
        if (clause := " ".join(raw.strip(" ,:").split()))
        and (_CHECKOUT_SUBJECT.search(clause) or _CHECKOUT_IMPLICIT_SALE.search(clause))
        and _CHECKOUT_PREDICATE.search(clause)
        and any(
            not _CHECKOUT_SINGLE_PAYMENT.fullmatch(match.group())
            or _CHECKOUT_MULTIPLE_PRODUCTS.search(clause)
            for match in _CHECKOUT_GROUPING.finditer(clause)
        )
        and not _CHECKOUT_UNCERTAIN.search(clause)
        and not _CHECKOUT_SELF_REFUSAL.search(clause)
    )


def unsupported_checkout_policy(text: str, policies: tuple[str, ...]) -> bool:
    """Require published wording for detected grouping assertions, including prohibitions.

    An explicit uncertainty or assistant action refusal is not a merchant restriction.
    Exact authoritative clauses preserve negation; a related URL or opposite claim cannot
    authorize a new checkout condition. This recognizes finite forms, not all paraphrases.
    """
    claims = _checkout_claims(text)
    if not claims:
        return False
    supported = frozenset(claim for policy in policies for claim in _checkout_claims(policy))
    return not claims.issubset(supported)


def _url_key(candidate: str) -> str | None:
    """Compare exact authorized paths, queries and fragments, never a host wildcard.

    Bare domains use https for prose like 'consumer.hotmart.com'. Sentence punctuation and
    host casing are normalized; encoded paths, extra parameters and userinfo are not aliases.
    """
    candidate = candidate.rstrip(".,;:!?'\"”")
    if not re.match(r"^https?://", candidate, re.IGNORECASE):
        candidate = f"https://{candidate}"
    try:
        parts = urlsplit(candidate)
        if (
            parts.scheme.lower() != "https"
            or not parts.hostname
            or parts.username
            or parts.password
        ):
            return None
        if parts.port is not None:
            return None
    except ValueError:
        return None
    return urlunsplit(
        ("https", parts.hostname.lower(), parts.path or "/", parts.query, parts.fragment)
    )


def _amount(raw: str) -> Decimal | None:
    # Match the complete numeric token. A prefix of '14,990' must not become 14.99; grouped,
    # scientific, signed and over-precision formats are not authoritative catalog displays.
    if not _DECIMAL_PRICE.fullmatch(raw):
        return None
    try:
        return Decimal(raw.replace(",", "."))
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
    if _has_unlisted_url(text, rules):
        violations.append(Violation.UNLISTED_URL)
    if (price_violation := _price_violation(text, rules)) is not None:
        violations.append(price_violation)
    if _DISCOUNT.search(text):
        violations.append(Violation.DISCOUNT_CLAIM)
    folded = fold(text)
    claims = (
        (Violation.FORBIDDEN_TERM, any(fold(term) in folded for term in rules.forbidden_terms)),
        (Violation.PRESSURE_CLAIM, any(phrase in folded for phrase in _PRESSURE)),
        (
            Violation.PAYMENT_DATA_REQUEST,
            _PAYMENT_REQUEST.search(text) or _PAYMENT_REQUEST_EN.search(text),
        ),
        (Violation.UNAUTHORIZED_ACTION_CLAIM, _positive_claim(_ACTION_CLAIM, text)),
        (Violation.UNSUPPORTED_OUTCOME_CLAIM, _positive_claim(_OUTCOME_CLAIM, folded)),
    )
    violations.extend(violation for violation, detected in claims if detected)
    return violations


def _has_unlisted_url(text: str, rules: AnswerRules) -> bool:
    without_emails = _EMAIL.sub(" ", text)
    urls = {_url_key(match.group()) for match in _URL.finditer(without_emails)}
    # Plain-text rendering cannot turn model-authored links into authorized navigation.
    # Still reject relative/empty/fragment/dangerous Markdown targets as final prose.
    urls.update(
        _url_key(match.group(1).strip()) for match in _MARKDOWN_LINK.finditer(without_emails)
    )
    allowed_urls = {_url_key(url) for url in rules.allowed_urls}
    return None in urls or any(url not in allowed_urls for url in urls)


def _price_violation(text: str, rules: AnswerRules) -> Violation | None:
    prices: list[tuple[Decimal | None, str]] = []
    for match in _MONEY.finditer(text):
        amount = _amount(match.group("a") or match.group("b"))
        currency = _currency(match.group("prefix") or match.group("suffix"))
        if match.group("trailing") and _currency(match.group("trailing")) != currency:
            amount = None
        prices.append((amount, currency))
    if not prices:
        return None
    if not rules.prices_verified:
        return Violation.UNVERIFIED_PRICE
    if any(
        amount is None or (amount, currency) not in rules.known_price_pairs
        for amount, currency in prices
    ):
        return Violation.UNKNOWN_PRICE
    return None


def _currency(raw: str) -> str:
    folded = fold(raw)
    if folded in {"us$", "u$s", "usd", "$", "dolares", "dollars"}:
        return "USD"
    if folded in {"eur", "€", "euros"}:
        return "EUR"
    if folded in {"brl", "r$", "reales"}:
        return "BRL"
    if folded in {"gbp", "£", "pounds", "libras"}:
        return "GBP"
    if folded in {"jpy", "¥", "yen"}:
        return "JPY"
    return folded.upper()


def _positive_claim(pattern: re.Pattern[str], text: str) -> bool:
    for match in pattern.finditer(text):
        prefix = fold(text[max(0, match.start() - 100) : match.start()])
        # A negation in a previous sentence/contrast must not hide a new positive claim.
        prefix = re.split(r"[.!?;,\n]|\b(?:pero|but|however|sin embargo|and|y)\b", prefix)[-1]
        if not _NEGATED_CLAIM_PREFIX.search(prefix) and not _CONDITIONAL_CLAIM_PREFIX.search(
            prefix
        ):
            return True
    return False
