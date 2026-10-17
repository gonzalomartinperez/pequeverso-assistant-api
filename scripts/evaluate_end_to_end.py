"""Frozen matrix over real loopback HTTP/SSE. Default fixture; live requires explicit opt-in.

Full answers are written exclusively to a new private directory outside the repository.
Structural correctness and heuristic flags are distinct from semantic/model quality.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import logging
import os
import socket
import sqlite3
import stat
import sys
import threading
import time
from collections.abc import AsyncGenerator, Callable
from contextlib import closing, nullcontext
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
import uvicorn
from dotenv import dotenv_values
from pydantic import SecretStr

from app.adapters.fixture_provider import FixtureProvider
from app.ai.evidence import passages, rank
from app.ai.provider import ModelChunk, ModelRequest
from app.application.knowledge_ports import EmbeddingAccounting
from app.bootstrap.config import DEFAULT_CATALOG, Settings
from app.bootstrap.container import ProviderResource, create_app
from app.domain.catalog import PriceStatus
from app.domain.web_evidence import SOURCES
from scripts.evaluate_conversations import CATALOG, _safety
from scripts.real_eval_budget import (
    ATTEMPT_MICRO,
    MAX_ATTEMPTS,
    BoundedProvider,
    Envelope,
    evaluation_run_ownership,
)

ORIGIN = 'http://localhost:3000'


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_private(path: Path, value: object) -> None:
    with path.open('x', encoding='utf-8') as output:
        os.chmod(path, 0o600)
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write('\n')


class EvidenceProvider:
    """Records actually sent public evidence privately; no instructions or visitor history."""

    def __init__(self, bounded: BoundedProvider | None = None) -> None:
        self.bounded = bounded
        self.records: list[dict[str, Any]] = []
        self.fixture = FixtureProvider(chunk_delay_seconds=0.001)

    @property
    def model(self) -> str:
        return self.bounded.model if self.bounded else 'fixture'

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelChunk]:
        raw = next(
            i.text.removeprefix('store_data:\n') for i in request.inputs if i.text.startswith('store_data:\n')
        )
        payload = json.loads(raw)
        official_raw = next(
            (
                i.text.removeprefix('official_platform_data:\n')
                for i in request.inputs
                if i.text.startswith('official_platform_data:\n')
            ),
            None,
        )
        official_record = {'official_platform': json.loads(official_raw)} if official_raw is not None else {}
        retrieval_raw = next(
            (
                i.text.removeprefix('retrieved_public_data:\n')
                for i in request.inputs
                if i.text.startswith('retrieved_public_data:\n')
            ),
            None,
        )
        self.records.append(
            {
                'sha256': digest(raw.encode()),
                'bytes': len(raw.encode()),
                'price_status': payload['price_status'],
                'products': [p['id'] for p in payload['products']],
                'resources': [r['id'] for p in payload['products'] for r in p['resources']],
                'documents': [d['id'] for d in payload['documents']],
                'links': [link['id'] for link in payload['links']],
                **official_record,
                **(
                    {
                        'retrieved_public': json.loads(retrieval_raw),
                        'retrieved_public_sha256': digest(retrieval_raw.encode()),
                    }
                    if retrieval_raw is not None
                    else {}
                ),
            }
        )
        async for chunk in (self.bounded or self.fixture).stream(request):
            yield chunk


def official_help_requested(manifest: dict[str, Any]) -> bool:
    value = manifest.get('official_help_enabled', False)
    if type(value) is not bool:
        raise ValueError('official_help_enabled must be a boolean')
    return value


def safety_with_official_evidence(
    events: list[dict[str, Any]], price_status: PriceStatus, evidence: list[dict[str, Any]]
) -> list[str]:
    selected = {item['id'] for record in evidence for item in record.get('official_platform', [])}
    if not selected:
        return _safety(events, price_status)
    known = {f'hotmart:{source.article_id}': source for source in SOURCES}
    copied = copy.deepcopy(events)
    problems: list[str] = []
    for event in copied:
        if event['type'] != 'message.completed':
            continue
        retained = []
        for citation in event['message']['sources']:
            source = known.get(citation['id'])
            if (
                source
                and citation['id'] in selected
                and citation['url'] == source.url
                and citation['title'] == source.title
            ):
                continue  # Exact actually sent public source, checked independently of catalog URLs.
            if citation['id'].startswith('hotmart:'):
                problems.append('unretrieved or invalid official platform citation')
            retained.append(citation)
        event['message']['sources'] = retained
    return [*_safety(copied, price_status), *problems]


def observed_language(content: str, notices: list[str], *, spanish_native: bool = False) -> str:
    if 'language_unsupported' in notices and not spanish_native:
        return 'bilingual-unsupported-notice'
    if content.startswith('From the store information (the material is in Spanish):'):
        return 'mixed-en-es-fixture'
    from app.domain.language import detect

    return detect(content)


def ask(
    client: httpx.Client,
    csrf: str,
    question: str,
    locale: str,
    key: str,
    *,
    on_event: Callable[[list[dict[str, Any]]], None] | None = None,
    response_language: str | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    first: float | None = None
    first_visible: float | None = None
    events: list[dict[str, Any]] = []
    with client.stream(
        'POST',
        '/api/v1/messages',
        headers={
            'Origin': ORIGIN,
            'X-CSRF-Token': csrf,
            'Idempotency-Key': key,
        },
        json={
            'content': question,
            'page': 'product',
            'locale': locale,
            **({'response_language': response_language} if response_language else {}),
            'context': {
                'opened_path': '/grafismo-fonetico/',
                'current_path': '/grafismo-fonetico/',
                'presentation': 'compact',
            },
        },
    ) as response:
        status = response.status_code
        error = None
        if status == 200:
            for line in response.iter_lines():
                if line.startswith('data: '):
                    event = json.loads(line[6:])
                    events.append(event)
                    is_delta = event['type'] == 'message.delta'
                    message = event.get('message')
                    visible = (is_delta and bool(event.get('text', '').strip())) or (
                        event['type'] == 'message.completed'
                        and isinstance(message, dict)
                        and isinstance(message.get('content'), str)
                        and bool(message['content'].strip())
                    )
                    if (is_delta and first is None) or (visible and first_visible is None):
                        elapsed = time.monotonic() - started
                        if is_delta and first is None:
                            first = elapsed
                        if visible and first_visible is None:
                            first_visible = elapsed
                    if on_event:
                        on_event(events)
        else:
            error = json.loads(response.read())['error']['code']
    return {
        'http_status': status,
        'error': error,
        'events': events,
        'first_content_seconds': first,
        'first_visible_content_seconds': first_visible,
        'duration_seconds': time.monotonic() - started,
    }


def load_live_provider(
    key_file: Path, budget_state: Path, *, max_attempts: int = MAX_ATTEMPTS
) -> BoundedProvider:
    """Only explicit live mode calls this; validate the shared cap before reading the key."""
    if type(max_attempts) is not int or not 1 <= max_attempts <= 650:
        raise ValueError('evaluation attempt cap must be an integer from 1 to 650')
    if max_attempts > MAX_ATTEMPTS and not budget_state.is_file():
        raise ValueError('extended attempt cap requires the existing shared evaluation budget')
    for path in (key_file, budget_state):
        if path.resolve().is_relative_to(ROOT):
            raise ValueError('live private files must be outside the repository')
        if path.is_symlink():
            raise ValueError('live private files cannot be symlinks')
    if not key_file.is_file() or stat.S_IMODE(key_file.stat().st_mode) != 0o600:
        raise ValueError('live key file must be a private mode600 regular file')
    if budget_state.exists() and stat.S_IMODE(budget_state.stat().st_mode) != 0o600:
        raise ValueError('shared budget state must be private mode600')
    budget_state.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if stat.S_IMODE(budget_state.parent.stat().st_mode) != 0o700:
        raise ValueError('shared budget directory must be private mode700')
    # Persisted-cap mismatch fails before any credential read. Extending the owner-approved
    # existing run must not accidentally create a fresh allowance through a mistyped path.
    envelope = Envelope(budget_state, max_attempts=max_attempts)
    envelope.admit_new_run()
    if max_attempts > MAX_ATTEMPTS and envelope.snapshot()['attempts'] == 0:
        raise ValueError('extended attempt cap requires an already-used shared evaluation budget')
    values = dotenv_values(key_file, interpolate=False)
    key = values.get('OPENAI_API_KEY')
    if (
        not key
        or values.get('OPENAI_MODEL') != 'gpt-6-luna'
        or values.get('OPENAI_REASONING_EFFORT') != 'medium'
    ):
        raise ValueError('private configuration does not match the authorized model')
    return BoundedProvider(key, envelope)


def checkpoint(path: Path, value: object) -> None:
    """Atomically preserve only this run's private partial artifacts."""
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as output:
        os.chmod(temporary, 0o600)
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def evaluate(
    manifest: dict[str, Any],
    destination: Path,
    source_revision: str,
    *,
    bounded: BoundedProvider | None = None,
    graph_settings: Settings | None = None,
    graph_factory: Callable[[EvidenceProvider, Settings, EmbeddingAccounting], ProviderResource]
    | None = None,
    graph_spend: Callable[[], Any] | None = None,
    embedding_receipts: list[dict[str, Any]] | None = None,
    retrieval_receipts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    use_official_help = official_help_requested(manifest)
    spanish_native = manifest.get('reply_policy') == 'spanish_native'
    response_language = 'es' if spanish_native else None
    policy_expectations = manifest.get('policy_expected_languages', {})
    provider = EvidenceProvider(bounded)
    envelope = bounded.envelope if bounded else None
    stop_reason: str | None = None
    isolated: bool | None = None
    bad_csrf: int | None = None
    bad_origin: int | None = None
    rows: list[dict[str, Any]] = []
    checkpoint(destination / 'answers.json', rows)

    def preflight() -> bool:
        nonlocal stop_reason
        if envelope:
            snapshot = envelope.snapshot()
            if snapshot['stop_reason']:
                stop_reason = snapshot['stop_reason']
            elif (
                snapshot['attempts'] >= envelope.max_attempts
                or snapshot['reserved_micro_usd'] + ATTEMPT_MICRO > envelope.cap_micro
            ):
                envelope.stop('budget_or_attempt_limit')
                stop_reason = 'budget_or_attempt_limit'
        return stop_reason is None

    settings = graph_settings or Settings(
        _env_file=None,
        environment='test',
        ai_provider='openai' if bounded else 'fixture',
        allow_paid_ai=bounded is not None,
        official_help_enabled=use_official_help and bounded is not None,
        openai_api_key=SecretStr(bounded._key) if bounded else None,
        catalog_url=None,
        catalog_file=DEFAULT_CATALOG,
        openai_model='gpt-6-luna',
        openai_reasoning_effort='medium',
        max_input_tokens=24000,
        max_output_tokens=4000,
        allowed_origins=[ORIGIN],
        ops_read_token=None,
        assistant_enabled=True,
        database_path=str(destination / 'evaluation.sqlite3'),
        sessions_per_client_per_hour=1000,
        messages_per_client_per_hour=10000,
        messages_per_session_per_day=100,
        service_revision=source_revision,
    )
    # Create only this isolated database with restrictive permissions before SQLite opens it.
    if graph_settings is None:
        descriptor = os.open(settings.database_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        app = create_app(settings, provider=provider)
    else:
        if (
            graph_factory is None
            or graph_spend is None
            or settings.application_storage != 'postgres'
            or settings.knowledge_backend != 'graphrag'
        ):
            raise ValueError(
                'graph evaluation requires explicit bounded composition and aggregate accounting'
            )
        app = create_app(
            settings, provider_factory=lambda conf, accounting: graph_factory(provider, conf, accounting)
        )
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
        reservation.listen(128)
        server = uvicorn.Server(
            uvicorn.Config(
                app, log_config=None, log_level=None, access_log=False, timeout_graceful_shutdown=5
            )
        )
        thread = threading.Thread(target=server.run, kwargs={'sockets': [reservation]}, daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError('evaluation server did not start')
            time.sleep(0.01)
        logging.getLogger().setLevel(logging.WARNING)
        try:
            for case in manifest['cases']:
                if not preflight():
                    break
                locale = 'es' if spanish_native else case['locale']
                with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=30, trust_env=False) as client:
                    opened = client.post(
                        '/api/v1/session', headers={'Origin': ORIGIN}, json={'locale': locale}
                    )
                    opened.raise_for_status()
                    csrf = opened.json()['csrf_token']
                    previous_question = ''
                    previous_history: list[dict[str, Any]] = []
                    for number, turn in enumerate(case['turns']):
                        if not preflight():
                            break
                        expected_language = (
                            policy_expectations[f'{case["id"]}:{number + 1}']
                            if spanish_native
                            else turn['expected_language']
                        )
                        key = f'matrix-{case["id"]}-{number}'
                        before = len(provider.records)
                        receipt_start = len(bounded.receipts) if bounded else 0
                        embedding_start = len(embedding_receipts or [])
                        retrieval_start = len(retrieval_receipts or [])

                        def capture_event(
                            events: list[dict[str, Any]],
                            case_id: str = case['id'],
                            turn_number: int = number + 1,
                        ) -> None:
                            checkpoint(
                                destination / 'inflight.json',
                                {
                                    'case_id': case_id,
                                    'turn': turn_number,
                                    'events': events,
                                },
                            )

                        try:
                            result = ask(
                                client,
                                csrf,
                                turn['question'],
                                locale,
                                key,
                                on_event=capture_event,
                                response_language=response_language,
                            )
                        except (httpx.HTTPError, ValueError) as error:
                            # No exception text: SDK/network errors can contain private values.
                            result = {
                                'http_status': None,
                                'error': type(error).__name__,
                                'events': [],
                                'first_content_seconds': None,
                                'first_visible_content_seconds': None,
                                'duration_seconds': None,
                            }
                        completed = [
                            e['message'] for e in result['events'] if e['type'] == 'message.completed'
                        ]
                        message = completed[-1] if completed else None
                        restored = client.post(
                            '/api/v1/session', headers={'Origin': ORIGIN}, json={'locale': locale}
                        )
                        restored.raise_for_status()
                        history = restored.json()['messages']
                        prior_history_preserved = history[:-2] == previous_history if completed else False
                        history_matches = bool(
                            len(completed) == 1
                            and prior_history_preserved
                            and history
                            and history[-1] == message
                            and len(history) == 2 * (number + 1)
                            and len({m['id'] for m in history}) == len(history)
                            and [m['role'] for m in history] == ['user', 'assistant'] * (number + 1)
                        )
                        public_evidence = provider.records[before:]
                        observed = (
                            observed_language(
                                message['content'], message['notices'], spanish_native=spanish_native
                            )
                            if message
                            else 'no-answer'
                        )
                        semantic_flags: list[str] = []
                        if observed == 'mixed-en-es-fixture':
                            semantic_flags.append('English response contains untranslated Spanish evidence')
                        if spanish_native and message:
                            from app.domain.language import Detected, detect

                            if any(
                                detect(text) in (Detected.EN, Detected.OTHER)
                                for text in [message['content'], *message['follow_ups']]
                            ):
                                semantic_flags.append(
                                    'Spanish native text or follow-up detected another language'
                                )
                        if expected_language == 'unsupported' and (
                            not message or 'language_unsupported' not in message['notices']
                        ):
                            semantic_flags.append('explicit unsupported language request reached generation')
                        elif (
                            expected_language in ('es', 'en')
                            and message
                            and message['language'] != expected_language
                        ):
                            semantic_flags.append('expected language differs from output metadata')
                        safety = (
                            safety_with_official_evidence(
                                result['events'],
                                PriceStatus(public_evidence[-1]['price_status'])
                                if public_evidence
                                else PriceStatus.UNVERIFIED,
                                public_evidence,
                            )
                            if result['events']
                            else ['no SSE events']
                        )
                        lexical = rank(f'{turn["question"]} {previous_question}', passages(CATALOG))
                        row = {
                            'case_id': case['id'],
                            'turn': number + 1,
                            'family': case['family'],
                            'question': turn['question'],
                            **result,
                            'terminal': [e['type'] for e in result['events'] if e['type'].startswith('run.')][
                                -1:
                            ],
                            'provider_calls': len(bounded.receipts[receipt_start:])
                            if bounded
                            else len(public_evidence),
                            'prepared_evidence_count': len(public_evidence),
                            'provider': (
                                provider.model
                                if bounded.receipts[receipt_start:]
                                else 'not-dispatched'
                                if public_evidence
                                else 'local-abstention'
                            )
                            if bounded
                            else 'fixture'
                            if public_evidence
                            else 'local-abstention',
                            'expected_language': expected_language,
                            'original_expected_language': turn['expected_language'],
                            'reply_policy': 'spanish_native' if spanish_native else 'legacy_bilingual',
                            'observed_language': observed,
                            'evidence': public_evidence,
                            'lexical_top3': [{'id': p.id, 'score': score} for p, score in lexical[:3]],
                            'history_matches': history_matches,
                            'prior_history_preserved': prior_history_preserved,
                            'structural_flags': safety,
                            'behavior_flags': semantic_flags,
                            'semantic_correctness': 'not certified: automated structural and heuristic checks only',
                            'citations': [s['id'] for s in message['sources']] if message else [],
                            'actual_provider_usd': None if bounded else '0',
                            'dispatched_attempts': len(bounded.receipts[receipt_start:]) if bounded else 0,
                            'all_sdk_attempts': (
                                len(bounded.receipts[receipt_start:])
                                + len((embedding_receipts or [])[embedding_start:])
                            )
                            if bounded
                            else 0,
                            'usage_receipts': bounded.receipts[receipt_start:] if bounded else [],
                            'embedding_receipts': (embedding_receipts or [])[embedding_start:],
                            'retrieval': (retrieval_receipts or [])[retrieval_start:],
                            'uncertain_paid_calls': sum(
                                r['usage'] is None for r in bounded.receipts[receipt_start:]
                            )
                            + sum(r['usage'] is None for r in (embedding_receipts or [])[embedding_start:])
                            if bounded
                            else 0,
                        }
                        rows.append(row)
                        checkpoint(destination / 'answers.json', rows)
                        if envelope:
                            checkpoint(destination / 'budget.json', envelope.snapshot())
                            if (
                                safety
                                or not history_matches
                                or result['error']
                                or row['terminal'] != ['run.completed']
                            ):
                                envelope.stop('case_gate_failure')
                            if bounded and any(r['usage'] is None for r in bounded.receipts[receipt_start:]):
                                envelope.stop('missing_usage')
                            if embedding_receipts and any(
                                r['usage'] is None for r in embedding_receipts[embedding_start:]
                            ):
                                envelope.stop('missing_embedding_usage')
                            if not preflight():
                                print(
                                    json.dumps({'completed_queries': len(rows), 'stop_reason': stop_reason}),
                                    flush=True,
                                )
                                break
                        print(
                            json.dumps(
                                {
                                    'case_id': case['id'],
                                    'turn': number + 1,
                                    'completed_queries': len(rows),
                                    'terminal': row['terminal'],
                                    'stop_reason': stop_reason,
                                }
                            ),
                            flush=True,
                        )
                        previous_question = turn['question']
                        previous_history = history
                        # Verify every completed turn, including intermediate conversation turns.
                        before_replay = len(provider.records)
                        embeddings_before_replay = len(embedding_receipts or [])
                        retrieval_before_replay = len(retrieval_receipts or [])
                        replay = ask(
                            client, csrf, turn['question'], locale, key, response_language=response_language
                        )
                        rows[-1]['replay_new_provider_calls'] = len(provider.records) - before_replay
                        rows[-1]['replay_new_embedding_calls'] = (
                            len(embedding_receipts or []) - embeddings_before_replay
                        )
                        rows[-1]['replay_new_retrievals'] = (
                            len(retrieval_receipts or []) - retrieval_before_replay
                        )
                        replay_messages = [
                            event['message']
                            for event in replay['events']
                            if event['type'] == 'message.completed'
                        ]
                        rows[-1]['replay_answer_matches'] = (
                            len(replay_messages) == 1 and replay_messages[0] == message
                        )
                        replay_history = client.post(
                            '/api/v1/session', headers={'Origin': ORIGIN}, json={'locale': locale}
                        )
                        replay_history.raise_for_status()
                        rows[-1]['replay_history_unchanged'] = replay_history.json()['messages'] == history
                        rows[-1]['replay_terminal'] = [
                            e['type'] for e in replay['events'] if e['type'].startswith('run.')
                        ][-1:]
                        checkpoint(destination / 'answers.json', rows)
                        if envelope and (
                            rows[-1]['replay_new_provider_calls']
                            or rows[-1]['replay_new_embedding_calls']
                            or rows[-1]['replay_new_retrievals']
                            or not rows[-1]['replay_answer_matches']
                            or not rows[-1]['replay_history_unchanged']
                            or rows[-1]['replay_terminal'] != ['run.completed']
                        ):
                            envelope.stop('replay_gate_failure')
                            preflight()
                            break
                    if stop_reason:
                        break
            with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=10, trust_env=False) as outsider:
                isolated = (
                    outsider.post('/api/v1/session', headers={'Origin': ORIGIN}, json={}).json()['messages']
                    == []
                )
                bad_csrf = outsider.post(
                    '/api/v1/messages',
                    headers={
                        'Origin': ORIGIN,
                        'X-CSRF-Token': 'not-valid',
                        'Idempotency-Key': 'matrix-invalid-csrf',
                    },
                    json={'content': 'What is included?'},
                ).status_code
                bad_origin = outsider.post(
                    '/api/v1/session', headers={'Origin': 'https://evil.invalid'}, json={}
                ).status_code
            if envelope and (not isolated or bad_csrf != 403 or bad_origin != 403):
                envelope.stop('authorization_isolation_gate_failure')
                preflight()
        except BaseException as error:  # noqa: BLE001 -- retain partial artifacts, expose type only
            stop_reason = (
                'interrupted' if isinstance(error, (KeyboardInterrupt, SystemExit)) else type(error).__name__
            )
            if envelope:
                envelope.stop(stop_reason)
        finally:
            checkpoint(destination / 'answers.json', rows)
            server.should_exit = True
            thread.join(timeout=20)
            if thread.is_alive():
                stop_reason = 'evaluation_server_failed_to_stop'
                if envelope:
                    envelope.stop(stop_reason)
    if graph_settings is None:
        with closing(sqlite3.connect(destination / 'evaluation.sqlite3')) as db:
            ledger = [
                dict(zip(('status', 'calls', 'reserved_micro', 'actual_micro'), r, strict=True))
                for r in db.execute(
                    'SELECT status, count(*), sum(reserved_micro), sum(actual_micro) FROM spend_ledger GROUP BY status'
                )
            ]
    else:
        assert graph_spend is not None
        ledger = asyncio.run(graph_spend())
    for suffix in ('', '-wal', '-shm'):
        state_file = destination / f'evaluation.sqlite3{suffix}'
        if state_file.exists():
            os.chmod(state_file, 0o600)
    checkpoint(destination / 'answers.json', rows)
    summary = {
        'schema': 1,
        'source_revision': source_revision,
        'fixture_only': bounded is None,
        'model': provider.model,
        'reasoning_effort': 'medium' if bounded else None,
        'stop_reason': stop_reason,
        'expected_queries': sum(len(c['turns']) for c in manifest['cases']),
        'missing_turns': [
            {'case_id': c['id'], 'turn': n + 1}
            for c in manifest['cases']
            for n, _ in enumerate(c['turns'])
            if not any(r['case_id'] == c['id'] and r['turn'] == n + 1 for r in rows)
        ],
        'manifest_sha256': digest(json.dumps(manifest, ensure_ascii=False, indent=2).encode() + b'\n'),
        'catalog_sha256': digest(DEFAULT_CATALOG.read_bytes()),
        'catalog_generated_at': CATALOG.generated_at.isoformat(),
        'queries': len(rows),
        'provider_calls': len(bounded.receipts) if bounded else len(provider.records),
        'prepared_evidence_count': len(provider.records),
        'actual_provider_usd': None if bounded else '0',
        'conservative_budget_not_invoice': envelope.snapshot() if envelope else None,
        'dispatched_attempts': len(bounded.receipts) if bounded else 0,
        'usage_receipts': bounded.receipts if bounded else [],
        'embedding_receipts': embedding_receipts or [],
        'all_sdk_attempts': (len(bounded.receipts) + len(embedding_receipts or [])) if bounded else 0,
        'embedding_sdk_attempts': len(embedding_receipts or []),
        'knowledge_backend': settings.knowledge_backend,
        'uncertain_paid_calls': (
            sum(r['usage'] is None for r in bounded.receipts)
            + sum(r['usage'] is None for r in embedding_receipts or [])
        )
        if bounded
        else 0,
        'isolated_visitor_empty_history': isolated,
        'invalid_csrf_http_status': bad_csrf,
        'invalid_origin_http_status': bad_origin,
        'history_mismatches': sum(not r['history_matches'] for r in rows),
        'structural_flagged_queries': sum(bool(r['structural_flags']) for r in rows),
        'behavior_flagged_queries': sum(bool(r['behavior_flags']) for r in rows),
        'application_ledger_estimate_not_invoice' if bounded else 'synthetic_ledger_not_invoice': ledger,
        'review_method': 'automated structural assertions and heuristic language flags; no human or live-model quality certification',
        'cases': [{k: v for k, v in row.items() if k not in ('question', 'events')} for row in rows],
    }
    write_private(destination / 'summary.json', summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--key-file', type=Path)
    parser.add_argument('--budget-state', type=Path)
    parser.add_argument('--max-attempts', type=int, default=MAX_ATTEMPTS)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'evals/end_to_end.json')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--source-revision', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    manifest = json.loads(args.manifest.read_text())
    official_help_requested(manifest)
    if not 1 <= args.max_attempts <= 650:
        parser.error('--max-attempts must be from 1 to 650')
    if sum(len(c['turns']) for c in manifest['cases']) < 200:
        parser.error('at least 200 frozen queries required')
    destination = args.output_dir.resolve()
    if destination == ROOT or ROOT in destination.parents:
        parser.error('full answers must be outside the repository')
    if destination.exists():
        parser.error('destination must be new; initial results must never be overwritten')
    if args.live and (args.key_file is None or args.budget_state is None):
        parser.error('--live requires --key-file and shared --budget-state')
    ownership = evaluation_run_ownership(args.budget_state) if args.live else nullcontext()
    with ownership:
        bounded = None
        if args.live:
            bounded = load_live_provider(args.key_file, args.budget_state, max_attempts=args.max_attempts)
        destination.mkdir(parents=True, mode=0o700)
        os.chmod(destination, 0o700)
        for name in ('httpx', 'httpx2', 'httpcore', 'httpcore2', 'openai'):
            logging.getLogger(name).setLevel(logging.CRITICAL)
        write_private(destination / 'manifest.json', manifest)
        (destination / 'catalog.json').write_bytes(DEFAULT_CATALOG.read_bytes())
        os.chmod(destination / 'catalog.json', 0o600)
        summary = evaluate(manifest, destination, args.source_revision, bounded=bounded)
        print(
            json.dumps({k: v for k, v in summary.items() if k not in ('cases', 'usage_receipts')}, indent=2)
        )
        if summary['stop_reason']:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
