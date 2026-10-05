"""Reply-language decision: the visitor's own words decide; quotes, names and data do not."""

from __future__ import annotations

import pytest

from app.domain.language import Detected, Language, detect, reply_language

PRODUCTS = ['Grafismo Fonético']


@pytest.mark.parametrize(
    ('text', 'expected'),
    [
        ('¿Qué incluye el kit?', Detected.ES),
        ('que incluye el kit', Detected.ES),
        ('Mi hijo tiene 5 años, le sirve?', Detected.ES),
        ('cuanto sale??', Detected.ES),
        ('What does the kit include?', Detected.EN),
        ('Is it good for a 6 year old?', Detected.EN),
        ('How much is Grafismo Fonético?', Detected.EN),
        ('Quanto custa o kit para meu filho?', Detected.OTHER),
        ('Combien coûte le kit pour mon fils?', Detected.OTHER),
        ('ok', Detected.UNKNOWN),
        ('Grafismo Fonético', Detected.UNKNOWN),
        ('https://pequeverso.com/grafismo-fonetico/', Detected.UNKNOWN),
    ],
)
def test_detect(text: str, expected: Detected) -> None:
    assert detect(text, PRODUCTS) is expected


def test_quoted_text_and_code_do_not_switch_the_language() -> None:
    assert (
        detect('¿Qué significa "what does the kit include and how much is it" en la tienda?') is Detected.ES
    )
    assert detect('mi hija escribió `print all the pages please now`, qué hago?') is Detected.ES


def test_conversation_then_locale_break_ties() -> None:
    assert reply_language('ok', [Language.EN], Language.ES) is Language.EN
    assert reply_language('ok', [], Language.EN) is Language.EN
    assert reply_language('ok', [], None) is Language.ES
    assert reply_language('What ages?', [Language.ES], Language.ES) is Language.EN
    assert reply_language('¿Y para 7 años?', [Language.EN], Language.EN) is Language.ES


def test_unsupported_language_returns_none() -> None:
    assert reply_language('Quanto custa o kit para meu filho?', [Language.ES], Language.ES) is None


@pytest.mark.parametrize(
    'text',
    [
        "I'm looking for something my kid's teacher recommended",
        "We're homeschooling and she's 5, what's best?",
        "Hi! I'd like to know if it's printable",
    ],
)
def test_english_contractions_are_not_mistaken_for_quotes(text: str) -> None:
    assert detect(text) is Detected.EN


def test_long_quoted_passages_never_switch_the_language() -> None:
    quoted = ' '.join(['the kit includes printable pages for children and parents'] * 9)
    assert len(quoted) > 400
    assert detect(f'¿Qué significa "{quoted}"?') is Detected.ES
