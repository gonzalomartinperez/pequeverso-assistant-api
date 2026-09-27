"""Retrieval evaluation over the committed catalog (deterministic, no model calls).

uv run python scripts/evaluate_retrieval.py [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.adapters.catalog_schema import CatalogParser
from app.ai.evidence import passages, rank
from app.bootstrap.config import DEFAULT_CATALOG, Settings


def evaluate(k: int = 3) -> dict[str, Any]:
    hosts = frozenset(Settings.model_fields['catalog_allowed_hosts'].default)
    catalog = CatalogParser(hosts)(DEFAULT_CATALOG.read_bytes())
    items = passages(catalog)
    cases = json.loads((ROOT / 'evals' / 'retrieval.json').read_text())['cases']
    results = []
    for case in cases:
        ranked = [p.id for p, score in rank(case['query'], items) if score > 0]
        positions = [ranked.index(r) + 1 for r in case['relevant'] if r in ranked]
        best = min(positions) if positions else None
        results.append({'query': case['query'], 'best_rank': best, 'top': ranked[:k]})
    hits = sum(1 for r in results if r['best_rank'] is not None and r['best_rank'] <= k)
    mrr = sum(1 / r['best_rank'] for r in results if r['best_rank']) / len(results)
    return {
        'cases': len(results),
        f'recall_at_{k}': hits / len(results),
        'mrr': round(mrr, 3),
        'misses': [r for r in results if r['best_rank'] is None or r['best_rank'] > k],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', action='store_true')
    report = evaluate()
    if parser.parse_args().json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f'cases={report["cases"]} recall@3={report["recall_at_3"]:.2f} mrr={report["mrr"]}')
        for miss in report['misses']:
            print(f'  miss: {miss["query"]!r} best={miss["best_rank"]} top={miss["top"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
