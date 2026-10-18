"""Bounded embeddings adapters. Provider accounting precedes every non-retried request.

The SDK client is borrowed from composition; this adapter never closes it or enables tracing.
Hash fixtures exercise storage/transport only and are not semantic embedding evidence.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re

from openai import AsyncOpenAI

from app.application.knowledge_ports import EmbeddingAccounting
from app.domain.errors import FailureCode, RejectedError
from app.domain.knowledge import EmbeddingPurpose, EmbeddingSpec, validate_vector

MAX_EMBEDDING_BATCH = 32
MAX_EMBEDDING_TEXT_BYTES = 8000
MAX_EMBEDDING_BATCH_BYTES = 240_000


def _input_bound(texts: tuple[str, ...]) -> int:
    if not texts or len(texts) > MAX_EMBEDDING_BATCH:
        raise ValueError('embedding batch must contain between one and 32 texts')
    sizes = [len(text.encode('utf-8')) for text in texts]
    if any(not text.strip() for text in texts) or any(size > MAX_EMBEDDING_TEXT_BYTES for size in sizes):
        raise ValueError('embedding texts must be nonempty and at most 8000 UTF-8 bytes')
    total = sum(sizes)
    if total > MAX_EMBEDDING_BATCH_BYTES:
        raise ValueError('embedding batch exceeds its UTF-8 byte bound')
    # Byte-level tokens cannot exceed UTF-8 bytes; this is a conservative reservation, not usage.
    return total


class OpenAIEmbeddings:
    def __init__(self, client: AsyncOpenAI, accounting: EmbeddingAccounting) -> None:
        self._client = client.with_options(max_retries=0, timeout=10.0)
        self._accounting = accounting
        self._spec = EmbeddingSpec('openai', 'text-embedding-3-small', 1536)

    @property
    def spec(self) -> EmbeddingSpec:
        return self._spec

    async def encode(
        self, texts: tuple[str, ...], purpose: EmbeddingPurpose
    ) -> tuple[tuple[float, ...], ...]:
        bound = _input_bound(texts)
        operation = await self._accounting.reserve(bound, purpose)
        try:
            response = await self._client.embeddings.create(
                input=list(texts),
                model=self.spec.model,
                dimensions=self.spec.dimensions,
                encoding_format='float',
            )
            usage = response.usage
            if (
                type(usage.prompt_tokens) is not int
                or type(usage.total_tokens) is not int
                or not 0 <= usage.prompt_tokens == usage.total_tokens <= bound
            ):
                raise ValueError('embedding usage is missing or outside the reserved bound')
            # A malformed vector does not undo known billed usage.
            await self._accounting.settle(operation, usage.prompt_tokens)
            if response.model != self.spec.model or len(response.data) != len(texts):
                raise ValueError('embedding response identity or cardinality mismatch')
            by_index: dict[int, tuple[float, ...]] = {}
            for item in response.data:
                if type(item.index) is not int or item.index in by_index or not 0 <= item.index < len(texts):
                    raise ValueError('embedding response indices must be unique and complete')
                vector = tuple(item.embedding)
                validate_vector(vector, self.spec)
                by_index[item.index] = vector
            return tuple(by_index[index] for index in range(len(texts)))
        except asyncio.CancelledError:
            await asyncio.shield(self._accounting.mark_unreported(operation))
            raise
        except Exception as error:
            await asyncio.shield(self._accounting.mark_unreported(operation))
            # Provider exception strings may contain request data. Only a safe public code escapes.
            raise RejectedError(FailureCode.PROVIDER_UNAVAILABLE) from error


class FixtureHashEmbeddings:
    @property
    def spec(self) -> EmbeddingSpec:
        return EmbeddingSpec('fixture', 'hash64-v1', 64)

    async def encode(
        self, texts: tuple[str, ...], purpose: EmbeddingPurpose
    ) -> tuple[tuple[float, ...], ...]:
        _input_bound(texts)
        result: list[tuple[float, ...]] = []
        for text in texts:
            values = [0.0] * self.spec.dimensions
            for token in re.findall(r'\w+', text.casefold()) or [text]:
                digest = hashlib.sha256(token.encode()).digest()
                values[int.from_bytes(digest[:2]) % self.spec.dimensions] += 1.0
            norm = math.hypot(*values)
            vector = tuple(value / norm for value in values)
            validate_vector(vector, self.spec)
            result.append(vector)
        return tuple(result)
