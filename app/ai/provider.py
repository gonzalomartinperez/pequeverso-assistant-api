"""The model port used by the composer. Adapters (OpenAI, fixture) implement `ModelProvider`."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from app.domain.budget import Usage


@dataclass(frozen=True, slots=True)
class ModelInput:
    role: Literal['user', 'assistant']
    text: str


@dataclass(frozen=True, slots=True)
class ModelRequest:
    instructions: str
    inputs: tuple[ModelInput, ...]
    output_schema: dict[str, Any]
    max_output_tokens: int
    safety_identifier: str
    cache_key: str

    def size_bytes(self) -> int:
        """UTF-8 size of everything sent; an upper bound of the input token count."""
        return len(self.instructions.encode()) + sum(len(item.text.encode()) + 16 for item in self.inputs)


@dataclass(frozen=True, slots=True)
class TextChunk:
    text: str


@dataclass(frozen=True, slots=True)
class UsageChunk:
    usage: Usage


ModelChunk = TextChunk | UsageChunk


class ModelProvider(Protocol):
    @property
    def model(self) -> str: ...

    def stream(self, request: ModelRequest) -> AsyncGenerator[ModelChunk]:
        """Raw structured-output text chunks, then at most one usage report.

        Raises `RejectedError(PROVIDER_UNAVAILABLE | GENERATION_FAILED)`; closing the iterator
        cancels the upstream request.
        """
        ...
