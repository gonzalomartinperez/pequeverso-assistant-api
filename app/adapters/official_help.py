"""Optional fixed-ID public help reader; no visitor data, authentication or model tools."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import socket
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from html.parser import HTMLParser

import httpx

from app.domain.web_evidence import SOURCES, HelpSource, HelpTopic, WebEvidence

log = logging.getLogger(__name__)
FETCH_ORIGIN = 'https://api-help-center.bkf.hotmart.com'
MAX_BODY_BYTES = 64 * 1024
MAX_ARTICLE_CHARS = 2000
FRESH_SECONDS = 6 * 3600
FAILURE_COOLDOWN_SECONDS = 30
FETCH_TIMEOUT_SECONDS = 3.0


class _ArticleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.blocked: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {'script', 'style', 'form', 'iframe', 'object', 'noscript', 'svg'}:
            self.blocked.append(tag)
        if not self.blocked and tag in {'p', 'li', 'br', 'h1', 'h2', 'h3'}:
            self.parts.append('\n')

    def handle_endtag(self, tag: str) -> None:
        if self.blocked and tag == self.blocked[-1]:
            self.blocked.pop()
        if not self.blocked and tag in {'p', 'li', 'h1', 'h2', 'h3'}:
            self.parts.append('\n')

    def handle_data(self, data: str) -> None:
        if not self.blocked:
            self.parts.append(data)


def parse_article(raw: bytes, source: HelpSource, now: datetime) -> WebEvidence:
    """Response cannot change the fixed identity/title/citation, or become executable HTML."""
    if len(raw) > MAX_BODY_BYTES:
        raise ValueError('help body too large')
    data = json.loads(raw)
    if (
        not isinstance(data, dict)
        or type(data.get('id')) is not int
        or str(data['id']) != source.article_id
        or data.get('locale') != 'es-es'
        or data.get('outdated') is not False
        or not isinstance(data.get('body'), str)
        or not isinstance(data.get('title'), str)
        or not 5 <= len(data['title']) <= 200
        or not 80 <= len(data['body']) <= MAX_BODY_BYTES
    ):
        raise ValueError('help article identity or content invalid')
    parser = _ArticleText()
    parser.feed(data['body'])
    parser.close()
    text = '\n'.join(' '.join(part.split()) for part in ''.join(parser.parts).splitlines() if part.strip())
    if not 80 <= len(text) <= MAX_BODY_BYTES:
        raise ValueError('help article has no usable text')
    # Never hand the model broken HTML or URLs from upstream; only the fixed structured citation
    # is navigable. URLs in ordinary source text remain untrusted and final URL rules still apply.
    text = text[:MAX_ARTICLE_CHARS]
    digest = hashlib.sha256(f'{source.article_id}\n{text}'.encode()).hexdigest()
    return WebEvidence(source, text, digest, now)


async def resolve_fixed_host() -> tuple[str, ...]:
    addresses = await asyncio.get_running_loop().getaddrinfo(
        'api-help-center.bkf.hotmart.com', 443, type=socket.SOCK_STREAM
    )
    return tuple({str(item[4][0]) for item in addresses})


def validate_public_addresses(addresses: tuple[str, ...]) -> None:
    if not addresses:
        raise ValueError('help DNS unavailable')
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global or ip.is_multicast or ip.is_reserved:
            raise ValueError('help DNS resolved a nonpublic address')


class OfficialHelpReader:
    """Three public cache keys, single-flight refresh, no stale-on-error or background retries.

    DNS is checked for public addresses before HTTP. TLS verifies the trusted fixed hostname.
    HTTP resolves again: this check is NOT DNS pinning and has a documented race residual.
    This is NOT a DNS-pinned transport: vps-ops must restrict egress to the fixed HTTPS origin.
    Fixed IDs prevent a visitor from selecting an SSRF target; no generic URL method exists.
    """

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        dns_resolver: Callable[[], Awaitable[tuple[str, ...]]] = resolve_fixed_host,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._transport = transport
        self._dns_resolver = dns_resolver
        self._monotonic = monotonic
        self._now = now
        self._cache: dict[HelpTopic, tuple[float, WebEvidence | None]] = {}
        self._locks = {source.topic: asyncio.Lock() for source in SOURCES}

    async def read(self, topics: tuple[HelpTopic, ...]) -> tuple[WebEvidence, ...]:
        selected = tuple(source for source in SOURCES if source.topic in topics)
        try:
            async with asyncio.timeout(FETCH_TIMEOUT_SECONDS):
                results = await asyncio.gather(*(self._one(source) for source in selected))
        except TimeoutError:
            expiry = self._monotonic() + FAILURE_COOLDOWN_SECONDS
            for source in selected:
                self._cache[source.topic] = (expiry, None)
            log.info('{"operation":"official_help","outcome":"timeout"}')
            return ()
        return tuple(item for item in results if item is not None)

    async def _one(self, source: HelpSource) -> WebEvidence | None:
        async with self._locks[source.topic]:
            cached = self._cache.get(source.topic)
            now = self._monotonic()
            if cached and now < cached[0]:
                log.info(
                    '{"operation":"official_help","outcome":"cache_hit","topic":"%s"}', source.topic.value
                )
                return cached[1]
            try:
                validate_public_addresses(await self._dns_resolver())
                async with (
                    httpx.AsyncClient(
                        timeout=FETCH_TIMEOUT_SECONDS,
                        follow_redirects=False,
                        trust_env=False,
                        transport=self._transport,
                    ) as client,
                    client.stream(
                        'GET',
                        f'{FETCH_ORIGIN}/articles/{source.article_id}',
                        headers={
                            'Accept': 'application/json',
                            'Accept-Language': 'es',
                            'Accept-Encoding': 'identity',
                        },
                    ) as response,
                ):
                    if response.status_code != 200:
                        raise ValueError('help status unavailable')
                    if response.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
                        raise ValueError('help response is not JSON')
                    if response.headers.get('content-encoding', 'identity').lower() != 'identity':
                        raise ValueError('compressed help responses are not accepted')
                    body = bytearray()
                    # Only identity encoding is accepted, so a decompression bomb is rejected before decoding.
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_BODY_BYTES:
                            raise ValueError('help body too large')
                    evidence = parse_article(bytes(body), source, self._now())
            except (httpx.HTTPError, ValueError, UnicodeError, OSError):
                self._cache[source.topic] = (now + FAILURE_COOLDOWN_SECONDS, None)
                log.info(
                    '{"operation":"official_help","outcome":"unavailable","topic":"%s"}', source.topic.value
                )
                return None
            self._cache[source.topic] = (now + FRESH_SECONDS, evidence)
            log.info('{"operation":"official_help","outcome":"verified","topic":"%s"}', source.topic.value)
            return evidence
