"""Grounded answer composition: evidence + bounded history + question → one provider call."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field, replace

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
from app.domain.catalog import DocumentKind, mentioned_products
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


@dataclass(frozen=True, slots=True, repr=False)
class PreparedRequest:
    request: ModelRequest
    web_evidence: tuple[WebEvidence, ...] = ()
    catalog_source_ids: frozenset[str] = frozenset()
    dispatch: _Dispatch = field(default_factory=lambda: _Dispatch(), compare=False, repr=False)

    @property
    def input_size_bytes(self) -> int:
        return self.request.size_bytes()

    @property
    def generation_started(self) -> bool:
        return self.dispatch.started


@dataclass(slots=True)
class _Dispatch:
    started: bool = False


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

    def prepare_selected(
        self, turn: Turn, document_ids: frozenset[str], retrieved_payload: str | None = None
    ) -> PreparedRequest:
        """Retrieved documents join mandatory commercial/support evidence.

        Product facts remain canonical and complete for safe comparisons. This path never
        substitutes graph text for catalog facts or bypasses ordinary packing and validation.
        """
        if not document_ids.issubset({document.id for document in turn.active.catalog.documents}):
            raise ValueError('retrieval named an unknown catalog document')
        selected = tuple(
            document
            for document in turn.active.catalog.documents
            if document.id in document_ids
            or _mandatory_document(document.kind, document.title, document.text)
        )
        active = replace(turn.active, catalog=replace(turn.active.catalog, documents=selected))
        selected_turn = replace(turn, active=active)
        prepared = self.prepare(selected_turn)
        assert isinstance(prepared, PreparedRequest)
        if retrieved_payload is None:
            return prepared

        def with_retrieval(base: PreparedRequest) -> PreparedRequest:
            request = replace(
                base.request,
                inputs=(
                    *base.request.inputs[:-1],
                    ModelInput('user', f'retrieved_public_data:\n{retrieved_payload}'),
                    base.request.inputs[-1],
                ),
            )
            return replace(base, request=request)

        # Reserve exact serialized payload overhead before the ordinary packer decides which
        # optional documents/history fit. Mandatory facts and the original input bound remain.
        extra_bytes = with_retrieval(prepared).input_size_bytes - prepared.input_size_bytes
        limit = min(self._settings.max_input_bytes, turn.input_size_limit or self._settings.max_input_bytes)
        packed = self.prepare(replace(selected_turn, input_size_limit=max(1, limit - extra_bytes)))
        assert isinstance(packed, PreparedRequest)
        return with_retrieval(packed)

    def prepare(self, turn: Turn) -> PreparedTurn:
        last_user = next((m.content for m in reversed(turn.history) if m.role is Role.USER), '')
        current_ids = mentioned_products(turn.question, turn.active.catalog)
        previous_ids = next(
            (
                tuple(p.id for p in m.details.products)
                for m in reversed(turn.history)
                if m.role is Role.ASSISTANT and m.details.products
            ),
            (),
        )
        # An explicit topic change wins. Otherwise preserve structured referents across multiple
        # short follow-ups without indexing visitor conversations into catalog knowledge.
        hints = ' '.join(current_ids or previous_ids)
        query = f'{turn.question} {hints}' if hints else f'{turn.question} {last_user}'
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
                    # Make room for effective procedure evidence by removing only whole,
                    # low-ranked noncommercial FAQ documents. Mandatory policies/support and
                    # product facts remain intact; the input bound never increases.
                    for document_id in removable:
                        if trial.size_bytes() <= limit:
                            break
                        if catalog.document(document_id) is None:
                            continue
                        catalog = replace(
                            catalog, documents=tuple(d for d in catalog.documents if d.id != document_id)
                        )
                        evidence = evidence_text()
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
        prepared.dispatch.started = True
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
