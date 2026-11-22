"""The official help scope and its guard against unsupported merchant claims."""

import json
from datetime import UTC, datetime

import pytest

from app.domain.web_evidence import (
    SOURCES,
    HelpTopic,
    WebEvidence,
    evidence_payload,
    negated_at,
    topics_for,
    unsupported_platform_policy,
)


@pytest.mark.parametrize(
    ("question", "previous", "expected"),
    [
        ("¿Cómo tramita mi pedido el soporte?", "", ()),
        ("¿Y si eso falla?", "¿Cuál es el estado de mi pedido?", ()),
        ("¿Y si eso falla?", "¿Cómo encuentro la descarga?", (HelpTopic.DELIVERY,)),
        ("¿Eso cambia? " + "x" * 90, "¿Cómo encuentro la descarga?", ()),
        ("¿Cuánto cuesta?", "¿Cómo contacto al productor?", ()),
        ("¿Cómo contacto al productor?", "", (HelpTopic.SUPPORT,)),
        (
            "¿Cómo consigo acceso, reembolso o soporte?",
            "",
            (HelpTopic.REFUND, HelpTopic.DELIVERY, HelpTopic.SUPPORT),
        ),
    ],
)
def test_topics_only_inherit_approved_procedures(question, previous, expected):
    assert topics_for(question, previous) == expected


def test_evidence_payload_keeps_procedure_scope_and_provenance():
    evidence = WebEvidence(
        SOURCES[0], "Revisa tu buzón.", "a" * 64, datetime(2026, 11, 22, tzinfo=UTC)
    )
    payload = evidence_payload((evidence,))
    assert "buzón" in payload
    assert json.loads(payload) == [
        {
            "id": "hotmart:209033897",
            "title": "Hotmart · entrega digital",
            "text": "Revisa tu buzón.",
            "verified_at": "2026-11-22T00:00:00+00:00",
            "sha256": "a" * 64,
            "scope": "general_platform_procedure_not_merchant_facts",
        }
    ]
    assert json.loads(evidence_payload(())) == []


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("no prometemos un |reembolso", True),
        ("never promise a |refund", True),
        ("no olvides el |reembolso", False),
        ("don't forget. |refund", False),
        ("no pediremos el correo, pero sí el |reembolso", False),
        ("no " + "x " * 41 + "|reembolso", False),
    ],
)
def test_negation_applies_only_within_the_current_clause(text, expected):
    prefix, _, claim = text.partition("|")
    assert negated_at(prefix + claim, len(prefix)) is expected


@pytest.mark.parametrize(
    ("claim", "policies", "blocked"),
    [
        ("La garantía dura 15 días.", ("Tienes 15 días para solicitarla.",), False),
        ("Ofrecemos 15 días de garantía.", ("Dispones de 15 días.",), False),
        ("The guarantee is 15 days.", ("Tienes 15 días.",), False),
        ("Get a 15-day guarantee.", ("Tienes 7 días.", "El banco demora 15 días."), True),
        ("La garantía no dura 15 días.", (), False),
        ("No olvides la garantía de 15 días.", (), True),
        ("La solicitud no se procesa inmediatamente.", (), True),
        ("The refund request is not processed immediately.", (), True),
        ("Tu compra es elegible.", (), True),
        ("El reembolso no está garantizado.", (), False),
        ("No prometemos un reembolso garantizado.", (), False),
        ("El reembolso será aprobado.", (), True),
        ("Send me your order number.", (), True),
        ("No me envíes tu correo.", (), False),
        ("Consulta el procedimiento en Hotmart.", (), False),
    ],
)
def test_platform_procedures_cannot_create_store_promises_or_collect_details(
    claim, policies, blocked
):
    assert unsupported_platform_policy(claim, policies) is blocked
