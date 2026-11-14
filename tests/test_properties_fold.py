"""Matching normalization."""

import string
import unicodedata

from hypothesis import example, given
from hypothesis import strategies as st

from app.domain.answer_policy import fold


@given(
    text=st.text(
        alphabet=string.ascii_letters + "áéíóúüñÁÉÍÓÚÜÑ çÇàÀ\u0301\u0308 -!?", max_size=100
    )
)
@example(text="Árbol, NIÑOS y pingüino")
def test_fold_is_idempotent_and_case_accent_insensitive(text):
    """Row 3: Latin matching ignores case and composed/decomposed accents."""
    stripped = "".join(
        c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c)
    )
    result = fold(text)
    assert fold(result) == result
    assert fold(text.upper()) == fold(text.lower()) == result
    assert fold(stripped) == fold(unicodedata.normalize("NFD", text)) == result
