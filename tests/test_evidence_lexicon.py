"""Query expansion adds weaker lexical matches while preserving exact BM25 matches."""

import pytest

from app.ai.evidence import Passage, rank


def test_regional_alias_matches_catalog_vocabulary_at_lower_weight() -> None:
    passage = Passage("one", "El precio aparece en tu moneda local.")
    exact = rank("moneda", [passage])[0][1]
    alias = rank("EUROS", [passage])[0][1]

    assert 0 < alias < exact
    assert rank("euros moneda", [passage])[0][1] == exact


def test_equivalent_aliases_do_not_stack() -> None:
    passage = Passage("one", "Contacto y soporte.")
    single = rank("TELÉFONO", [passage])
    assert single[0][1] > 0
    assert rank("teléfono WhatsApp WhatsApp", [passage]) == single


def test_expansion_is_query_side_only() -> None:
    passage = Passage("one", "Teléfono")
    assert rank("contacto", [passage]) == [(passage, 0.0)]


def test_intent_phrase_requires_the_negative_context() -> None:
    passage = Passage("one", "Revisa Spam y Promociones.")
    assert rank("No me llegó el correo", [passage])[0][1] > 0
    assert rank("Me llegó el correo", [passage]) == [(passage, 0.0)]


@pytest.mark.parametrize("query", ["Ya sé más", "telescopio", ""])
def test_unrelated_and_empty_queries_preserve_catalog_order(query: str) -> None:
    items = [Passage("first", "Contacto y soporte."), Passage("second", "Escríbenos por correo.")]
    assert rank(query, items) == [(item, 0.0) for item in items]


def test_exact_terms_keep_length_normalization_and_stable_ties() -> None:
    first = Passage("first", "Sílabas")
    longer = Passage("longer", "Sílabas palabras")
    last = Passage("last", "Sílaba")

    results = rank("SÍLABAS sílaba", [longer, first, last])

    assert [passage for passage, _ in results] == [first, last, longer]
    assert results[0][1] == results[1][1] > results[2][1] > 0
