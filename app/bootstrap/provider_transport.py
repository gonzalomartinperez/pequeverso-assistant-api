"""Explicit owned provider HTTP profile; credentials/payloads cannot follow redirects or ambient proxies."""

from __future__ import annotations

from typing import Protocol

from openai import DefaultAsyncHttpxClient


class _ClosableProvider(Protocol):
    async def close(self) -> None: ...


def provider_http_client() -> DefaultAsyncHttpxClient:
    # Preserve SDK defaults for protocols, connection limits and timeouts. Only the
    # destination/TLS/environment boundary changes; there is no user-configurable gateway.
    return DefaultAsyncHttpxClient(verify=True, follow_redirects=False, trust_env=False)


async def close_provider_transport(http: DefaultAsyncHttpxClient) -> None:
    if not http.is_closed:
        await http.aclose()


async def close_owned_provider(client: _ClosableProvider, http: DefaultAsyncHttpxClient) -> None:
    """SDK failure cannot skip closing its owned transport; borrowed providers never use this."""
    try:
        await client.close()
    finally:
        await close_provider_transport(http)
