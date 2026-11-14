"""Language detection on a finite classified vocabulary."""

import unicodedata

from hypothesis import example, given
from hypothesis import strategies as st

from app.domain.language import Detected, detect

SENTENCES = [
    ("¿Cuál es el precio para mi niño?", Detected.ES),
    ("Quiero imprimir las letras para mi hija", Detected.ES),
    ("¿Cómo puedo comprar y cuál es la garantía?", Detected.ES),
    ("What is the price for my child?", Detected.EN),
    ("Can I print this for my daughter?", Detected.EN),
    ("How do I buy and what does it include?", Detected.EN),
]


@given(
    sentence=st.sampled_from(SENTENCES),
    casing=st.sampled_from(["upper", "lower", "swapcase", "title"]),
)
@example(sentence=SENTENCES[0], casing="upper")
def test_detect_survives_case_and_accent_changes(sentence, casing):
    """Row 4: classified Spanish/English sentences retain their language."""
    text, expected = sentence
    stripped = "".join(
        c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c)
    )
    assert detect(text) == expected
    assert detect(getattr(text, casing)()) == expected
    assert detect(getattr(stripped, casing)()) == expected
