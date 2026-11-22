"""Boundary cases in native and legacy response language selection."""

import pytest

from app.domain.language import Detected, Language, detect, reply_language, spanish_native_language


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("ok pdf 123", Detected.UNKNOWN),
        ("xylophone kaleidoscope", Detected.UNKNOWN),
        ("xylophone kaleidoscope hello", Detected.UNKNOWN),
        ("hola hello", Detected.UNKNOWN),
        ("¡xylophone!", Detected.ES),
        ("hello", Detected.EN),
        ("obrigada", Detected.OTHER),
    ],
)
def test_detector_requires_a_unique_sufficient_signal(question, expected):
    assert detect(question, ("",)) is expected


def test_legacy_mixed_turn_uses_the_latest_answer_language():
    assert reply_language("hola hello", [Language.ES, Language.EN], Language.ES) is Language.EN


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Please continue in Spanish.", Language.ES),
        ("Hablemos en inglés.", None),
        ("No hablemos en inglés. Usemos el material del kit.", Language.ES),
        ("No respondas en español. Luego usa inglés.", None),
        ("What does the kit include?", Language.ES),
        ('Please read this phrase: "switch to English".', Language.ES),
        ("Por favor usa español. Y utiliza francés.", None),
    ],
)
def test_native_explicit_language_selection(question, expected):
    assert spanish_native_language(question) is expected
