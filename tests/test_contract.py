"""Pinned v1 contract artifacts are current and self-consistent."""

from __future__ import annotations

import hashlib
import json

from pydantic import TypeAdapter

from app.presentation.events import TERMINAL_TYPES, StreamEvent
from app.presentation.schemas import SessionOut
from contracts.export import ROOT, build
from tests.support import parse_sse

EVENTS = TypeAdapter(StreamEvent)


def test_committed_artifacts_match_the_code() -> None:
    for name, data in build().items():
        assert (ROOT / name).read_bytes() == data, f'{name} is stale: run uv run python -m contracts.export'


def test_manifest_hashes_every_artifact() -> None:
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    assert manifest['contract_version'] == '1'
    for name, digest in manifest['artifacts'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest


def test_example_streams_follow_the_event_grammar() -> None:
    for path in sorted((ROOT / 'examples').glob('*.sse')):
        events = parse_sse(path.read_text())
        for event in events:
            EVENTS.validate_python(event)
        types = [e['type'] for e in events]
        assert types[0] == 'run.started', path
        assert types[-1] in TERMINAL_TYPES, path
        assert sum(t in TERMINAL_TYPES for t in types) == 1, path
        if 'message.completed' in types:
            assert types[-2:] == ['message.completed', 'run.completed'], path
            streamed = ''.join(e['text'] for e in events if e['type'] == 'message.delta')
            assert streamed == events[-2]['message']['content'], path


def test_examples_never_carry_unsafe_payloads() -> None:
    for path in (ROOT / 'examples').iterdir():
        text = path.read_text()
        for forbidden in ('<script', 'javascript:', 'sk-', 'instructions', 'reasoning', 'Imprime y Juega'):
            assert forbidden not in text, (path.name, forbidden)
    SessionOut.model_validate_json((ROOT / 'examples' / 'session.created.json').read_text())


def test_openapi_routes_keep_the_public_prefix() -> None:
    paths = set(json.loads((ROOT / 'openapi.json').read_text())['paths'])
    assert paths == {
        '/api/v1/availability',
        '/api/v1/session',
        '/api/v1/messages',
        '/api/v1/runs/{run_id}/cancel',
    }
    assert not any(p.startswith(('/api/api', '/health')) for p in paths)
