"""Visitor-input hygiene applied before anything is stored or sent to a model.

Payment card numbers stop the turn entirely (the assistant never handles payment data); e-mail
addresses and phone numbers are replaced by placeholders because no answer needs them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CARD_CANDIDATE = re.compile(r'(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)')
_EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
_PHONE = re.compile(r'(?<![\w])\+?\d(?:[\s().-]?\d){7,14}(?![\w])')

EMAIL_PLACEHOLDER = '[correo]'
PHONE_PLACEHOLDER = '[teléfono]'


def _luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def contains_card_number(text: str) -> bool:
    for match in _CARD_CANDIDATE.finditer(text):
        digits = re.sub(r'\D', '', match.group())
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            return True
    return False


@dataclass(frozen=True, slots=True)
class Redacted:
    text: str
    redactions: int


def redact_contact_data(text: str) -> Redacted:
    text, emails = _EMAIL.subn(EMAIL_PLACEHOLDER, text)
    text, phones = _PHONE.subn(PHONE_PLACEHOLDER, text)
    return Redacted(text=text, redactions=emails + phones)
