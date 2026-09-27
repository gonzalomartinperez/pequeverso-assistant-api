"""Grounded answer composition: evidence + bounded history + question → one provider call."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from app.ai.evidence import catalog_payload
from app.ai.output import AnswerStreamParser
from app.ai.prompt import INSTRUCTIONS, OUTPUT_SCHEMA, PROMPT_VERSION
from app.ai.provider import ModelInput, ModelProvider, ModelRequest, TextChunk, UsageChunk
from app.application.ports import ComposerEvent, DeltaEvent, DraftEvent, PreparedTurn, Turn
from app.domain.budget import Usage
from app.domain.conversation import Role

MAX_HISTORY_CHARS = 1200


@dataclass(frozen=True, slots=True)
class ComposerSettings:
    max_output_tokens: int
    max_evidence_chars: int


@dataclass(frozen=True, slots=True)
class PreparedRequest:
    request: ModelRequest

    @property
    def input_size_bytes(self) -> int:
        return self.request.size_bytes()


def _conversation(turn: Turn) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for message in turn.history:
        entry: dict[str, object] = {'role': message.role.value, 'text': message.content[:MAX_HISTORY_CHARS]}
        if message.role is Role.ASSISTANT:
            referenced = [p.id for p in message.details.products] + [r.id for r in message.details.resources]
            if referenced:
                entry['referenced_ids'] = referenced
        entries.append(entry)
    return entries


class GroundedComposer:
    def __init__(self, provider: ModelProvider, settings: ComposerSettings) -> None:
        self._provider = provider
        self._settings = settings

    @property
    def model(self) -> str:
        return self._provider.model

    def prepare(self, turn: Turn) -> PreparedTurn:
        last_user = next((m.content for m in reversed(turn.history) if m.role is Role.USER), '')
        evidence = catalog_payload(
            turn.active.catalog,
            turn.price_status,
            f'{turn.question} {last_user}',
            self._settings.max_evidence_chars,
        )
        question = json.dumps(
            {'page': turn.page, 'conversation': _conversation(turn), 'question': turn.question},
            ensure_ascii=False,
            separators=(',', ':'),
        )
        request = ModelRequest(
            instructions=INSTRUCTIONS,
            inputs=(
                ModelInput('user', f'store_data:\n{evidence}'),
                ModelInput('user', f'visitor_turn:\n{question}'),
            ),
            output_schema=OUTPUT_SCHEMA,
            max_output_tokens=self._settings.max_output_tokens,
            safety_identifier=turn.safety_identifier,
            cache_key=f'pequeverso-assistant:{PROMPT_VERSION}:{turn.active.sha256[:16]}',
        )
        return PreparedRequest(request)

    async def compose(self, prepared: PreparedTurn) -> AsyncGenerator[ComposerEvent]:
        assert isinstance(prepared, PreparedRequest)
        parser = AnswerStreamParser()
        usage: Usage | None = None
        stream = self._provider.stream(prepared.request)
        try:
            async for chunk in stream:
                if isinstance(chunk, TextChunk):
                    delta = parser.feed(chunk.text)
                    if delta:
                        yield DeltaEvent(delta)
                elif isinstance(chunk, UsageChunk):
                    usage = chunk.usage
        finally:
            await stream.aclose()
        yield DraftEvent(parser.finish(), usage)
