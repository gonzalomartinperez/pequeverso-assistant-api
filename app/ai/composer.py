"""Grounded answer composition: evidence + bounded history + question → one provider call."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import AsyncGenerator
from dataclasses import dataclass, replace

from app.ai.evidence import catalog_payload, passages, rank
from app.ai.output import AnswerStreamParser
from app.ai.prompt import INSTRUCTIONS, OUTPUT_SCHEMA, PROMPT_VERSION
from app.ai.provider import ModelInput, ModelProvider, ModelRequest, TextChunk, UsageChunk
from app.application.ports import (
    ComposerEvent,
    DeltaEvent,
    DraftEvent,
    GenerationError,
    PreparedTurn,
    Turn,
)
from app.domain.answer_policy import fold
from app.domain.budget import Usage
from app.domain.catalog import DocumentKind
from app.domain.conversation import Role
from app.domain.errors import RejectedError
from app.domain.web_evidence import WebEvidence, evidence_payload

MAX_HISTORY_CHARS = 1200


def _mandatory_document(kind: DocumentKind, title: str, text: str) -> bool:
    if kind in (DocumentKind.POLICY, DocumentKind.SUPPORT):
        return True

    return (
        re.search(
            r'\b(?:garant\w*|reembols\w*|pago\w*|compra\w*|moneda|impuesto\w*|'
            r'entrega|acceso|hotmart|fisico|digital|resultad\w*)\b',
            fold(f'{title} {text}'),
        )
        is not None
    )


@dataclass(frozen=True, slots=True)
class ComposerSettings:
    max_output_tokens: int
    max_evidence_chars: int
    max_input_bytes: int = 24000


@dataclass(frozen=True, slots=True)
class PreparedRequest:
    request: ModelRequest
    web_evidence: tuple[WebEvidence, ...] = ()
    catalog_source_ids: frozenset[str] = frozenset()

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
        query = f'{turn.question} {last_user}'
        limit = (
            min(self._settings.max_input_bytes, turn.input_size_limit)
            if turn.input_size_limit is not None
            else self._settings.max_input_bytes
        )
        catalog = turn.active.catalog
        conversation = _conversation(turn)

        def evidence_text() -> str:
            mandatory_ids = frozenset(
                d.id for d in catalog.documents if _mandatory_document(d.kind, d.title, d.text)
            )
            return catalog_payload(
                catalog, turn.price_status, query, self._settings.max_evidence_chars, mandatory_ids
            )

        evidence = evidence_text()
        request = self._request(turn, evidence, conversation, ())
        # Keep all persisted history unchanged. Only old model-context text is removed,
        # retaining roles and structured reference ids plus the latest exchange.
        for entry in conversation[:-2]:
            if request.size_bytes() <= limit:
                break
            entry['text'] = ''
            request = self._request(turn, evidence, conversation, ())
        # Whole low-ranked documents only: commercial and support evidence is mandatory.
        ranked = rank(query, passages(catalog))
        removable = [
            p.id.removeprefix('document:')
            for p, _ in reversed(ranked)
            if p.id.startswith('document:')
            and (document := catalog.document(p.id.removeprefix('document:'))) is not None
            and not _mandatory_document(document.kind, document.title, document.text)
        ]
        for document_id in removable:
            if request.size_bytes() <= limit:
                break
            catalog = replace(catalog, documents=tuple(d for d in catalog.documents if d.id != document_id))
            evidence = evidence_text()
            request = self._request(turn, evidence, conversation, ())
        if request.size_bytes() > limit and conversation and conversation[-1]['role'] == Role.ASSISTANT.value:
            original_text = str(conversation[-1]['text'])
            # Preserve a useful complete-sentence prefix and every structured reference id;
            # never mutate the stored message or slice through its final qualification.
            ends = [m.end() for m in re.finditer(r'[.!?](?=\s|$)', original_text)]
            for end in reversed(ends):
                conversation[-1]['text'] = original_text[:end]
                trial = self._request(turn, evidence, conversation, ())
                if trial.size_bytes() <= limit:
                    request = trial
                    break
            else:
                conversation[-1]['text'] = original_text
        selected: list[WebEvidence] = []
        if request.size_bytes() <= limit:
            for item in turn.web_evidence:
                kept: list[str] = []
                accepted: WebEvidence | None = None
                for paragraph in item.text.splitlines():
                    text = '\n'.join([*kept, paragraph])
                    candidate = replace(item, text=text, sha256=hashlib.sha256(text.encode()).hexdigest())
                    proposed = (*selected, candidate)
                    trial = self._request(turn, evidence, conversation, proposed)
                    if trial.size_bytes() > limit:
                        break
                    kept.append(paragraph)
                    accepted = candidate
                if accepted is not None:
                    selected.append(accepted)
            request = self._request(turn, evidence, conversation, tuple(selected))
        source_ids = frozenset(d['id'] for d in json.loads(evidence)['documents'])
        return PreparedRequest(request, tuple(selected), source_ids)

    def _request(
        self,
        turn: Turn,
        evidence: str,
        conversation: list[dict[str, object]],
        web_evidence: tuple[WebEvidence, ...],
    ) -> ModelRequest:
        question = json.dumps(
            {
                'page': turn.page,
                'reply_language': turn.language.value,
                'conversation': conversation,
                'question': turn.question,
                **(
                    {'visitor_context': turn.context.payload()}
                    if turn.context and not turn.context.empty
                    else {}
                ),
            },
            ensure_ascii=False,
            separators=(',', ':'),
        )
        web_inputs: tuple[ModelInput, ...] = ()
        if web_evidence:
            web_inputs = (ModelInput('user', f'official_platform_data:\n{evidence_payload(web_evidence)}'),)
        return ModelRequest(
            instructions=INSTRUCTIONS,
            inputs=(
                ModelInput('user', f'store_data:\n{evidence}'),
                *web_inputs,
                ModelInput('user', f'visitor_turn:\n{question}'),
            ),
            output_schema=OUTPUT_SCHEMA,
            max_output_tokens=self._settings.max_output_tokens,
            safety_identifier=turn.safety_identifier,
            cache_key=f'pequeverso-assistant:{PROMPT_VERSION}:{turn.active.sha256[:16]}',
        )

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
        except GenerationError:
            raise
        except RejectedError as error:
            raise GenerationError(error.code, usage) from error
        finally:
            await stream.aclose()
        try:
            draft = parser.finish()
        except RejectedError as error:
            raise GenerationError(error.code, usage) from error
        yield DraftEvent(draft, usage)
