"""Evaluation injection boundaries, frozen selections and default zero-provider behavior."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.adapters.providers.fixture_provider import FixtureProvider
from app.application.embedding_budget import SharedEmbeddingAccounting
from app.application.knowledge_ports import EmbeddingAccounting
from app.bootstrap import container
from app.bootstrap.config import Settings
from app.bootstrap.container import ProviderResource
from scripts import evaluate_graph_end_to_end as graph_runner
from scripts.evaluate_end_to_end import EvidenceProvider
from tests.support import settings
from tests.test_evaluation_embedding_accounting import ApplicationAccounting


def test_factory_is_single_owned_composition_with_real_shared_accounting(tmp_path: Path) -> None:
    calls: list[str] = []

    async def close() -> None:
        calls.append('close')

    def factory(config: Settings, accounting: EmbeddingAccounting) -> ProviderResource:
        assert config.ai_provider == 'fixture'
        assert isinstance(accounting, SharedEmbeddingAccounting)
        calls.append('construct')
        return ProviderResource(FixtureProvider(), close)

    app = container.create_app(settings(tmp_path), provider_factory=factory)
    assert calls == ['construct']
    with TestClient(app) as client:
        assert client.get('/health/ready').status_code == 200
        assert calls == ['construct']
    assert calls == ['construct', 'close']


@pytest.mark.parametrize('production', [False, True])
def test_forbidden_factory_overrides_fail_before_any_resource_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, production: bool
) -> None:
    def forbidden(*args: object, **kwargs: object) -> Any:
        raise AssertionError('forbidden override must fail before persistence or factory')

    monkeypatch.setattr(container, 'build_persistence', forbidden)
    config = settings(tmp_path)
    if production:
        config = Settings(
            _env_file=None,
            environment='production',
            assistant_enabled=False,
            session_cookie_secure=True,
            allowed_origins=['https://pequeverso.com'],
            client_hash_key=SecretStr('c' * 32),
        )
        with pytest.raises(ValueError, match='overrides'):
            container.create_app(config, provider_factory=forbidden)
    else:
        with pytest.raises(ValueError, match='mutually exclusive'):
            container.create_app(config, provider=FixtureProvider(), provider_factory=forbidden)


def test_fixture_factories_never_construct_sdk_even_with_ambient_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-ambient-must-not-be-read')
    monkeypatch.setenv('AI_PROVIDER', 'openai')

    def forbidden(*args: object, **kwargs: object) -> Any:
        raise AssertionError('fixture factory may not construct SDK or HTTP transport')

    monkeypatch.setattr(graph_runner, 'AsyncOpenAI', forbidden)
    monkeypatch.setattr(graph_runner, 'provider_http_client', forbidden)
    receipts: list[dict[str, Any]] = []
    embedding_factory, runtime_factory = graph_runner.factories(None, receipts)
    resource = embedding_factory(ApplicationAccounting())
    assert resource.embeddings.spec.provider == 'fixture' and resource.close is None
    evidence = EvidenceProvider()
    runtime = runtime_factory(
        evidence,
        Settings(_env_file=None, ai_provider='fixture', allow_paid_ai=False, openai_api_key=None),
        ApplicationAccounting(),
    )
    assert runtime.provider is evidence and runtime.embeddings is not None and runtime.close is None
    assert receipts == []


def test_frozen_subset_preserves_full_conversations_and_rejects_changed_turns() -> None:
    cases: list[dict[str, Any]] = [
        {
            'id': 'conversation',
            'family': 'followup',
            'turns': [{'question': 'one'}, {'question': 'two'}, {'question': 'three'}],
        },
        {'id': 'independent', 'family': 'price', 'turns': [{'question': 'four'}]},
    ]
    parent: dict[str, Any] = {'cases': cases, 'reply_policy': 'spanish_native'}
    parent_hash = 'a' * 64
    canonical = {'phase': graph_runner.PHASE, 'parent_manifest_sha256': parent_hash, 'cases': [cases[0]]}
    selector_hash = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    ).hexdigest()
    plan = {
        'recommended_full_manifest': {'sha256': parent_hash},
        'proposed_subset_not_execution_authorization': {
            'case_ids_in_order': ['conversation'],
            'canonical_selector_sha256': selector_hash,
        },
    }
    selected = graph_runner.selected_manifest(parent, parent_hash, plan)
    assert selected['query_count'] == 3 and selected['counts']['unexecuted_parent_queries'] == 1
    assert selected['cases'][0] == parent['cases'][0] and selected['cases'][0] is not parent['cases'][0]
    selected['cases'][0]['turns'][0]['question'] = 'changed'
    assert parent['cases'][0]['turns'][0]['question'] == 'one'
    parent['cases'][0]['turns'][0]['question'] = 'tampered'
    with pytest.raises(ValueError, match='changed'):
        graph_runner.selected_manifest(parent, parent_hash, plan)
    with pytest.raises(ValueError, match='parent hash'):
        graph_runner.selected_manifest(parent, 'b' * 64, plan)


def fixture_values() -> dict[str, Any]:
    return {
        'isolated_fixture': True,
        'runtime_roles_verified_non_owner': True,
        **{
            f'postgres_{kind}_dsn': f'postgresql://{kind}:synthetic@127.0.0.1:55440/pv_graph_eval'
            for kind in ('private', 'knowledge', 'indexer', 'embedding')
        },
        'neo4j_uri': 'bolt://127.0.0.1:17689',
        'neo4j_username': 'neo4j',
        'neo4j_password': 'synthetic-fixture-only',
    }


@pytest.mark.parametrize('problem', ['permissions', 'remote', 'shared_database', 'same_role', 'neo_origin'])
def test_configuration_rejects_unsafe_fixture_targets(tmp_path: Path, problem: str) -> None:
    path = tmp_path / 'fixture.json'
    values = fixture_values()
    if problem == 'remote':
        values['postgres_private_dsn'] = (
            'postgresql://private:synthetic@untrusted.invalid:55440/pv_graph_eval'
        )
    elif problem == 'shared_database':
        values['postgres_private_dsn'] = 'postgresql://private:synthetic@127.0.0.1:55440/shared'
    elif problem == 'same_role':
        values['postgres_private_dsn'] = values['postgres_knowledge_dsn']
    elif problem == 'neo_origin':
        values['neo4j_uri'] = 'bolt://untrusted.invalid:17689'
    path.write_text(json.dumps(values))
    path.chmod(0o644 if problem == 'permissions' else 0o600)
    with pytest.raises(ValueError, match=r'fixture|capabilities'):
        graph_runner.graph_configuration(path)


def test_default_graph_cli_ignores_key_and_budget_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / 'matrix.json'
    manifest.write_text(json.dumps({'cases': [{'id': 'fixture', 'turns': [{'question': 'Hola'}]}]}))
    output = tmp_path / 'output'
    monkeypatch.setattr(graph_runner, 'graph_configuration', lambda path: fixture_values())

    def forbidden(*args: object, **kwargs: object) -> Any:
        raise AssertionError('default fixture CLI must not read key/budget or create SDK')

    monkeypatch.setattr(graph_runner, 'load_live_provider', forbidden)
    monkeypatch.setattr(graph_runner, 'AsyncOpenAI', forbidden)
    monkeypatch.setattr(graph_runner, 'provider_http_client', forbidden)

    async def index(*args: object, **kwargs: object) -> Any:
        from app.application.indexing import IndexResult
        from app.domain.knowledge import ProjectionStamp

        return IndexResult('a' * 64, ProjectionStamp('a' * 64, 'b' * 64, 1, 1, 1), False)

    monkeypatch.setattr(graph_runner, 'index_evaluation_snapshot', index)

    def evaluate(*args: object, **kwargs: Any) -> dict[str, Any]:
        assert kwargs['bounded'] is None
        assert kwargs['graph_settings'].ai_provider == 'fixture'
        assert kwargs['graph_settings'].openai_api_key is None
        return {'stop_reason': None, 'structural_flagged_queries': 0, 'history_mismatches': 0}

    monkeypatch.setattr(graph_runner, 'evaluate', evaluate)
    monkeypatch.setattr(
        'sys.argv',
        [
            'graph-eval',
            '--services-config',
            str(tmp_path / 'fixture.json'),
            '--manifest',
            str(manifest),
            '--output-dir',
            str(output),
            '--source-revision',
            'a' * 40,
            '--key-file',
            str(tmp_path / 'MUST-NOT-READ'),
            '--budget-state',
            str(tmp_path / 'MUST-NOT-TOUCH'),
        ],
    )
    assert graph_runner.main() == 0
    assert not (tmp_path / 'MUST-NOT-TOUCH').exists()
    assert json.loads((output / 'index-accounting.json').read_text())['fixture_only'] is True


def test_historical_unreported_attempt_blocks_factory_before_any_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domain.errors import RejectedError
    from scripts.real_eval_budget import BoundedProvider, Envelope

    envelope = Envelope(tmp_path / 'budget.sqlite3', max_attempts=650)
    attempt = envelope.reserve()

    def forbidden(*args: object, **kwargs: object) -> Any:
        raise AssertionError('historical unknown usage must stop before SDK construction')

    monkeypatch.setattr(graph_runner, 'provider_http_client', forbidden)
    monkeypatch.setattr(graph_runner, 'AsyncOpenAI', forbidden)
    with pytest.raises(RejectedError):
        graph_runner.factories(BoundedProvider('synthetic-unused', envelope), [])
    assert envelope.snapshot() == {
        'attempts': 1,
        'reserved_micro_usd': 11000,
        'stop_reason': 'historical_unreported_usage',
    }
    with envelope.connect() as database:
        assert database.execute('SELECT id,reserved,settled FROM attempts').fetchall() == [
            (attempt, 11000, 0)
        ]


def test_live_loader_blocks_historical_unknown_before_credential_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domain.errors import RejectedError
    from scripts import evaluate_end_to_end as runner
    from scripts.real_eval_budget import Envelope

    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    key = private / 'key.env'
    key.write_text('synthetic must never be parsed')
    key.chmod(0o600)
    budget = private / 'budget.sqlite3'
    envelope = Envelope(budget, max_attempts=650)
    envelope.reserve()

    def forbidden(*args: object, **kwargs: object) -> Any:
        raise AssertionError('do not parse credentials with historical unknown spend')

    monkeypatch.setattr(runner, 'dotenv_values', forbidden)
    with pytest.raises(RejectedError):
        runner.load_live_provider(key, budget, max_attempts=650)
    assert envelope.snapshot()['stop_reason'] == 'historical_unreported_usage'


def test_evaluation_owner_is_exclusive_and_release_preserves_ledger(tmp_path: Path) -> None:
    from scripts.real_eval_budget import Envelope, evaluation_run_ownership

    directory = tmp_path / 'private'
    directory.mkdir(mode=0o700)
    path = directory / 'budget.sqlite3'
    envelope = Envelope(path, max_attempts=650)
    attempt = envelope.reserve()
    envelope.settle(attempt, 1, 1)
    before = envelope.snapshot()

    def second_owner() -> None:
        with evaluation_run_ownership(path):
            raise AssertionError('second runner cannot enter')

    with evaluation_run_ownership(path), pytest.raises(ValueError, match='owned'):
        second_owner()
    with evaluation_run_ownership(path):
        envelope.admit_new_run()
    assert envelope.snapshot() == before


@pytest.mark.parametrize('cancelled', [False, True])
def test_graph_index_failure_after_known_usage_persists_stop_and_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancelled: bool
) -> None:
    import asyncio

    import httpx2
    from openai import DefaultAsyncHttpxClient

    from app.domain.errors import RejectedError
    from app.domain.knowledge import EmbeddingPurpose
    from scripts.real_eval_budget import BoundedProvider, Envelope, evaluation_run_ownership

    private = tmp_path / 'private'
    private.mkdir(mode=0o700)
    budget = private / 'budget.sqlite3'
    envelope = Envelope(budget, max_attempts=650)
    bounded = BoundedProvider('synthetic-unused-no-provider-call', envelope)
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'cases': [{'id': 'synthetic', 'turns': [{'question': 'Hola'}]}]}))
    plan = tmp_path / 'plan.json'
    plan.write_text('{}')
    output = tmp_path / 'result'
    monkeypatch.setattr(graph_runner, 'graph_configuration', lambda path: fixture_values())
    monkeypatch.setattr(graph_runner, 'selected_manifest', lambda original, parent, plan: original)
    monkeypatch.setattr(graph_runner, 'load_live_provider', lambda *a, **k: bounded)

    async def failed_index(*args: object, **kwargs: object) -> Any:
        with pytest.raises(ValueError, match='owned'), evaluation_run_ownership(budget):
            raise AssertionError('runner must hold ownership throughout indexing')
        if cancelled:
            attempt = envelope.reserve()
            assert envelope.settle_embedding(attempt, 2, input_byte_bound=20)
            raise asyncio.CancelledError
        factory = args[3]
        assert callable(factory)
        owned = factory(ApplicationAccounting())
        try:
            await owned.embeddings.encode(('synthetic public catalog chunk',), EmbeddingPurpose.INDEX)
        finally:
            await owned.close()
        raise AssertionError('zero vector must be rejected after known SDK usage')

    sdk_calls: list[str] = []

    def response(request: httpx2.Request) -> httpx2.Response:
        sdk_calls.append(request.url.path)
        assert envelope.snapshot()['attempts'] == 1
        return httpx2.Response(
            200,
            json={
                'object': 'list',
                'model': 'text-embedding-3-small',
                'data': [{'object': 'embedding', 'index': 0, 'embedding': [0.0] * 1536}],
                'usage': {'prompt_tokens': 2, 'total_tokens': 2},
            },
        )

    monkeypatch.setattr(
        graph_runner,
        'provider_http_client',
        lambda: DefaultAsyncHttpxClient(
            transport=httpx2.MockTransport(response),
            verify=True,
            follow_redirects=False,
            trust_env=False,
        ),
    )
    monkeypatch.setattr(graph_runner, 'index_evaluation_snapshot', failed_index)
    monkeypatch.setattr(
        'sys.argv',
        [
            'graph-eval',
            '--services-config',
            str(tmp_path / 'fixture.json'),
            '--manifest',
            str(manifest),
            '--subset-plan',
            str(plan),
            '--output-dir',
            str(output),
            '--source-revision',
            'a' * 40,
            '--live',
            '--key-file',
            str(private / 'MUST-NOT-READ'),
            '--budget-state',
            str(budget),
        ],
    )
    with pytest.raises(asyncio.CancelledError if cancelled else RejectedError):
        graph_runner.main()
    assert envelope.snapshot() == {
        'attempts': 1,
        'reserved_micro_usd': 1,
        'stop_reason': 'index_setup_failure',
    }
    assert sdk_calls == ([] if cancelled else ['/v1/embeddings'])
    receipt = json.loads((output / 'index-accounting.json').read_text())
    assert receipt['result'] is None and receipt['envelope'] == envelope.snapshot()
    with evaluation_run_ownership(budget), pytest.raises(RejectedError):
        envelope.admit_new_run()
