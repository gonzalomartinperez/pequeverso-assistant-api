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


def _passage(pid: str, text: str) -> Passage:
    return Passage(pid, text)


@pytest.mark.parametrize(
    "query",
    [
        "¿En qué hago clic para imprimir las fichas?",
        "¿Puede mi hijo devolver las tarjetas a la caja?",
        "Me arrepentí de imprimir en color",
    ],
)
def test_ambiguous_words_do_not_pull_payment_or_refund_policy(query: str) -> None:
    items = [
        _passage(
            "policy", "Pago en página segura. Reembolso y arrepentimiento: revocar la compra."
        ),
        _passage(
            "faq", "Puedes imprimir las fichas y tarjetas en casa, en color o en blanco y negro."
        ),
    ]
    assert rank(query, items)[0][0].id == "faq"


def test_refund_phrases_still_expand() -> None:
    items = [
        _passage("other", "Fichas para imprimir."),
        _passage("refund", "Reembolso del dinero."),
    ]
    assert rank("Quiero que me devuelvan la plata", items)[0][0].id == "refund"


def test_irregular_plurals_fold_to_the_singular() -> None:
    from app.ai.evidence import tokens

    assert tokens("meses países") == tokens("mes país")


def test_query_text_is_never_memoized() -> None:
    from app.ai import evidence

    sentinel = "consulta centinela irrepetible 7f3a9c"
    items = [_passage("faq", "Puedes imprimir las fichas en casa.")]
    evidence.rank(sentinel, items)
    for name in dir(evidence):
        cache = getattr(getattr(evidence, name), "cache_parameters", None)
        if cache is None:
            continue
        assert name in {"_passage_tokens", "_alias_index"}, f"{name} caches query-side input"
    assert evidence._passage_tokens("consulta centinela irrepetible 7f3a9c") is not None
    evidence._passage_tokens.cache_clear()


@pytest.mark.parametrize(
    ("plural", "singular"),
    [
        ("nombres", "nombre"),
        ("posibles", "posible"),
        ("grandes", "grande"),
        ("lugares", "lugar"),
        ("actividades", "actividad"),
        ("veces", "vez"),
        ("tres", "tres"),
    ],
)
def test_spanish_plural_folding(plural: str, singular: str) -> None:
    from app.ai.evidence import tokens

    assert tokens(plural) == tokens(singular)


def test_stopwords_are_dropped() -> None:
    from app.ai.evidence import tokens

    assert tokens("el kit de las fichas") == tokens("kit fichas")


def test_values_question_does_not_pull_payment_policy() -> None:
    items = [
        _passage("policy", "Precio y pago en página segura."),
        _passage("faq", "El kit enseña valores como la paciencia y el respeto."),
    ]
    assert rank("¿Qué valores enseña?", items)[0][0].id == "faq"
