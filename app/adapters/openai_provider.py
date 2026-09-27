"""OpenAI Responses API adapter (streaming, strict JSON-schema output, `store=False`).

Retries are bounded and happen only when the request failed before any stream opened
(connection errors, 429, 5xx), so a response that may have been billed is never repeated.
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
                    usage = getattr(event.response, 'usage', None)
                    if usage is not None:
                        details = getattr(usage, 'input_tokens_details', None)
                        yield UsageChunk(
                            Usage(
                                input_tokens=usage.input_tokens,
                                output_tokens=usage.output_tokens,
                                cached_input_tokens=getattr(details, 'cached_tokens', 0) or 0,
                                cache_write_tokens=getattr(details, 'cache_write_tokens', 0) or 0,
                            )
                        )
                elif kind in ('response.refusal.delta', 'response.refusal.done'):
                    raise RejectedError(FailureCode.GENERATION_FAILED)
                elif kind in ('response.failed', 'response.incomplete', 'error'):
                    log.warning('{"operation":"provider_stream","outcome":"%s"}', kind)
                    raise RejectedError(FailureCode.GENERATION_FAILED)
        except openai.OpenAIError as error:
            raise RejectedError(FailureCode.PROVIDER_UNAVAILABLE) from error
        finally:
            await events.close()
        if not completed:
            raise RejectedError(FailureCode.PROVIDER_UNAVAILABLE)
