"""Characterize ordering, claim attribution and packing before local extractions."""

import json
from dataclasses import replace
from datetime import timedelta

import pytest

from app.adapters.catalog_schema import CatalogParser
from app.ai.composer import ComposerSettings, GroundedComposer, PreparedRequest
from app.application.catalog_scope import catalog_scope_reply
from app.application.ports import Turn
from app.domain.answer_policy import Violation, check_answer
from app.domain.catalog import ActiveCatalog, PriceStatus
from app.domain.conversation import AnswerDetails, Message, Notice, Role
from app.domain.errors import FailureCode, RejectedError
from app.domain.knowledge import ChunkKind, RetrievalStrategy
from app.domain.language import Language
from app.domain.page_claims import unsupported_page_claim
from tests.support import CATALOG_BYTES, ScriptedProvider
from tests.test_domain import RULES
from tests.test_hybrid_knowledge import execute, setup

CATALOG = CatalogParser(
    frozenset({"pequeverso.com", "consumer.hotmart.com", "refund.hotmart.com"})
)(CATALOG_BYTES)


@pytest.mark.parametrize(
    ("verified", "price_violation"),
    [(True, Violation.UNKNOWN_PRICE), (False, Violation.UNVERIFIED_PRICE)],
)
def test_policy_returns_all_violations_in_order(verified, price_violation):
    answer = (
        "Escribe a help@example.com o visita [aquí](#faq). Cuesta US$14.99 EUR. "
        "Usa 20% de descuento. Pack Imprime y Juega. Solo por hoy. Share your password. "
        "He procesado tu pedido. Aprenderá a leer en dos semanas."
    )
    assert check_answer(answer, replace(RULES, prices_verified=verified)) == [
        Violation.UNLISTED_EMAIL,
        Violation.UNLISTED_URL,
        price_violation,
        Violation.DISCOUNT_CLAIM,
        Violation.FORBIDDEN_TERM,
        Violation.PRESSURE_CLAIM,
        Violation.PAYMENT_DATA_REQUEST,
        Violation.UNAUTHORIZED_ACTION_CLAIM,
        Violation.UNSUPPORTED_OUTCOME_CLAIM,
    ]


@pytest.mark.parametrize(
    ("text", "unsupported"),
    [
        ("Hay 39 páginas en Safari.", True),
        ("Hay 40 páginas en Safari.", False),
        ("Hay 39 páginas junto a Safari.", False),
        ("Both have 39 pages each.", False),
        ("El kit incluye Safari y ambos tienen 40 páginas. Ambos tienen 39 páginas.", True),
        ("Safari y el kit suman 414 páginas.", False),
        ("El kit y Safari suman 40 páginas.", True),
        (
            "Safari tiene 40 páginas. Juega tiene 50 páginas. Safari trae juegos. "
            "Mi Pared de Sonidos trae material. Ambos tienen 40 páginas.",
            False,
        ),
    ],
)
def test_page_claims_keep_local_product_and_recent_resource_attribution(text, unsupported):
    assert unsupported_page_claim(text, CATALOG) is unsupported


def test_catalog_scope_removes_redaction_markers_and_checks_only_the_latest_message():
    history = (
        Message(
            "a",
            Role.ASSISTANT,
            "Respuesta anterior",
            CATALOG.generated_at,
            AnswerDetails(notices=(Notice.ANSWER_REPLACED,)),
        ),
        Message("u", Role.USER, "Consulta anterior", CATALOG.generated_at),
    )
    assert catalog_scope_reply(
        "¿Tus fuentes incluyen chats de otros clientes? [correo] [teléfono]",
        CATALOG,
        history,
        Language.ES,
    ) == (
        "El catálogo contiene información pública sobre los productos; no incorpora "
        "conversaciones ni datos privados de otras personas."
    )
    assert catalog_scope_reply("", CATALOG, history, Language.ES) is None


@pytest.mark.parametrize(
    ("role", "expected_text"),
    [(Role.ASSISTANT, ""), (Role.USER, ("Una frase sin puntuación " * 70)[:1200])],
)
def test_composer_only_omits_latest_answer_text_when_no_complete_sentence_fits(role, expected_text):
    active = ActiveCatalog(CATALOG, "a" * 64, CATALOG.generated_at, timedelta(days=7))
    history = (Message("m", role, "Una frase sin puntuación " * 70, CATALOG.generated_at),)
    turn = Turn(
        active,
        PriceStatus.VERIFIED,
        history,
        "¿Cómo recibo el kit?",
        None,
        "synthetic",
        input_size_limit=128,
    )
    prepared = GroundedComposer(ScriptedProvider(), ComposerSettings(4000, 40000)).prepare(turn)
    assert isinstance(prepared, PreparedRequest)
    visitor = json.loads(prepared.request.inputs[-1].text.split("\n", 1)[1])
    assert visitor["conversation"] == [{"role": role.value, "text": expected_text}]
    assert visitor["question"] == turn.question
    assert prepared.input_size_bytes > 128


@pytest.mark.parametrize("stage", ["lexical", "vector", "graph", "graph_error", "anchor"])
def test_retrieval_rejects_mislabeled_hits_and_noncanonical_anchors(stage):
    retrieval, store, graph, embeddings, active = setup()
    product_id = "grafismo-fonetico"
    chunk_id = f"product:{product_id}"
    store.lexical = (store.hit(chunk_id),)
    if stage == "lexical":
        store.lexical = (store.hit(chunk_id, RetrievalStrategy.VECTOR),)
    elif stage == "vector":
        store.vector = (store.hit(chunk_id),)
    elif stage == "graph":
        graph.hits = (store.hit(chunk_id),)
    elif stage == "graph_error":
        graph.candidate_error = RejectedError(FailureCode.CATALOG_UNAVAILABLE)
    else:
        chunks = tuple(
            replace(c, kind=ChunkKind.RESOURCE) if c.id == chunk_id else c
            for c in store.corpus.chunks
        )
        store.corpus = replace(store.corpus, chunks=chunks)

    with pytest.raises(RejectedError, match="catalog_unavailable"):
        execute(retrieval, active, (product_id,))
    assert len(embeddings.calls) == (0 if stage == "lexical" else 1)


def test_retrieval_rejects_an_embedding_batch_with_no_query_vector(monkeypatch):
    retrieval, _, _, embeddings, active = setup()

    async def encode(texts, purpose):
        return ()

    monkeypatch.setattr(embeddings, "encode", encode)
    with pytest.raises(RejectedError, match="dependency_unavailable"):
        execute(retrieval, active)


def test_retrieval_breaks_equal_fusion_scores_by_chunk_id():
    retrieval, store, graph, _, active = setup()
    filler = next(c.id for c in store.corpus.chunks if c.kind is ChunkKind.RESOURCE)
    lexical = "product:grafismo-fonetico"
    semantic = "product:alimentacion-bebe"
    store.lexical = (store.hit(filler),) * 4 + (store.hit(lexical),)
    store.vector = (store.hit(filler, RetrievalStrategy.VECTOR),) * 3 + (
        store.hit(semantic, RetrievalStrategy.VECTOR),
    )
    expected = (filler, semantic, lexical)
    assert tuple(c.id for c in execute(retrieval, active).chunks) == expected
    assert graph.seeds == expected
