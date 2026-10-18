"""Isolated GraphRAG socket evaluation. Fixture by default; no implicit paid index setup.

Use an already migrated, exclusively owned fixture database and four distinct non-owner
capabilities. Full matrices are fixture-only; a future live subset needs separate current
owner authorization, the existing shared envelope, and a frozen parent/selection proof.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import logging
import os
import stat
import sys
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openai import AsyncOpenAI
from pydantic import SecretStr

from app.adapters.providers.openai_embeddings import FixtureHashEmbeddings, OpenAIEmbeddings
from app.application.knowledge_ports import EmbeddingAccounting
from app.bootstrap.config import DEFAULT_CATALOG, Settings
from app.bootstrap.container import ProviderResource, SystemClock
from app.bootstrap.evaluation_index import (
    EmbeddingFactory,
    EmbeddingResource,
    EvaluationIndexConfig,
    RecordingComposer,
    evaluation_spend_snapshot,
    index_evaluation_snapshot,
)
from app.bootstrap.knowledge_evaluation import safe_exception_hook
from app.bootstrap.logging import configure_logging
from app.bootstrap.provider_transport import close_owned_provider, provider_http_client
from scripts.evaluate_end_to_end import (
    ORIGIN,
    EvidenceProvider,
    digest,
    evaluate,
    load_live_provider,
    official_help_requested,
    write_private,
)
from scripts.real_eval_budget import BoundedProvider, EvaluationEmbeddingAccounting, evaluation_run_ownership

PHASE = 'proposed-bounded-graph-targeted-development-only'


def graph_configuration(path: Path) -> dict[str, str]:
    resolved = path.resolve()
    if path.is_symlink() or resolved.is_relative_to(ROOT) or not path.is_file():
        raise ValueError('graph fixture configuration must be an external regular private file')
    if (
        stat.S_IMODE(path.stat().st_mode) != 0o600
        or path.stat().st_uid != os.getuid()
        or path.stat().st_size > 32768
    ):
        raise ValueError('graph fixture configuration ownership, permissions or size is invalid')
    raw = json.loads(path.read_text())
    if raw.get('isolated_fixture') is not True or raw.get('runtime_roles_verified_non_owner') is not True:
        raise ValueError('graph evaluation requires explicitly isolated non-owner fixture capabilities')
    keys = (
        'postgres_private_dsn',
        'postgres_knowledge_dsn',
        'postgres_indexer_dsn',
        'postgres_embedding_dsn',
        'neo4j_uri',
        'neo4j_username',
        'neo4j_password',
    )
    if any(not isinstance(raw.get(key), str) or not raw[key] for key in keys):
        raise ValueError('graph fixture capabilities are incomplete')
    values = {key: raw[key] for key in keys}
    locations = [urlsplit(values[key]) for key in keys[:4]]
    if any(
        p.scheme != 'postgresql'
        or p.hostname != '127.0.0.1'
        or p.port != 55440
        or not p.path.startswith('/pv_')
        or p.query
        or p.fragment
        for p in locations
    ):
        raise ValueError('graph evaluation accepts only its dedicated loopback PostgreSQL fixture')
    if len({p.path for p in locations}) != 1 or len({p.username for p in locations}) != 4:
        raise ValueError('four separate capabilities must address one isolated fixture database')
    if values['neo4j_uri'] != 'bolt://127.0.0.1:17689':
        raise ValueError('graph evaluation accepts only its dedicated loopback Neo4j fixture')
    return values


def selected_manifest(
    manifest: dict[str, Any], parent_hash: str, plan: dict[str, Any] | None
) -> dict[str, Any]:
    if plan is None:
        return copy.deepcopy(manifest)
    selection = plan['proposed_subset_not_execution_authorization']
    if plan['recommended_full_manifest']['sha256'] != parent_hash:
        raise ValueError('frozen subset parent hash does not match the unchanged full matrix')
    ids = selection['case_ids_in_order']
    if not isinstance(ids, list) or not ids or len(ids) != len(set(ids)):
        raise ValueError('subset case ids must be nonempty and unique')
    lookup = {case['id']: case for case in manifest['cases']}
    cases = [copy.deepcopy(lookup[case_id]) for case_id in ids]
    canonical = {'phase': PHASE, 'parent_manifest_sha256': parent_hash, 'cases': cases}
    expected = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    ).hexdigest()
    if expected != selection['canonical_selector_sha256']:
        raise ValueError('frozen subset questions/order/rubrics have changed')
    chosen = copy.deepcopy(manifest)
    chosen.update(
        phase=PHASE,
        parent_manifest_sha256=parent_hash,
        selection_sha256=expected,
        cases=cases,
        case_count=len(cases),
        query_count=sum(len(c['turns']) for c in cases),
    )
    chosen['counts'] = {
        'selected_cases': len(cases),
        'selected_queries': chosen['query_count'],
        'unexecuted_parent_queries': sum(len(c['turns']) for c in manifest['cases']) - chosen['query_count'],
    }
    return chosen


def factories(
    bounded: BoundedProvider | None,
    receipts: list[dict[str, Any]],
    retrievals: list[dict[str, Any]] | None = None,
) -> tuple[EmbeddingFactory, Callable[[EvidenceProvider, Settings, EmbeddingAccounting], ProviderResource]]:
    if bounded is not None:
        bounded.envelope.admit_new_run()

    def embeddings(accounting: EmbeddingAccounting) -> EmbeddingResource:
        if bounded is None:
            return EmbeddingResource(FixtureHashEmbeddings())
        guarded = EvaluationEmbeddingAccounting(accounting, bounded.envelope)
        guarded.receipts = receipts
        http = provider_http_client()
        sdk = AsyncOpenAI(
            api_key=bounded._key,
            base_url='https://api.openai.com/v1',
            http_client=http,
            max_retries=0,
            timeout=30,
        )
        return EmbeddingResource(OpenAIEmbeddings(sdk, guarded), lambda: close_owned_provider(sdk, http))

    def runtime(
        evidence: EvidenceProvider, settings: Settings, accounting: EmbeddingAccounting
    ) -> ProviderResource:
        if (bounded is None) != (settings.ai_provider == 'fixture'):
            raise ValueError('fixture/live provider identity mismatch')
        owned = embeddings(accounting)
        return ProviderResource(
            evidence,
            owned.close,
            owned.embeddings,
            lambda composer: RecordingComposer(composer, retrievals if retrievals is not None else []),
        )

    return embeddings, runtime


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--services-config', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--subset-plan', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--source-revision', required=True)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--key-file', type=Path)
    parser.add_argument('--budget-state', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    configure_logging()
    values = graph_configuration(args.services_config)
    body = args.manifest.read_bytes()
    parent_hash = digest(body)
    original = json.loads(body)
    manifest = selected_manifest(
        original, parent_hash, json.loads(args.subset_plan.read_text()) if args.subset_plan else None
    )
    destination = args.output_dir.resolve()
    if destination.is_relative_to(ROOT) or destination.exists():
        parser.error('output must be a new private directory outside the repository')
    if args.live and (args.subset_plan is None or args.key_file is None or args.budget_state is None):
        parser.error('live requires a frozen bounded subset and the existing private shared budget/key paths')
    ownership = evaluation_run_ownership(args.budget_state) if args.live else nullcontext()
    with ownership:
        # Default fixture mode does not inspect either credential/budget argument, even if present.
        bounded = (
            load_live_provider(args.key_file, args.budget_state, max_attempts=650) if args.live else None
        )
        destination.mkdir(parents=True, mode=0o700)
        for name in ('httpx', 'httpx2', 'httpcore', 'httpcore2', 'openai'):
            logging.getLogger(name).setLevel(logging.CRITICAL)
        write_private(destination / 'source-manifest.json', original)
        write_private(destination / 'manifest.json', manifest)
        (destination / 'catalog.json').write_bytes(DEFAULT_CATALOG.read_bytes())
        (destination / 'catalog.json').chmod(0o600)
        receipts: list[dict[str, Any]] = []
        retrievals: list[dict[str, Any]] = []
        embedding_factory, runtime_factory = factories(bounded, receipts, retrievals)
        clock = SystemClock()
        index_config = EvaluationIndexConfig(
            SecretStr(values['postgres_indexer_dsn']),
            SecretStr(values['postgres_embedding_dsn']),
            values['neo4j_uri'],
            values['neo4j_username'],
            SecretStr(values['neo4j_password']),
        )
        index_result = None
        try:
            index_result = asyncio.run(
                index_evaluation_snapshot(
                    index_config, DEFAULT_CATALOG.read_bytes(), clock, embedding_factory
                )
            )
        except BaseException:
            if bounded is not None:
                bounded.envelope.stop('index_setup_failure')
            raise
        finally:
            write_private(
                destination / 'index-accounting.json',
                {
                    'result': asdict(index_result) if index_result else None,
                    'embedding_receipts': receipts,
                    'envelope': bounded.envelope.snapshot() if bounded else None,
                    'fixture_only': bounded is None,
                },
            )
        settings = Settings(
            _env_file=None,
            environment='test',
            session_cookie_secure=False,
            observability_enabled=False,
            telemetry_otlp_endpoint=None,
            ai_provider='openai' if bounded else 'fixture',
            allow_paid_ai=bounded is not None,
            official_help_enabled=official_help_requested(manifest) and bounded is not None,
            openai_api_key=SecretStr(bounded._key) if bounded else None,
            application_storage='postgres',
            knowledge_backend='graphrag',
            postgres_private_dsn=SecretStr(values['postgres_private_dsn']),
            postgres_knowledge_dsn=SecretStr(values['postgres_knowledge_dsn']),
            neo4j_uri=values['neo4j_uri'],
            neo4j_username=values['neo4j_username'],
            neo4j_password=SecretStr(values['neo4j_password']),
            catalog_url=None,
            catalog_file=DEFAULT_CATALOG,
            max_input_tokens=24000,
            max_output_tokens=4000,
            allowed_origins=[ORIGIN],
            ops_read_token=None,
            assistant_enabled=True,
            sessions_per_client_per_hour=1000,
            messages_per_client_per_hour=10000,
            messages_per_session_per_day=100,
            service_revision=args.source_revision,
        )
        result = evaluate(
            manifest,
            destination,
            args.source_revision,
            bounded=bounded,
            graph_settings=settings,
            graph_factory=runtime_factory,
            graph_spend=lambda: evaluation_spend_snapshot(
                SecretStr(values['postgres_private_dsn']), SecretStr(values['postgres_knowledge_dsn']), clock
            ),
            embedding_receipts=receipts,
            retrieval_receipts=retrievals,
        )
        print(
            json.dumps(
                {
                    key: value
                    for key, value in result.items()
                    if key not in ('cases', 'usage_receipts', 'embedding_receipts')
                },
                indent=2,
            )
        )
        return (
            1
            if result['stop_reason'] or result['structural_flagged_queries'] or result['history_mismatches']
            else 0
        )


if __name__ == '__main__':
    sys.excepthook = safe_exception_hook
    raise SystemExit(main())
