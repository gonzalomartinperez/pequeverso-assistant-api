"""Offline operator guards refuse before acquiring services or dispatching paid requests."""

from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path

import pytest

from app.bootstrap import knowledge_jobs
from tests.support import CATALOG_BYTES


@pytest.mark.parametrize('failure', ['flag', 'environment', 'key', 'hash', 'provider', 'receipt_exists'])
def test_index_guards_precede_service_acquisition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str], failure: str
) -> None:
    catalog = tmp_path / 'catalog.json'
    catalog.write_bytes(CATALOG_BYTES)
    receipt = tmp_path / 'receipt.json'
    if failure == 'receipt_exists':
        receipt.write_text('retain-original-receipt')
    values = {
        'POSTGRES_INDEXER_DSN': 'postgresql://indexer:synthetic-private@db/public',
        'POSTGRES_EMBEDDING_DSN': 'postgresql://accounting:synthetic-private@db/public',
        'NEO4J_URI': 'bolt://graph:7687',
        'NEO4J_PASSWORD': 'synthetic-private',
        'AI_PROVIDER': 'openai',
        'ALLOW_PAID_AI': 'true',
        'OPENAI_API_KEY': 'synthetic-provider-key-never-sent',
    }
    if failure == 'environment':
        values['ALLOW_PAID_AI'] = 'false'
    elif failure == 'key':
        values['OPENAI_API_KEY'] = ''
    elif failure == 'provider':
        values['AI_PROVIDER'] = 'other-provider'
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    args = [
        'index_public_knowledge.py',
        '--catalog',
        str(catalog),
        '--expected-catalog-sha256',
        '0' * 64 if failure == 'hash' else hashlib.sha256(CATALOG_BYTES).hexdigest(),
        '--receipt',
        str(receipt),
    ]
    if failure != 'flag':
        args.append('--allow-paid-indexing')
    monkeypatch.setattr(sys, 'argv', args)

    def forbidden_acquisition(*args: object, **kwargs: object) -> None:
        pytest.fail('a refused indexing job must not create any database or provider resource')

    monkeypatch.setattr(knowledge_jobs, 'PostgresDatabase', forbidden_acquisition)
    monkeypatch.setattr(knowledge_jobs, 'AsyncOpenAI', forbidden_acquisition)
    assert asyncio.run(knowledge_jobs.index_main()) == 1
    captured = capsys.readouterr()
    assert 'synthetic-private' not in captured.out + captured.err
    assert 'synthetic-provider-key' not in captured.out + captured.err
    if failure == 'receipt_exists':
        assert receipt.read_text() == 'retain-original-receipt'
    else:
        assert not receipt.exists()
