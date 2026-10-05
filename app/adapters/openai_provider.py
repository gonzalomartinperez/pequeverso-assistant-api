"""OpenAI Responses API adapter (streaming, strict JSON-schema output, `store=False`).

Retries are bounded and happen only when the request failed before any stream opened
(connection errors, 429, 5xx), so a response that may have been billed is never repeated.
Usage is reported whenever the provider includes it, also on an incomplete or failed response
(reasoning can consume the whole output allowance before any text), so the ledger settles to
what was actually billed instead of keeping only the estimate.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any, cast

import openai
from openai import AsyncOpenAI
from openai.types.responses import EasyInputMessageParam, ResponseInputParam, ResponseTextConfigParam
from openai.types.shared_params import Reasoning

from app.ai.provider import ModelChunk, ModelRequest, TextChunk, UsageChunk
from app.domain.budget import Usage
from app.domain.errors import FailureCode, RejectedError

log = logging.getLogger(__name__)

_RETRYABLE = (openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError)


def _input(request: ModelRequest) -> ResponseInputParam:
    items: list[EasyInputMessageParam] = [
        {'role': item.role, 'content': item.text, 'type': 'message'} for item in request.inputs
    ]
    return list(items)


def _text_format(request: ModelRequest) -> ResponseTextConfigParam:
    return {
        'format': {
            'type': 'json_schema',
            'name': 'assistant_answer',
            'schema': request.output_schema,
            'strict': True,
        }
    }


def _reasoning(effort: str) -> Reasoning:
    return cast(Reasoning, {'effort': effort})


def usage_of(response: Any) -> Usage | None:
    """Provider usage as a domain value; None when absent or malformed (never guessed)."""
    usage = getattr(response, 'usage', None)
    if usage is None:
        return None
    try:
        inputs = getattr(usage, 'input_tokens_details', None)
        outputs = getattr(usage, 'output_tokens_details', None)
        return Usage(
            input_tokens=int(usage.input_tokens),
            output_tokens=int(usage.output_tokens),
            cached_input_tokens=int(getattr(inputs, 'cached_tokens', 0) or 0),
            cache_write_tokens=int(getattr(inputs, 'cache_write_tokens', 0) or 0),
            reasoning_tokens=int(getattr(outputs, 'reasoning_tokens', 0) or 0),
        )
    except (TypeError, ValueError):
        log.warning('{"operation":"provider_usage","outcome":"malformed"}')
        return None


class OpenAIResponsesProvider:
    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        reasoning_effort: str,
        max_retries: int,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        self._client = client
        self._model = model
        self._effort = reasoning_effort
        self._max_retries = max_retries
        self._backoff = retry_backoff_seconds

    @property
    def model(self) -> str:
        return self._model

    async def _open(self, request: ModelRequest) -> Any:
        attempt = 0
        while True:
            try:
                return await self._client.responses.create(
                    model=self._model,
                    instructions=request.instructions,
                    input=_input(request),
                    text=_text_format(request),
                    reasoning=_reasoning(self._effort),
                    max_output_tokens=request.max_output_tokens,
                    store=False,
                    stream=True,
                    prompt_cache_key=request.cache_key,
                    safety_identifier=request.safety_identifier,
                )
            except _RETRYABLE as error:
                if attempt >= self._max_retries:
                    log.warning(
                        '{"operation":"provider_open","outcome":"failed","error":"%s"}', type(error).__name__
                    )
                    raise RejectedError(FailureCode.PROVIDER_UNAVAILABLE) from error
                attempt += 1
                await asyncio.sleep(self._backoff * attempt)
            except openai.OpenAIError as error:
                log.warning(
                    '{"operation":"provider_open","outcome":"rejected","error":"%s"}', type(error).__name__
                )
                raise RejectedError(FailureCode.PROVIDER_UNAVAILABLE) from error

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelChunk]:
        events = await self._open(request)
        completed = False
        try:
            async for event in events:
                kind = getattr(event, 'type', '')
                if kind == 'response.output_text.delta':
                    yield TextChunk(event.delta)
                elif kind == 'response.completed':
                    completed = True
                    usage = usage_of(event.response)
                    if usage is not None:
                        yield UsageChunk(usage)
                elif kind in ('response.refusal.delta', 'response.refusal.done'):
                    raise RejectedError(FailureCode.GENERATION_FAILED)
                elif kind in ('response.failed', 'response.incomplete'):
                    response = getattr(event, 'response', None)
                    reason = getattr(getattr(response, 'incomplete_details', None), 'reason', None)
                    log.warning(
                        '{"operation":"provider_stream","outcome":"%s","reason":"%s"}', kind, reason or 'none'
                    )
                    usage = usage_of(response)
                    if usage is not None:
                        yield UsageChunk(usage)
                    raise RejectedError(FailureCode.GENERATION_FAILED)
                elif kind == 'error':
                    log.warning('{"operation":"provider_stream","outcome":"error"}')
                    raise RejectedError(FailureCode.GENERATION_FAILED)
        except openai.OpenAIError as error:
            raise RejectedError(FailureCode.PROVIDER_UNAVAILABLE) from error
        finally:
            await events.close()
        if not completed:
            raise RejectedError(FailureCode.PROVIDER_UNAVAILABLE)
