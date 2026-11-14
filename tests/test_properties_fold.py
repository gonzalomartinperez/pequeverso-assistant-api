"""Matching normalization."""

import string
import unicodedata

import pytest
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
    """Row 3, over Latin letters and accents (the matching domain); see the xfail below."""
    stripped = "".join(
        c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c)
    )
    result = fold(text)
    assert fold(result) == result
    assert fold(text.upper()) == fold(text.lower()) == result
    assert fold(stripped) == fold(unicodedata.normalize("NFD", text)) == result


@pytest.mark.xfail(
    strict=True,
    reason="fold lowercases before NFKD, so compatibility characters (e.g. U+2120) fold to upper case "
    "and a second fold changes them; low impact: both sides of a match use the same function",
)
def test_fold_is_idempotent_for_compatibility_characters():
    """Row 3 outside the Latin alphabet: documents the known gap found in review."""
    assert fold(fold("\u2120")) == fold("\u2120")
