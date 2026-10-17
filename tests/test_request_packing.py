"""Exact request packing preserves commercial facts and records only effective sources."""

import hashlib
import json
from datetime import timedelta

from app.adapters.catalog_schema import CatalogParser
from app.ai.composer import ComposerSettings, GroundedComposer
from app.ai.prompt import INSTRUCTIONS, OUTPUT_SCHEMA
from app.application.answers import answer_rules, finalize
from app.application.ports import Draft, Turn
from app.domain.catalog import ActiveCatalog, PriceStatus
from app.domain.conversation import AnswerDetails, Message, Role
from app.domain.web_evidence import SOURCES, WebEvidence
from tests.support import (
    CATALOG_BYTES,
    JSON_HEADERS,
    ScriptedProvider,
    answer_json,
    ask,
    client,
    open_session,
)

CATALOG = CatalogParser(frozenset({'pequeverso.com', 'consumer.hotmart.com', 'refund.hotmart.com'}))(
    CATALOG_BYTES
)
ACTIVE = ActiveCatalog(CATALOG, 'a' * 64, CATALOG.generated_at, timedelta(hours=168))


def _turn(history=(), evidence=()):
    return Turn(
        ACTIVE,
        PriceStatus.VERIFIED,
        history,
        '¿Cómo recibo el kit?',
        None,
        'synthetic',
        web_evidence=evidence,
    )


def _composer(limit=24000):
    return GroundedComposer(ScriptedProvider(), ComposerSettings(4000, 40000, limit))


def _store(prepared):
    return json.loads(prepared.request.inputs[0].text.split('\n', 1)[1])


def _visitor(prepared):
    return json.loads(prepared.request.inputs[-1].text.split('\n', 1)[1])


def test_old_context_compacts_but_latest_exchange_and_structured_catalog_survive():
    history = tuple(
        Message(
            f'm-{i}',
            Role.USER if i % 2 == 0 else Role.ASSISTANT,
            'Información anterior. ' * 70,
            CATALOG.generated_at,
            AnswerDetails(),
        )
        for i in range(10)
    )
    prepared = _composer().prepare(_turn(history))
    assert prepared.input_size_bytes <= 24000
    conversation = _visitor(prepared)['conversation']
    assert any(not entry['text'] for entry in conversation[:-2])
    assert conversation[-2]['text'] == history[-2].content[:1200]
    assert conversation[-1]['text'] and history[-1].content.startswith(conversation[-1]['text'])
    assert conversation[-1]['text'].endswith('.')
    assert all(m.content for m in history)
    store = _store(prepared)
    assert len(store['products'][0]['resources']) == 9
    assert store['products'][0]['page_count'] == 414
    assert {r['id']: r['pages'] for r in store['products'][0]['resources']}['grafismo-fonetico/juega'] == 50
    mandatory = {
        d.id
        for d in CATALOG.documents
        if d.kind.value in ('policy', 'support')
        and CATALOG.applies_to(d.product_ids, frozenset({'grafismo-fonetico'}))
    }
    mandatory |= {
        'faq.grafismo-fonetico.03',
        'faq.grafismo-fonetico.06',
        'faq.grafismo-fonetico.10',
        'faq.grafismo-fonetico.11',
    }
    assert mandatory <= {d['id'] for d in store['documents']}
    assert _visitor(prepared)['question'] == '¿Cómo recibo el kit?'
    assert prepared.request.instructions == INSTRUCTIONS and prepared.request.output_schema == OUTPUT_SCHEMA


def test_optional_article_fits_only_as_complete_prefix_with_effective_hash():
    # Each long paragraph alone exceeds the unchanged full request bound, independently
    # of prompt compaction or eviction of optional FAQ evidence.
    text = 'Synthetic public procedure with its complete condition.\n' + 'Long synthetic paragraph. ' * 1200
    original = WebEvidence(SOURCES[0], text, hashlib.sha256(text.encode()).hexdigest(), CATALOG.generated_at)
    prepared = _composer().prepare(_turn(evidence=(original,)))
    assert prepared.input_size_bytes <= 24000
    assert len(prepared.web_evidence) == 1
    effective = prepared.web_evidence[0]
    assert effective.text == text.splitlines()[0]
    assert effective.sha256 == hashlib.sha256(effective.text.encode()).hexdigest()
    assert original.text == text and original.sha256 != effective.sha256
    payload = json.loads(prepared.request.inputs[1].text.split('\n', 1)[1])
    assert effective.sha256 in json.dumps(payload)
    assert effective.text in prepared.request.inputs[1].text


def test_unfitting_whole_paragraph_is_omitted_without_fabricated_source():
    original = WebEvidence(
        SOURCES[0], 'One indivisible qualified paragraph. ' * 800, 'a' * 64, CATALOG.generated_at
    )
    prepared = _composer().prepare(_turn(evidence=(original,)))
    assert prepared.input_size_bytes <= 24000 and not prepared.web_evidence
    assert not any(item.text.startswith('official_platform_data:') for item in prepared.request.inputs)
    final = finalize(
        Draft('El material es digital.', references=(), sources=(original.id,), follow_ups=()),
        ACTIVE,
        PriceStatus.VERIFIED,
        answer_rules(CATALOG, PriceStatus.VERIFIED, ()),
        web_evidence=prepared.web_evidence,
        catalog_source_ids=prepared.catalog_source_ids,
    )
    assert not final.details.sources


def test_valid_but_unsent_catalog_document_cannot_become_final_citation():
    history = tuple(
        Message(
            f'm-{i}',
            Role.USER if i % 2 == 0 else Role.ASSISTANT,
            'Contexto anterior. ' * 90,
            CATALOG.generated_at,
            AnswerDetails(),
        )
        for i in range(6)
    )
    prepared = _composer().prepare(_turn(history))
    omitted = next(d.id for d in CATALOG.documents if d.id not in prepared.catalog_source_ids)
    sent = next(iter(prepared.catalog_source_ids))
    final = finalize(
        Draft('El material es digital.', references=(), sources=(omitted, sent), follow_ups=()),
        ACTIVE,
        PriceStatus.VERIFIED,
        answer_rules(CATALOG, PriceStatus.VERIFIED, ()),
        catalog_source_ids=prepared.catalog_source_ids,
    )
    assert [source.id for source in final.details.sources] == [sent]
    assert final.dropped_references == 1


def test_smaller_limit_remains_fail_closed_without_relaxing_protocol_margin():
    prepared = _composer(128).prepare(_turn())
    assert prepared.input_size_bytes > 128 and not prepared.web_evidence
    assert prepared.request.instructions == INSTRUCTIONS


def test_six_turn_http_followups_keep_full_history_and_every_current_question(tmp_path):
    answer = (
        'Safari tiene 40 páginas y Juega tiene 50 páginas. '
        + 'Puedes elegir una actividad para cada práctica. ' * 23
    ).strip()
    provider = ScriptedProvider(
        answer_json(answer, references=[{'kind': 'resource', 'id': 'grafismo-fonetico/juega'}])
    )
    with client(tmp_path, provider) as http:
        csrf = open_session(http)
        previous = []
        for turn in range(6):
            question = (
                f'¿Y cómo comparo estos bonos en la práctica {turn}?'
                if turn
                else '¿Qué diferencias hay entre Safari y Juega?'
            )
            status, events, _ = ask(http, csrf, question, f'packing-turn-{turn}')
            assert status == 200 and events[-1]['type'] == 'run.completed'
            restored = http.post('/api/v1/session', headers=JSON_HEADERS, json={}).json()['messages']
            assert restored[: len(previous)] == previous
            assert len(restored) == (turn + 1) * 2 and restored[-1]['content'] == answer
            previous = restored
            assert provider.calls[-1].size_bytes() <= 24000
            visitor = json.loads(provider.calls[-1].inputs[-1].text.split('\n', 1)[1])
            assert visitor['question'] == question
            if turn:
                assert visitor['conversation'][-1]['referenced_ids'] == ['grafismo-fonetico/juega']
        assert len(provider.calls) == 6
