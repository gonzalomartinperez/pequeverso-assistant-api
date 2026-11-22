"""Characterize public results and failure paths before extracting adapter helpers."""

import asyncio
import hashlib
import json
from dataclasses import asdict, replace
from decimal import Decimal
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from app.adapters.catalog.knowledge import build_public_corpus
from app.adapters.neo4j.public_graph import Neo4jPublicGraph
from app.adapters.providers.openai_provider import OpenAIResponsesProvider
from app.ai.provider import TextChunk, UsageChunk
from app.domain.budget import Usage
from app.domain.catalog import Catalog, Document, DocumentKind, Link, Price, Product, Resource, Site
from app.domain.errors import FailureCode, RejectedError
from tests.test_knowledge_indexing import VECTOR, Rig, corpus
from tests.test_neo4j_public_graph import Driver
from tests.test_openai_provider import REQUEST, _Client, _Events
from tests.test_public_corpus import NOW, SPEC

if TYPE_CHECKING:
    from openai import AsyncOpenAI


def test_corpus_preserves_projection_bytes_with_shared_topics_and_legacy_owners() -> None:
    body = b'{"fixture": "public corpus"}'
    core = Product(
        id="kit",
        name="Grafía",
        path="/kit",
        purchase_path="/comprar",
        summary="Práctica",
        age_range="3-5",
        format="PDF",
        usage="En casa",
        pdf_count=1,
        page_count=5,
        price=Price(Decimal("10.00"), "USD", "$10.00", "", ""),
        resources=(Resource("trazos", "Trazos", 5, "Guía"),),
        topics=("Motricidad", "Trazos", "Motricidad"),
    )
    affiliate = replace(
        core,
        id="curso",
        name="Curso",
        path="/curso",
        price=None,
        resources=(),
        kind="affiliate",
        topics=("Motricidad",),
    )
    catalog = Catalog(
        1,
        NOW,
        "a" * 40,
        Site("Fixture", "https://example.test", "es", "help@example.test", "help"),
        (core, affiliate),
        (Document("policy", DocumentKind.POLICY, "Política", "Cláusula", "https://example.test"),),
        (
            Link("help", "Ayuda", "https://example.test/help"),
            Link("course", "Curso", "https://example.test/course", ("curso",)),
        ),
    )

    def parse(raw: bytes) -> Catalog:
        assert raw == body
        return catalog

    projection = asdict(build_public_corpus(body, NOW, SPEC, parse))
    projection["catalog_body"] = projection["catalog_body"].hex()
    projection["verified_at"] = projection["verified_at"].isoformat()
    serialized = json.dumps(projection, ensure_ascii=False, separators=(",", ":")).encode()
    # Captured from the pre-refactor implementation. Field, chunk, entity and relation order
    # all contribute to the digest, as do the exact text bytes and the derived hashes.
    assert (
        hashlib.sha256(serialized).hexdigest()
        == "be7a5f723400c2862560c8e06b81e60ac3329d841adbc8870ac951a302dbfc63"
    )


@pytest.mark.parametrize(
    ("rows", "limit", "error", "message"),
    [
        ([{}, {}], 1, ValueError, "graph returned more candidates than requested"),
        (
            [{"id": "product:kit", "depth": 1, "relations": [None]}],
            1,
            TypeError,
            "graph path provenance is malformed",
        ),
        (
            [{"id": "product:kit", "depth": True, "relations": [None]}],
            1,
            ValueError,
            "graph path must have one or two supported edges",
        ),
        (
            [{"id": "product:kit", "depth": 1, "relations": {}}],
            1,
            ValueError,
            "graph path must have one or two supported edges",
        ),
        (
            [
                {
                    "id": "product:kit",
                    "sha256": "a" * 64,
                    "depth": 1,
                    "relations": [
                        {
                            "subject": "product:kit",
                            "object": "topic:trazos",
                            "predicate": "has_topic",
                            "support": "product:kit",
                            "pointer": "/products/0/topics/0",
                        }
                    ],
                },
                {"id": "product:kit"},
            ],
            2,
            ValueError,
            "graph returned duplicate chunk candidates",
        ),
    ],
)
def test_graph_candidates_close_session_before_rejecting_invalid_rows(
    rows, limit, error, message
) -> None:
    driver = Driver()
    driver.hits = rows
    with pytest.raises(error, match=f"^{message}$"):
        asyncio.run(Neo4jPublicGraph(driver).candidates("a" * 64, ("product:kit",), limit))
    assert driver.session_exits == 1


def test_graph_candidates_skip_empty_seeds_and_map_driver_failure() -> None:
    driver = Driver()
    driver.fail_read = True
    graph = Neo4jPublicGraph(driver)
    assert asyncio.run(graph.candidates("a" * 64, (), 1)) == ()
    assert driver.calls == []
    with pytest.raises(RejectedError, match=r"^dependency_unavailable$") as error:
        asyncio.run(graph.candidates("a" * 64, ("product:kit",), 1))
    assert error.value.__cause__ is None
    assert len(driver.calls) == driver.session_exits == 1


@pytest.mark.parametrize("close_after_usage", [False, True])
def test_failed_openai_response_logs_and_yields_usage_before_rejection(
    caplog: pytest.LogCaptureFixture, close_after_usage: bool
) -> None:
    events = _Events(
        [
            SimpleNamespace(type="response.output_text.delta", delta="prefix"),
            SimpleNamespace(
                type="response.failed",
                response=SimpleNamespace(usage=SimpleNamespace(input_tokens=4, output_tokens=2)),
            ),
        ]
    )
    client = _Client([events])
    provider = OpenAIResponsesProvider(cast("AsyncOpenAI", client), "test", "low", max_retries=0)

    async def run() -> None:
        stream = provider.stream(REQUEST)
        assert await anext(stream) == TextChunk("prefix")
        assert await anext(stream) == UsageChunk(Usage(input_tokens=4, output_tokens=2))
        assert not events.closed
        if close_after_usage:
            await stream.aclose()
        else:
            with pytest.raises(RejectedError) as error:
                await anext(stream)
            assert error.value.code is FailureCode.GENERATION_FAILED
        assert events.closed

    asyncio.run(run())
    assert len(client.calls) == 1
    assert caplog.record_tuples == [
        (
            "app.adapters.providers.openai_provider",
            30,
            '{"operation":"provider_stream","outcome":"response.failed","reason":"none"}',
        )
    ]


@pytest.mark.parametrize("kind", ["error", "response.refusal.done"])
def test_openai_error_events_reject_and_close(caplog: pytest.LogCaptureFixture, kind: str) -> None:
    events = _Events([SimpleNamespace(type=kind)])
    client = _Client([events])
    provider = OpenAIResponsesProvider(cast("AsyncOpenAI", client), "test", "low", max_retries=0)

    async def run() -> None:
        with pytest.raises(RejectedError) as error:
            await anext(provider.stream(REQUEST))
        assert error.value.code is FailureCode.GENERATION_FAILED

    asyncio.run(run())
    assert events.closed
    assert caplog.messages == (
        ['{"operation":"provider_stream","outcome":"error"}'] if kind == "error" else []
    )


def test_openai_completion_without_usage_closes_after_ignoring_unknown_events() -> None:
    events = _Events(
        [
            SimpleNamespace(),
            SimpleNamespace(type="response.output_text.delta", delta="text"),
            SimpleNamespace(type="response.completed", response=SimpleNamespace()),
        ]
    )
    client = _Client([events])
    provider = OpenAIResponsesProvider(cast("AsyncOpenAI", client), "test", "low", max_retries=0)

    async def run() -> None:
        assert [chunk async for chunk in provider.stream(REQUEST)] == [TextChunk("text")]

    asyncio.run(run())
    assert events.closed


def test_index_rejects_later_batch_cardinality_mismatch_without_staging() -> None:
    async def run() -> None:
        rig = Rig()
        rig.encoder.output = (VECTOR,) * 32
        with pytest.raises(ValueError, match=r"^index embedding cardinality mismatch$"):
            await rig.indexer.index(corpus(33))
        assert [len(batch) for batch in rig.encoder.calls] == [32, 1]
        assert rig.events == ["lock", "recover", "pg-proof", "encode", "encode", "unlock"]
        assert rig.store.active_version == "previous-active"

    asyncio.run(run())
