"""Run a finite post-adjustment matrix against the same existing live evaluation allowance.

This is targeted revalidation, never an independent holdout or a replacement for the frozen
>=200-query baseline. Existing cases must be byte-equivalent as parsed JSON, and new variants
must be identified separately. No automatic generation retry or new paid allowance is created.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.bootstrap.config import DEFAULT_CATALOG
from scripts.evaluate_end_to_end import digest, evaluate, load_live_provider, write_private
from scripts.resume_end_to_end import verify_existing_budget

MAX_REVALIDATION_QUERIES = 64


def validate_matrix(manifest: dict[str, Any], baseline: dict[str, Any]) -> dict[str, int]:
    """Reject changed baseline cases, duplicate keys and an unbounded new paid matrix."""
    originals = baseline['cases']
    if sum(len(c['turns']) for c in originals) < 200:
        raise ValueError('revalidation requires the original >=200-query baseline')
    if manifest.get('phase') != 'post-adjustment targeted revalidation; not independent holdout':
        raise ValueError('revalidation must declare its non-independent phase')
    by_id = {c['id']: c for c in originals}
    if len(by_id) != len(originals):
        raise ValueError('baseline ids must be unique')
    ids: set[str] = set()
    repeats = variants = queries = 0
    for case in manifest['cases']:
        case_id = case['id']
        if not isinstance(case_id, str) or case_id in ids:
            raise ValueError('revalidation ids must be unique strings')
        ids.add(case_id)
        turns = case['turns']
        if not turns or any(
            not isinstance(t.get('question'), str) or not 1 <= len(t['question']) <= 4000 for t in turns
        ):
            raise ValueError('revalidation needs bounded nonempty visitor turns')
        if case_id in by_id:
            if case != by_id[case_id]:
                raise ValueError('a repeated baseline case must remain unchanged')
            repeats += 1
        elif case_id.startswith('revalidation-') and case.get('relation') == 'new_variant':
            variants += 1
        else:
            raise ValueError('new cases must be explicitly identified as revalidation variants')
        queries += len(turns)
    if not repeats or not variants or not 1 <= queries <= MAX_REVALIDATION_QUERIES:
        raise ValueError('revalidation must mix unchanged affected cases and new variants within 64 queries')
    if manifest.get('query_count') != queries:
        raise ValueError('declared query count does not match the frozen cases')
    if manifest.get('reply_policy') != 'spanish_native':
        raise ValueError('the current revalidation must declare the Spanish native policy')
    expected_keys = {f'{c["id"]}:{n + 1}' for c in manifest['cases'] for n, _ in enumerate(c['turns'])}
    expectations = manifest.get('policy_expected_languages')
    if (
        not isinstance(expectations, dict)
        or set(expectations) != expected_keys
        or any(value not in ('es', 'unsupported') for value in expectations.values())
    ):
        raise ValueError('each turn needs an explicit Spanish-policy expectation outside baseline cases')
    return {'queries': queries, 'repeated_cases': repeats, 'new_variant_cases': variants}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--baseline-manifest', type=Path, required=True)
    parser.add_argument('--previous-run', type=Path, required=True)
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--budget-state', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--source-revision', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    for name in ('httpx', 'httpx2', 'httpcore', 'httpcore2', 'openai'):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    manifest = json.loads(args.manifest.read_text())
    baseline = json.loads(args.baseline_manifest.read_text())
    if manifest.get('baseline_manifest_sha256') != digest(args.baseline_manifest.read_bytes()):
        parser.error('the baseline manifest does not match its frozen digest')
    counts = validate_matrix(manifest, baseline)
    verify_existing_budget(args.previous_run, args.budget_state, terminal_only=False)
    destination = args.output_dir.resolve()
    if destination.is_relative_to(ROOT) or destination.exists():
        parser.error('output must be a new private directory outside the repository')
    bounded = load_live_provider(args.key_file, args.budget_state)
    destination.mkdir(parents=True, mode=0o700)
    write_private(destination / 'manifest.json', manifest)
    write_private(
        destination / 'revalidation-receipt.json',
        {
            **counts,
            'phase': manifest['phase'],
            'reply_policy': manifest['reply_policy'],
            'baseline_manifest_sha256': digest(args.baseline_manifest.read_bytes()),
            'manifest_sha256': digest(args.manifest.read_bytes()),
            'catalog_sha256': digest(DEFAULT_CATALOG.read_bytes()),
            'source_revision': args.source_revision,
            'budget_before': bounded.envelope.snapshot(),
            'automatic_generation_retries': 0,
        },
    )
    (destination / 'catalog.json').write_bytes(DEFAULT_CATALOG.read_bytes())
    (destination / 'catalog.json').chmod(0o600)
    summary = evaluate(manifest, destination, args.source_revision, bounded=bounded)
    print(json.dumps({k: v for k, v in summary.items() if k not in ('cases', 'usage_receipts')}, indent=2))
    if summary['stop_reason']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
