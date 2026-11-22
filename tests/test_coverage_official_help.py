"""Official help handles malformed, oversized and slow replies with fake HTTP and DNS."""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from app.adapters import official_help
from app.domain.web_evidence import SOURCES, HelpTopic
from tests.test_official_help import _CLOCK, BODY, NOW, payload, public_dns, raw


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"x" * (official_help.MAX_BODY_BYTES + 1), "body too large"),
        (b"[]", "identity or content invalid"),
        (raw(title=123), "identity or content invalid"),
        (raw(body=123), "identity or content invalid"),
        (raw(body="<p>" + "x" * 2001 + "</p>"), "no bounded complete excerpt"),
    ],
)
def test_article_requires_bounded_complete_public_text(body, message):
    with pytest.raises(ValueError, match=message):
        official_help.parse_article(body, SOURCES[0], NOW)


def test_excerpt_drops_an_entire_paragraph_when_adding_it_would_exceed_the_cap():
    result = official_help.parse_article(
        raw(body=BODY + "<p>" + "x" * 2000 + " Condición importante.</p>"),
        SOURCES[0],
        NOW,
    )
    assert result.text == BODY.removeprefix("<p>").removesuffix("</p>")


@pytest.mark.parametrize(
    ("response", "retry_after"),
    [
        (lambda: httpx.Response(200, text="not JSON"), 30),
        (
            lambda: httpx.Response(
                200,
                stream=httpx.ByteStream(b"ignored"),
                headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
            ),
            30,
        ),
        (
            lambda: httpx.Response(
                200,
                content=b"x" * (official_help.MAX_BODY_BYTES + 1),
                headers={"Content-Type": "application/json"},
            ),
            30,
        ),
    ],
    ids=["content-type", "compressed", "oversized"],
)
def test_unusable_http_response_is_suppressed_until_cooldown(response, retry_after):
    ticks = [0.0]
    calls = []

    def handle(request):
        calls.append(request.url.path)
        return response() if len(calls) == 1 else httpx.Response(200, json=payload())

    async def run():
        reader = official_help.OfficialHelpReader(
            clock=_CLOCK,
            transport=httpx.MockTransport(handle),
            dns_resolver=public_dns,
            monotonic=lambda: ticks[0],
        )
        assert await reader.read((HelpTopic.DELIVERY,)) == ()
        ticks[0] = retry_after - 1
        assert await reader.read((HelpTopic.DELIVERY,)) == ()
        assert len(calls) == 1
        ticks[0] = retry_after
        recovered = await reader.read((HelpTopic.DELIVERY,))
        assert [item.source for item in recovered] == [SOURCES[0]]

    asyncio.run(run())
    assert calls == ["/articles/209033897", "/articles/209033897"]


def test_batch_timeout_cools_down_each_topic_and_cancels_pending_resolution(monkeypatch):
    monkeypatch.setattr(official_help, "FETCH_TIMEOUT_SECONDS", 0)
    resolved = AsyncMock(side_effect=AssertionError("timeout must cancel before DNS executes"))
    transport = httpx.MockTransport(lambda _request: pytest.fail("HTTP reached after timeout"))
    ticks = [0.0]

    async def run():
        reader = official_help.OfficialHelpReader(
            clock=_CLOCK, transport=transport, dns_resolver=resolved, monotonic=lambda: ticks[0]
        )
        selected = (HelpTopic.DELIVERY, HelpTopic.REFUND)
        assert await reader.read(selected) == ()
        monkeypatch.setattr(official_help, "FETCH_TIMEOUT_SECONDS", 3)
        ticks[0] = 29.0
        assert await reader.read((HelpTopic.DELIVERY,)) == ()
        assert await reader.read((HelpTopic.REFUND,)) == ()

    asyncio.run(run())
    resolved.assert_not_awaited()
