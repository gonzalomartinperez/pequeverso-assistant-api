"""Continue a frozen >=200-query matrix without repeating completed provider requests.

Previous artifacts remain immutable. A final terminal checkpoint can establish completion
when the harness died before its answer checkpoint; it does not establish HTTP replay or
history verification. Partially completed multi-turn cases cannot be resumed without their
original session and are rejected. All segments share the same conservative budget ledger.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluate_end_to_end import digest, evaluate, load_live_provider, write_private
from scripts.real_eval_budget import CAP_MICRO


def verify_existing_budget(previous: Path, state: Path, terminal_only: bool) -> None:
    """A typo must never create a new paid allowance when continuing a previous run."""
    if not state.is_file() or state.is_symlink():
        raise ValueError('continuation requires the existing shared budget file')
    old = json.loads((previous / 'budget.json').read_text())
    with sqlite3.connect(state.resolve().as_uri() + '?mode=ro', uri=True) as db:
        count, amount = db.execute('SELECT count(*),coalesce(sum(reserved),0) FROM attempts').fetchone()
        cap = db.execute('SELECT cap FROM limits').fetchone()
        stopped = db.execute('SELECT reason FROM status LIMIT 1').fetchone()
    required = old['attempts'] + int(terminal_only)
    if not cap or not 0 < cap[0] <= CAP_MICRO or count < required or amount < old['reserved_micro_usd']:
        raise ValueError('budget does not preserve the previous run allowance')
    if stopped:
        raise ValueError('the shared budget is stopped; never reset it for continuation')


def remaining_cases(manifest: dict[str, Any], previous: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Only completed frozen case/turn keys can be removed; never synthesize answers."""
    if sum(len(c['turns']) for c in manifest['cases']) < 200:
        raise ValueError('the original frozen matrix must contain at least 200 queries')
    original = json.loads((previous / 'manifest.json').read_text())
    if original != manifest:
        raise ValueError('previous artifacts do not match the frozen manifest')
    allowed = {(c['id'], n + 1) for c in manifest['cases'] for n, _ in enumerate(c['turns'])}
    rows = json.loads((previous / 'answers.json').read_text())
    completed: set[tuple[str, int]] = set()
    for row in rows:
        key = (row['case_id'], row['turn'])
        if key not in allowed or key in completed or row['terminal'] != ['run.completed']:
            raise ValueError('previous answer checkpoint is not safely resumable')
        completed.add(key)
    terminal_only: dict[str, Any] | None = None
    checkpoint_file = previous / 'inflight.json'
    if checkpoint_file.exists():
        checkpoint = json.loads(checkpoint_file.read_text())
        key = (checkpoint['case_id'], checkpoint['turn'])
        if key not in allowed:
            raise ValueError('unknown inflight turn')
        if key not in completed:
            events = checkpoint['events']
            if (
                not events
                or events[-1]['type'] != 'run.completed'
                or sum(e['type'] == 'message.completed' for e in events) != 1
            ):
                raise ValueError('inflight request has no final completion; never retry it automatically')
            completed.add(key)
            terminal_only = {
                'case_id': key[0],
                'turn': key[1],
                'proof': 'message.completed and run.completed in immutable inflight checkpoint',
                'http_history_and_replay_verified': False,
            }
    remaining = []
    for case in manifest['cases']:
        keys = {(case['id'], n + 1) for n, _ in enumerate(case['turns'])}
        if keys <= completed:
            continue
        if keys & completed:
            raise ValueError('cannot recreate a partially completed conversation without its session')
        remaining.append(case)
    if not remaining:
        raise ValueError('no remaining queries; do not repeat a completed matrix')
    report = {
        'original_queries': len(allowed),
        'previous_answer_checkpoints': len(rows),
        'completed_keys_skipped': len(completed),
        'terminal_only_completion': terminal_only,
        'remaining_queries': sum(len(c['turns']) for c in remaining),
        'previous_answers_sha256': digest((previous / 'answers.json').read_bytes()),
        'previous_manifest_sha256': digest((previous / 'manifest.json').read_bytes()),
        'previous_inflight_sha256': digest(checkpoint_file.read_bytes())
        if checkpoint_file.exists()
        else None,
        'automatic_generation_retries': 0,
    }
    return {**manifest, 'cases': remaining}, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
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
    remaining, receipt = remaining_cases(manifest, args.previous_run)
    verify_existing_budget(
        args.previous_run, args.budget_state, receipt['terminal_only_completion'] is not None
    )
    destination = args.output_dir.resolve()
    if destination.is_relative_to(ROOT) or destination.exists():
        parser.error('output must be a new private directory outside the repository')
    bounded = load_live_provider(args.key_file, args.budget_state)
    destination.mkdir(parents=True, mode=0o700)
    write_private(destination / 'manifest.json', remaining)
    write_private(destination / 'original-manifest.json', manifest)
    write_private(destination / 'continuation-receipt.json', receipt)
    catalog = args.previous_run / 'catalog.json'
    from scripts.evaluate_end_to_end import DEFAULT_CATALOG

    if catalog.read_bytes() != DEFAULT_CATALOG.read_bytes():
        raise ValueError('continuation cannot silently change the original catalog')
    (destination / 'catalog.json').write_bytes(catalog.read_bytes())
    (destination / 'catalog.json').chmod(0o600)
    summary = evaluate(remaining, destination, args.source_revision, bounded=bounded)
    print(json.dumps({k: v for k, v in summary.items() if k not in ('cases', 'usage_receipts')}, indent=2))
    if summary['stop_reason']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
