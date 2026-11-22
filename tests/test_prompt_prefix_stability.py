"""PVA-M4-X: the provider-cacheable prompt prefix is byte-stable across visitors and turns.

Provider prompt caching only pays off when every request starts with identical bytes. The
prefix is the instructions, the output schema and the cache key; the catalog evidence follows,
and every per-visitor value (question, history, safety identifier) comes last.
"""

from __future__ import annotations

import json
from datetime import timedelta

from app.adapters.catalog_schema import CatalogParser
from app.ai.composer import ComposerSettings, GroundedComposer
from app.ai.prompt import INSTRUCTIONS, OUTPUT_SCHEMA, PROMPT_VERSION
from app.application.ports import Turn
from app.domain.catalog import ActiveCatalog, PriceStatus
from app.domain.conversation import AnswerDetails, Message, Role
from tests.support import CATALOG_BYTES, FixedClock, ScriptedProvider

CATALOG = CatalogParser(
    frozenset({"pequeverso.com", "consumer.hotmart.com", "refund.hotmart.com"})
)(CATALOG_BYTES)
ACTIVE = ActiveCatalog(CATALOG, "b" * 64, CATALOG.generated_at, timedelta(hours=168))
NOW = FixedClock().now()


def _request(question: str, *, session: str, history: tuple[Message, ...] = ()):
    turn = Turn(ACTIVE, PriceStatus.VERIFIED, history, question, None, session)
    composer = GroundedComposer(ScriptedProvider(), ComposerSettings(4000, 40000, 24000))
    return composer.prepare(turn).request


def _prefix(request) -> bytes:
    return json.dumps(
        {
            "instructions": request.instructions,
            "schema": request.output_schema,
            "cache_key": request.cache_key,
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode()


def test_prefix_bytes_do_not_depend_on_the_visitor_question_or_history() -> None:
    history = (
        Message("m1", Role.USER, "Hola, busco algo para mi hija", NOW, AnswerDetails()),
        Message("m2", Role.ASSISTANT, "¡Hola! Contame más.", NOW, AnswerDetails(language="es")),
    )
    first = _request("¿Cómo recibo el kit?", session="visitor-a")
    second = _request("¿Qué incluye la guía?", session="visitor-b", history=history)
    assert _prefix(first) == _prefix(second)
    assert first.instructions == INSTRUCTIONS
    assert first.output_schema == OUTPUT_SCHEMA
    assert first.cache_key == f"pequeverso-assistant:{PROMPT_VERSION}:{'b' * 16}"


def test_per_visitor_values_stay_out_of_the_prefix_and_after_the_catalog() -> None:
    request = _request("¿Cuánto cuesta el kit de verano?", session="visitor-c")
    prefix = _prefix(request).decode()
    for private in ("visitor-c", "kit de verano"):
        assert private not in prefix
    assert request.inputs[0].text.startswith("store_data:\n")
    assert request.inputs[-1].text.startswith("visitor_turn:\n")
    assert "kit de verano" in request.inputs[-1].text
    assert all("visitor-c" not in item.text for item in request.inputs)


def test_same_question_and_catalog_yield_identical_catalog_evidence_bytes() -> None:
    first = _request("¿Cómo recibo el kit?", session="visitor-a")
    second = _request("¿Cómo recibo el kit?", session="visitor-b")
    assert first.inputs[0].text.encode() == second.inputs[0].text.encode()


def test_a_new_catalog_snapshot_or_prompt_version_changes_only_the_cache_key() -> None:
    other = ActiveCatalog(CATALOG, "c" * 64, CATALOG.generated_at, timedelta(hours=168))
    turn = Turn(other, PriceStatus.VERIFIED, (), "¿Cómo recibo el kit?", None, "visitor-a")
    composer = GroundedComposer(ScriptedProvider(), ComposerSettings(4000, 40000, 24000))
    changed = composer.prepare(turn).request
    base = _request("¿Cómo recibo el kit?", session="visitor-a")
    assert changed.instructions == base.instructions
    assert changed.output_schema == base.output_schema
    assert changed.cache_key != base.cache_key
