"""Characterization of the lexical evidence path (PVA-M2.6): stems, rankings and the payload.

These pin today's reviewed behaviour so a silent change (or a surviving mutant) fails. When a
change is intended, re-run the probes in this file and update the expectations in the same PR.
"""

from __future__ import annotations

import hashlib

import pytest

from app.ai.evidence import _stem, catalog_payload, passages, rank
from app.domain.catalog import PriceStatus
from scripts.evaluate_conversations import CATALOG

STEMS = {
    "silabas": "silaba",
    "lugares": "lugar",
    "veces": "vez",
    "meses": "mes",
    "paises": "pais",
    "tres": "tres",
    "mies": "mies",
    "luz": "luz",
    "dos": "dos",
    "dias": "dia",
    "crisis": "crisis",
    "virus": "virus",
    "clases": "clase",
    "nombres": "nombre",
    "grandes": "grande",
    "posibles": "posible",
    "actividades": "actividad",
    "niveles": "nivel",
    "sesiones": "sesion",
    "padres": "padre",
    "lapices": "lapiz",
    "mas": "mas",
    "es": "es",
}


@pytest.mark.parametrize(("word", "stem"), sorted(STEMS.items()))
def test_stem(word: str, stem: str) -> None:
    assert _stem(word) == stem


TOP3 = {
    "¿Cómo pido el reembolso?": [
        "document:support.route.2",
        "document:faq.grafismo-fonetico.03",
        "document:policy.guarantee",
    ],
    "¿Qué incluye el kit?": [
        "document:faq.grafismo-fonetico.09",
        "document:faq.grafismo-fonetico.05",
        "document:support.route.3",
    ],
    "¿Cómo accedo después de comprar?": [
        "document:faq.grafismo-fonetico.10",
        "document:policy.delivery",
        "document:support.access.2",
    ],
    "¿Puedo pagar en pesos?": [
        "document:policy.payment",
        "document:faq.grafismo-fonetico.11",
        "document:support.route.1",
    ],
    "no me llegó el correo": [
        "document:support.access.1",
        "document:support.route.1",
        "document:support.access.3",
    ],
}


@pytest.mark.parametrize(("query", "expected"), sorted(TOP3.items()))
def test_rank_top3(query: str, expected: list[str]) -> None:
    ranked = rank(query, passages(CATALOG))
    assert [p.id for p, _ in ranked[:3]] == expected
    scores = [score for _, score in ranked]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] > 0


PAYLOADS = [
    (
        "",
        PriceStatus.VERIFIED,
        40000,
        (),
        13148,
        "1aa43666ea32fb6af612e3ea053c7282de1b26ad6a635232672c7e242fadceb7",
    ),
    (
        "alimentación del bebé",
        PriceStatus.UNVERIFIED,
        40000,
        (),
        6214,
        "3b25560f9dd8686bf396737b51c457b95ed9f986704a3b8e5651b4d8b4d27c1b",
    ),
    (
        "¿Qué incluye el kit de grafismo fonético?",
        PriceStatus.VERIFIED,
        6000,
        (),
        5918,
        "6a40b65382b198dc780d0d4cc8e527f836191ed91203d1f587ebbf069b37a0b9",
    ),
    (
        "quiero un reembolso",
        PriceStatus.VERIFIED,
        4000,
        ("policy.guarantee",),
        6078,
        "feb2895c0cddc775976b800bb007187886862e918482a1daed681909c0e9ef41",
    ),
]


@pytest.mark.parametrize(
    ("query", "status", "max_chars", "mandatory", "length", "digest"), PAYLOADS
)
def test_catalog_payload_is_stable(
    query: str,
    status: PriceStatus,
    max_chars: int,
    mandatory: tuple[str, ...],
    length: int,
    digest: str,
) -> None:
    out = catalog_payload(CATALOG, status, query, max_chars, frozenset(mandatory))
    assert len(out) == length
    assert hashlib.sha256(out.encode()).hexdigest() == digest
