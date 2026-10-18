"""Pinned real SDK/HTTP transport without sockets, provider keys or paid requests."""

import asyncio
import ssl
from contextlib import AsyncExitStack
from typing import Any

import httpx2
import pytest
from openai import APIStatusError, AsyncOpenAI, DefaultAsyncHttpxClient

from app.bootstrap import container, provider_transport
from app.bootstrap.config import Settings


@pytest.mark.parametrize('status', [307, 308])
@pytest.mark.parametrize('endpoint', ['responses', 'embeddings'])
def test_sdk_never_forwards_private_payload_to_a_redirect_origin(
    monkeypatch: pytest.MonkeyPatch, status: int, endpoint: str
) -> None:
    seen: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(
            status,
            headers={'Location': 'https://untrusted.invalid/collect'},
            json={'error': {'message': 'synthetic redirect'}},
        )

    def factory(**kwargs: Any) -> DefaultAsyncHttpxClient:
        assert kwargs == {'verify': True, 'follow_redirects': False, 'trust_env': False}
        return DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handle), **kwargs)

    monkeypatch.setattr(provider_transport, 'DefaultAsyncHttpxClient', factory)

    async def run() -> None:
        http = provider_transport.provider_http_client()
        client = AsyncOpenAI(
            api_key='synthetic-not-a-real-key',
            base_url='https://api.openai.com/v1',
            max_retries=0,
            http_client=http,
        )
        try:

            async def send() -> None:
                if endpoint == 'responses':
                    await client.responses.create(model='gpt-6-luna', input='private-fixture-message')
                else:
                    await client.embeddings.create(
                        model='text-embedding-3-small', input=['private-fixture-message']
                    )

            with pytest.raises(APIStatusError) as raised:
                await send()
            assert raised.value.status_code == status
            assert len(seen) == 1
            assert seen[0].url.host == 'api.openai.com'
            assert b'private-fixture-message' in seen[0].content
            assert all(request.url.host != 'untrusted.invalid' for request in seen)
        finally:
            await provider_transport.close_owned_provider(client, http)
        assert http.is_closed

    asyncio.run(run())


def test_actual_tls_profile_ignores_ambient_proxy_and_ca_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:9')
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:9')
    monkeypatch.setenv('ALL_PROXY', 'http://127.0.0.1:9')
    monkeypatch.setenv('SSL_CERT_FILE', '/nonexistent-fixture-only-ca.pem')
    monkeypatch.setenv('SSL_CERT_DIR', '/nonexistent-fixture-only-ca-directory')

    async def run() -> None:
        http = provider_transport.provider_http_client()
        try:
            assert not http.trust_env and not http.follow_redirects
            assert not http._mounts  # No ambient proxy mounts were created.
            assert isinstance(http._transport, httpx2.AsyncHTTPTransport)
            context = http._transport._pool._ssl_context
            assert isinstance(context, ssl.SSLContext)
            assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
        finally:
            await provider_transport.close_provider_transport(http)

    asyncio.run(run())


def test_sdk_close_failure_still_closes_actual_http_and_independent_resources(
    caplog: pytest.LogCaptureFixture,
) -> None:
    order: list[str] = []

    class BrokenClose(AsyncOpenAI):
        async def close(self) -> None:
            order.append('sdk')
            raise RuntimeError('private-close-canary')

    async def run() -> None:
        http = provider_transport.provider_http_client()
        client = BrokenClose(api_key='synthetic-not-a-real-key', http_client=http, max_retries=0)

        async def close_database() -> None:
            order.append('database')

        async def close_everything() -> None:
            async with AsyncExitStack() as stack:
                stack.push_async_callback(close_database)
                stack.push_async_callback(provider_transport.close_owned_provider, client, http)

        with pytest.raises(RuntimeError, match='private-close-canary'):
            await close_everything()
        assert http.is_closed and order == ['sdk', 'database']

    asyncio.run(run())
    assert 'private-close-canary' not in caplog.text and 'synthetic-not-a-real-key' not in caplog.text


def test_sdk_failure_after_http_close_does_not_close_transport_twice() -> None:
    class CountingHttp(DefaultAsyncHttpxClient):
        closes = 0

        async def aclose(self) -> None:
            self.closes += 1
            await super().aclose()

    class ClosedThenFailed(AsyncOpenAI):
        async def close(self) -> None:
            await super().close()
            raise RuntimeError('synthetic SDK close failure after closure')

    async def run() -> None:
        http = CountingHttp(verify=True, trust_env=False, follow_redirects=False)
        client = ClosedThenFailed(api_key='synthetic-not-a-real-key', http_client=http, max_retries=0)
        with pytest.raises(RuntimeError, match='after closure'):
            await provider_transport.close_owned_provider(client, http)
        assert http.is_closed and http.closes == 1

    asyncio.run(run())


def test_fixture_provider_allocates_no_sdk_or_http_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError('fixture mode must never construct a provider transport')

    monkeypatch.setattr(container, 'AsyncOpenAI', forbidden)
    monkeypatch.setattr(container, 'provider_http_client', forbidden)
    settings = Settings(_env_file=None, ai_provider='fixture', allow_paid_ai=False, openai_api_key=None)
    resource = container.build_provider(settings)
    assert resource.close is None and resource.provider.model == 'fixture'
