"""Installed dependency regressions; all credentials, files and transport are synthetic."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator
from contextlib import closing
from pathlib import Path
from typing import Any

import anyio
import anyio.lowlevel
import httpx2
import pytest
from openai import AsyncOpenAI
from pydantic import ValidationError

from app.adapters.openai_provider import OpenAIResponsesProvider
from app.ai.provider import TextChunk, UsageChunk
from app.bootstrap.config import Settings
from app.domain.errors import FailureCode, RejectedError
from tests.support import answer_json, ask, client, open_session
from tests.test_openai_provider import REQUEST


def clean_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


def test_explicit_utf8_dotenv_precedence_and_disabled_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clean_settings_environment(monkeypatch)
    env = tmp_path / 'synthetic.env'
    marker = 'synthetic-áéíóú-secret-never-used'
    env.write_text(f'MAX_OUTPUT_TOKENS=900\nOPENAI_API_KEY={marker}\n', encoding='utf-8')
    monkeypatch.setenv('MAX_OUTPUT_TOKENS', '1000')
    configured = Settings(_env_file=env)  # type: ignore[call-arg]
    assert configured.max_output_tokens == 1000
    assert configured.openai_api_key is not None
    assert configured.openai_api_key.get_secret_value() == marker
    assert marker not in repr(configured)
    monkeypatch.delenv('MAX_OUTPUT_TOKENS')
    assert Settings(_env_file=env).max_output_tokens == 900  # type: ignore[call-arg]
    disabled = Settings(_env_file=None)  # type: ignore[call-arg]
    assert disabled.max_output_tokens == 4000 and disabled.openai_api_key is None
    assert disabled.openai_model == 'gpt-6-luna' and disabled.openai_reasoning_effort == 'medium'
    assert disabled.openai_max_retries == 0 and not disabled.allow_paid_ai


def test_default_dotenv_does_not_search_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clean_settings_environment(monkeypatch)
    (tmp_path / '.env.local').write_text('ALLOW_PAID_AI=true\nMAX_OUTPUT_TOKENS=900\n')
    child = tmp_path / 'child'
    child.mkdir()
    monkeypatch.chdir(child)
    configured = Settings()
    assert not configured.allow_paid_ai and configured.max_output_tokens == 4000


def test_invalid_dotenv_configuration_redacts_input_and_retains_paid_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clean_settings_environment(monkeypatch)
    marker = 'SYNTHETIC_PRIVATE_INVALID_CONFIGURATION'
    env = tmp_path / 'synthetic.env'
    env.write_text(f'OPENAI_MAX_RETRIES={marker}\nOPENAI_API_KEY={marker}\n')
    with pytest.raises(ValidationError) as rejected:
        Settings(_env_file=env)  # type: ignore[call-arg]
    assert marker not in str(rejected.value)
    env.write_text('AI_PROVIDER=openai\nOPENAI_API_KEY=synthetic-unused\n')
    with pytest.raises(ValidationError, match='requires ALLOW_PAID_AI=true'):
        Settings(_env_file=env)  # type: ignore[call-arg]


def sse(kind: str, **data: object) -> bytes:
    return f'event: {kind}\ndata: {json.dumps({"type": kind, **data})}\n\n'.encode()


COMPLETE = sse(
    'response.completed',
    response={
        'usage': {
            'input_tokens': 100,
            'output_tokens': 10,
            'total_tokens': 110,
            'input_tokens_details': {'cached_tokens': 0},
            'output_tokens_details': {'reasoning_tokens': 2},
        }
    },
)


class SyntheticStream(httpx2.AsyncByteStream):
    def __init__(self, mode: str = 'buffered', text: str = 'respuesta sintética') -> None:
        self.mode = mode
        self.text = text
        self.tail_attempted = False
        self.tail_drained = False
        self.tail_started = asyncio.Event()
        self.close_count = 0
        self.closed = asyncio.Event()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield sse('response.output_text.delta', delta=self.text)
        if self.mode == 'timeout':
            raise httpx2.ReadTimeout('synthetic transport timeout')
        if self.mode == 'eof':
            return
        yield COMPLETE
        yield b'data: [DONE]\n\n'
        self.tail_attempted = True
        self.tail_started.set()
        if self.mode in ('slow', 'cancel'):
            await asyncio.Event().wait()
        yield b'unparsed trailing transport bytes'
        self.tail_drained = True

    async def aclose(self) -> None:
        # A checkpoint ensures cancellation shielding is exercised, rather than a synchronous fake.
        await anyio.lowlevel.checkpoint()
        self.close_count += 1
        self.closed.set()


def sdk_client(stream: SyntheticStream, version: str = 'HTTP/1.1'):
    requests: list[httpx2.Request] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(
            200,
            headers={'content-type': 'text/event-stream'},
            extensions={'http_version': version.encode()},
            stream=stream,
        )

    transport = httpx2.AsyncClient(transport=httpx2.MockTransport(respond))
    sdk = AsyncOpenAI(
        api_key='synthetic-unused-provider-key',
        base_url='https://api.openai.com/v1',
        max_retries=0,
        http_client=transport,
    )
    return sdk, transport, requests


@pytest.mark.parametrize('version', ['HTTP/1.1', 'HTTP/2'])
def test_installed_sdk_request_and_protocol_specific_completion_cleanup(version: str) -> None:
    async def scenario() -> None:
        stream = SyntheticStream()
        sdk, transport, requests = sdk_client(stream, version)
        try:
            provider = OpenAIResponsesProvider(sdk, 'gpt-6-luna', 'medium', max_retries=0)
            chunks = [chunk async for chunk in provider.stream(REQUEST)]
            assert [chunk.text for chunk in chunks if isinstance(chunk, TextChunk)] == ['respuesta sintética']
            usage = next(chunk.usage for chunk in chunks if isinstance(chunk, UsageChunk))
            assert (usage.input_tokens, usage.output_tokens, usage.reasoning_tokens) == (100, 10, 2)
            assert len(requests) == 1
            payload = json.loads(requests[0].content)
            assert payload['model'] == 'gpt-6-luna' and payload['reasoning'] == {'effort': 'medium'}
            assert payload['service_tier'] == 'default' and payload['store'] is False
            assert payload['stream'] is True and payload['max_output_tokens'] == REQUEST.max_output_tokens
            assert payload['text']['format']['strict'] is True
            assert payload['prompt_cache_key'] == REQUEST.cache_key
            assert payload['safety_identifier'] == REQUEST.safety_identifier
            assert not payload.get('tools') and sdk.max_retries == 0
            assert stream.close_count == 1
            assert stream.tail_attempted is (version == 'HTTP/1.1')
            assert stream.tail_drained is (version == 'HTTP/1.1')
            # The provider owns the response, not the borrowed SDK/transport client.
            assert not transport.is_closed
        finally:
            await sdk.close()
        assert transport.is_closed

    asyncio.run(scenario())


def test_installed_sdk_slow_http1_tail_has_bounded_drain_and_shielded_close() -> None:
    async def scenario() -> None:
        stream = SyntheticStream('slow')
        sdk, transport, requests = sdk_client(stream)
        try:
            provider = OpenAIResponsesProvider(sdk, 'gpt-6-luna', 'medium', max_retries=0)
            # An indefinitely stalled tail must finish; generous outer bound is not a latency claim.
            with anyio.fail_after(2):
                chunks = [chunk async for chunk in provider.stream(REQUEST)]
            assert any(isinstance(chunk, UsageChunk) for chunk in chunks)
            assert stream.tail_attempted and not stream.tail_drained
            assert stream.close_count == 1 and not transport.is_closed and len(requests) == 1
        finally:
            await sdk.close()

    asyncio.run(scenario())


@pytest.mark.parametrize('mode', ['eof', 'timeout'])
def test_installed_sdk_incomplete_transport_is_closed_without_retry(mode: str) -> None:
    async def scenario() -> None:
        stream = SyntheticStream(mode)
        sdk, transport, requests = sdk_client(stream)
        try:
            provider = OpenAIResponsesProvider(sdk, 'gpt-6-luna', 'medium', max_retries=0)
            with pytest.raises(RejectedError) as rejected:
                _ = [chunk async for chunk in provider.stream(REQUEST)]
            assert rejected.value.code is FailureCode.PROVIDER_UNAVAILABLE
            assert stream.close_count == 1 and len(requests) == 1 and not transport.is_closed
        finally:
            await sdk.close()

    asyncio.run(scenario())


def test_installed_sdk_cancellation_during_http1_drain_closes_response() -> None:
    async def scenario() -> None:
        stream = SyntheticStream('cancel')
        sdk, _, requests = sdk_client(stream)
        provider = OpenAIResponsesProvider(sdk, 'gpt-6-luna', 'medium', max_retries=0)

        async def consume() -> None:
            async for _chunk in provider.stream(REQUEST):
                pass

        try:
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(consume)
                with anyio.fail_after(2):
                    await stream.tail_started.wait()
                tasks.cancel_scope.cancel()
            assert stream.closed.is_set() and stream.close_count == 1 and len(requests) == 1
        finally:
            await sdk.close()

    asyncio.run(scenario())


def test_installed_sdk_caller_closes_partial_response_without_closing_borrowed_client() -> None:
    async def scenario() -> None:
        stream = SyntheticStream()
        sdk, transport, requests = sdk_client(stream)
        try:
            provider = OpenAIResponsesProvider(sdk, 'gpt-6-luna', 'medium', max_retries=0)
            generation = provider.stream(REQUEST)
            assert isinstance(await anext(generation), TextChunk)
            await generation.aclose()
            assert stream.close_count == 1 and len(requests) == 1
            assert not stream.tail_attempted and not transport.is_closed
        finally:
            await sdk.close()

    asyncio.run(scenario())


@pytest.mark.parametrize('mode', ['buffered', 'eof', 'timeout'])
def test_installed_sdk_through_session_csrf_sse_history_and_ledger(
    mode: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.bootstrap import container

    stream = SyntheticStream(mode, text=answer_json('Puedes conocer el kit en la tienda.'))
    sdk, transport, requests = sdk_client(stream)
    options: list[dict[str, Any]] = []

    def factory(**kwargs: Any) -> AsyncOpenAI:
        options.append(kwargs)
        return sdk

    monkeypatch.setattr(container, 'AsyncOpenAI', factory)
    with client(tmp_path, ai_provider='openai', allow_paid_ai=True, openai_api_key='synthetic-unused') as c:
        csrf = open_session(c)
        denied = c.post(
            '/api/v1/messages',
            headers={'Origin': 'http://localhost:3000', 'Idempotency-Key': 'synthetic-no-csrf'},
            json={'content': '¿Qué incluye Grafismo Fonético?'},
        )
        assert denied.status_code == 403 and requests == []
        status, events, error = ask(c, csrf, '¿Qué incluye Grafismo Fonético?', key='synthetic-sdk-once')
        assert status == 200 and error is None and len(requests) == 1
        assert events[-1]['type'] == ('run.completed' if mode == 'buffered' else 'run.failed')
        if mode != 'buffered':
            assert events[-1]['code'] == 'provider_unavailable'
        # Restoring a session must never dispatch another generation.
        restored = c.post('/api/v1/session', headers={'Origin': 'http://localhost:3000'}, json={})
        assert restored.status_code == 200 and len(requests) == 1
        messages = restored.json()['messages']
        assert len(messages) == (2 if mode == 'buffered' else 1)
        if mode == 'buffered':
            completed = next(event for event in events if event['type'] == 'message.completed')
            assert messages[-1]['content'] == completed['message']['content']
    assert transport.is_closed and stream.close_count == 1
    assert options[0]['max_retries'] == 0 and options[0]['base_url'] == 'https://api.openai.com/v1'
    with closing(sqlite3.connect(tmp_path / 'test.sqlite3')) as database:
        reserved, actual, state = database.execute(
            'SELECT reserved_micro, actual_micro, status FROM spend_ledger'
        ).fetchone()
        assert reserved > 0
        if mode == 'buffered':
            assert actual > 0 and state == 'settled'
        else:
            assert actual is None and state == 'unreported'
