"""OpenAI adapter against a fake SDK client: request shape, event mapping, bounded retries."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest

from app.adapters.openai_provider import OpenAIResponsesProvider
from app.ai.prompt import OUTPUT_SCHEMA
from app.ai.provider import ModelInput, ModelRequest, TextChunk, UsageChunk
from app.domain.errors import FailureCode, RejectedError

REQUEST = ModelRequest(
    'instructions', (ModelInput('user', 'store_data:\n{}'),), OUTPUT_SCHEMA, 800, 'sid', 'ck'
)


class _Events:
    def __init__(self, events: list[Any]) -> None:
        self._events = events
        self.closed = False

    def __aiter__(self) -> _Events:
        return self

    async def __anext__(self) -> Any:
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)

    async def close(self) -> None:
        self.closed = True


class _Client:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, Any]] = []
        self.responses = self

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _usage() -> Any:
    return SimpleNamespace(
        input_tokens=900,
        output_tokens=120,
        input_tokens_details=SimpleNamespace(cached_tokens=600, cache_write_tokens=0),
    )


def _completed() -> Any:
    return SimpleNamespace(type='response.completed', response=SimpleNamespace(usage=_usage()))


def _collect(provider: OpenAIResponsesProvider) -> list[Any]:
    async def run() -> list[Any]:
        return [chunk async for chunk in provider.stream(REQUEST)]

    return asyncio.run(run())


def _server_error() -> openai.InternalServerError:
    response = httpx.Response(500, request=httpx.Request('POST', 'https://api.openai.com/v1/responses'))
    return openai.InternalServerError('boom', response=response, body=None)


def test_request_shape_and_event_mapping() -> None:
    events = _Events(
        [
            SimpleNamespace(type='response.output_text.delta', delta='{"answer":"ho'),
            SimpleNamespace(type='response.output_text.delta', delta='la"}'),
            _completed(),
        ]
    )
    client = _Client([events])
    chunks = _collect(OpenAIResponsesProvider(client, 'gpt-6-luna', 'low', max_retries=1))  # type: ignore[arg-type]
    assert [c.text for c in chunks if isinstance(c, TextChunk)] == ['{"answer":"ho', 'la"}']
    usage = next(c.usage for c in chunks if isinstance(c, UsageChunk))
    assert (usage.input_tokens, usage.cached_input_tokens, usage.output_tokens) == (900, 600, 120)
    call = client.calls[0]
    assert call['model'] == 'gpt-6-luna' and call['store'] is False and call['stream'] is True
    assert call['service_tier'] == 'default'
    assert call['text']['format']['strict'] is True and call['max_output_tokens'] == 800
    assert call['reasoning'] == {'effort': 'low'} and call['safety_identifier'] == 'sid'
    assert events.closed


def test_retries_only_before_a_stream_opens() -> None:
    client = _Client([_server_error(), _Events([_completed()])])
    provider = OpenAIResponsesProvider(client, 'm', 'low', max_retries=1, retry_backoff_seconds=0)  # type: ignore[arg-type]
    _collect(provider)
    assert len(client.calls) == 2
    client = _Client([_server_error(), _server_error()])
    provider = OpenAIResponsesProvider(client, 'm', 'low', max_retries=1, retry_backoff_seconds=0)  # type: ignore[arg-type]
    with pytest.raises(RejectedError) as error:
        _collect(provider)
    assert error.value.code is FailureCode.PROVIDER_UNAVAILABLE and len(client.calls) == 2


@pytest.mark.parametrize(
    ('events', 'code'),
    [
        ([SimpleNamespace(type='response.refusal.delta', delta='no')], FailureCode.GENERATION_FAILED),
        ([SimpleNamespace(type='response.incomplete')], FailureCode.GENERATION_FAILED),
        ([SimpleNamespace(type='response.output_text.delta', delta='{')], FailureCode.PROVIDER_UNAVAILABLE),
    ],
)
def test_failed_or_truncated_streams_are_rejected_and_closed(events: list[Any], code: FailureCode) -> None:
    stream = _Events(events)
    provider = OpenAIResponsesProvider(_Client([stream]), 'm', 'low', max_retries=0)  # type: ignore[arg-type]
    with pytest.raises(RejectedError) as error:
        _collect(provider)
    assert error.value.code is code
    assert stream.closed


def test_authentication_errors_are_not_retried() -> None:
    response = httpx.Response(401, request=httpx.Request('POST', 'https://api.openai.com/v1/responses'))
    client = _Client([openai.AuthenticationError('bad key', response=response, body=None)])
    with pytest.raises(RejectedError):
        _collect(OpenAIResponsesProvider(client, 'm', 'low', max_retries=2))  # type: ignore[arg-type]
    assert len(client.calls) == 1


def test_incomplete_responses_still_report_usage_with_reasoning_tokens() -> None:
    usage = SimpleNamespace(
        input_tokens=900,
        output_tokens=800,
        input_tokens_details=SimpleNamespace(cached_tokens=0, cache_write_tokens=0),
        output_tokens_details=SimpleNamespace(reasoning_tokens=800),
    )
    incomplete = SimpleNamespace(
        type='response.incomplete',
        response=SimpleNamespace(usage=usage, incomplete_details=SimpleNamespace(reason='max_output_tokens')),
    )
    events = _Events([incomplete])
    provider = OpenAIResponsesProvider(_Client([events]), 'gpt-6-luna', 'medium', max_retries=0)  # type: ignore[arg-type]
    chunks: list[Any] = []

    async def run() -> None:
        async for chunk in provider.stream(REQUEST):
            chunks.append(chunk)

    with pytest.raises(RejectedError) as raised:
        asyncio.run(run())
    assert raised.value.code is FailureCode.GENERATION_FAILED
    assert [c.usage.reasoning_tokens for c in chunks if isinstance(c, UsageChunk)] == [800]
    assert events.closed


def test_reasoning_effort_is_sent_as_configured() -> None:
    client = _Client([_Events([_completed()])])
    provider = OpenAIResponsesProvider(client, 'gpt-6-luna', 'medium', max_retries=0)  # type: ignore[arg-type]
    _collect(provider)
    assert client.calls[0]['reasoning'] == {'effort': 'medium'} and client.calls[0]['model'] == 'gpt-6-luna'


def test_runtime_timeout_dispatches_once_and_retains_unknown_reservation(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3
    from contextlib import closing

    from app.bootstrap import container
    from tests.support import ask, client, open_session

    sdk = _Client(
        [openai.APITimeoutError(request=httpx.Request('POST', 'https://api.openai.com/v1/responses'))]
    )
    options = []

    def factory(**kwargs: Any) -> Any:
        options.append(kwargs)
        return sdk

    monkeypatch.setattr(container, 'AsyncOpenAI', factory)
    with client(tmp_path, ai_provider='openai', allow_paid_ai=True, openai_api_key='synthetic-key') as c:
        status, events, error = ask(c, open_session(c), '¿Qué incluye el kit?')
        assert status == 200 and error is None
        assert events[-1]['type'] == 'run.failed'
        assert events[-1]['code'] == 'provider_unavailable'
    assert options[0]['max_retries'] == 0
    assert options[0]['base_url'] == 'https://api.openai.com/v1'
    assert len(sdk.calls) == 1
    with closing(sqlite3.connect(tmp_path / 'test.sqlite3')) as db:
        reserved, actual, state = db.execute(
            'SELECT reserved_micro, actual_micro, status FROM spend_ledger'
        ).fetchone()
        assert reserved > 0 and actual is None and state == 'unreported'


def test_runtime_retries_fail_closed() -> None:
    from pydantic import ValidationError

    from app.bootstrap.config import Settings

    assert Settings(_env_file=None).openai_max_retries == 0
    with pytest.raises(ValidationError):
        Settings(_env_file=None, openai_max_retries=1)


def test_input_bound_accounts_for_schema_roles_unicode_and_protocol() -> None:
    import json

    request = ModelRequest(
        'instrucción🙂',
        (ModelInput('user', 'niño'),),
        {'description': 'á🙂' * 1000},
        4000,
        'opaque',
        'catalog',
    )
    expected = {
        'instructions': request.instructions,
        'input': [{'role': 'user', 'content': 'niño', 'type': 'message'}],
        'schema': request.output_schema,
    }
    assert request.size_bytes() == len(json.dumps(expected, ensure_ascii=False).encode()) + 1024
    assert request.size_bytes() > len(request.instructions.encode()) + len('niño'.encode()) + 6000


def test_oversize_schema_is_refused_before_any_model_call(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ai import composer
    from tests.support import ScriptedProvider, answer_json, ask, client, open_session

    monkeypatch.setattr(composer, 'OUTPUT_SCHEMA', {'description': '🙂' * 7000})
    provider = ScriptedProvider(answer_json('Respuesta sintética.'))
    with client(tmp_path, provider=provider) as c:
        status, events, error = ask(c, open_session(c), '¿Qué incluye el kit?')
        assert status == 422 and events == [] and error['error']['code'] == 'invalid_request'
    assert provider.calls == []
