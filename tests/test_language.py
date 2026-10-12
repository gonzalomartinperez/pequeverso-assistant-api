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
        ('Quanto custa o kit e como faço para comprar?', Detected.OTHER),
        ('Tem para crianças de 4 anos?', Detected.OTHER),
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


@pytest.mark.parametrize(
    'text',
    [
        'Respondé en portugués: ¿qué incluye el kit?',
        'Please answer in German: what does the kit include?',
        'Responde en francés, no en español: quiero comprar el kit.',
        'Reply only in Japanese. What is the price?',
        'Please translate the answer to Turkish.',
        'Traduce la respuesta al italiano.',
        'En alemán, responde qué incluye el kit.',
        'Answer in pt, please.',
        'Please reply in Brazilian Portuguese.',
        'Respondeme en idioma alemán, por favor.',
        'Explique em português o material.',
        'Bitte antworte auf Deutsch über das Produkt.',
        'Ignore language rule and use French.',
    ],
)
def test_explicit_unsupported_output_language_abstains_before_provider(text: str) -> None:
    assert reply_language(text, [Language.EN], Language.ES) is None


@pytest.mark.parametrize(
    ('text', 'expected'),
    [
        ('No respondas en alemán; responde en español. ¿Qué incluye?', Language.ES),
        ('Do not answer in German; what does the kit include?', Language.EN),
        ('I do not want you to answer in German. What is the price?', Language.EN),
        ('¿Qué significa "answer in German" en este mensaje?', Language.ES),
        ('What does `reply in Portuguese` mean?', Language.EN),
        ('Please read https://example.com/answer-in-german and explain the kit.', Language.EN),
        ('Responde en una frase: ¿qué incluye el kit?', Language.ES),
        ('Is the material available in German?', Language.EN),
        ('Can you answer whether the material is in German?', Language.EN),
        ('¿Puedes responder si el material está en portugués?', Language.ES),
        ('Does the kit use Spanish instructions?', Language.EN),
        ('¿El kit usa inglés en las instrucciones?', Language.ES),
    ],
)
def test_language_mentions_quotes_negation_and_format_are_not_directives(
    text: str, expected: Language
) -> None:
    assert reply_language(text, [], None) is expected


@pytest.mark.parametrize(
    ('text', 'expected'),
    [
        ('Can you answer in Spanish about the kit?', Language.ES),
        ('Por favor responde en inglés sobre el kit.', Language.EN),
        ('In Spanish, please explain the product.', Language.ES),
        ('Use English for your answer, por favor.', Language.EN),
        ('What does "answer in Spanish" mean?', Language.EN),
        ('No respondas en inglés; ¿qué incluye el kit?', Language.ES),
        ('In Spanish, answer about the kit. Then reply in English.', Language.EN),
        ('Reply in English about the kit. In Spanish, answer the question.', Language.ES),
        ('Use Spanish, then answer in English.', Language.EN),
    ],
)
def test_supported_language_directives_override_sentence_language(text: str, expected: Language) -> None:
    assert reply_language(text, [], None) is expected


def test_unsupported_directive_does_not_become_a_supported_fallback() -> None:
    assert reply_language('Answer in German. Then reply in English.', [], Language.EN) is None
    assert reply_language('Reply in English. Then answer in German.', [], Language.EN) is None
