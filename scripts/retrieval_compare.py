"""Paired comparison of two retriever versions on the full set (PVA-M2.6 part B).

Per-case results (ids and ranks only, no text) are saved for a version, then two saves are compared
with a paired bootstrap over cases (fixed seed, stdlib only) on recall@5 and nDCG@5.

    uv run python -m scripts.retrieval_compare --save /tmp/step1.json
    uv run python -m scripts.retrieval_compare --compare /tmp/base.json /tmp/step1.json [--split dev]

The p-value is one-sided: the share of bootstrap resamples where the mean paired difference is <= 0
(small means the candidate is better). Cases are resampled with replacement as independent units.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from statistics import fmean
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

SEED = 20261114
RESAMPLES = 10000


def _hit(row: dict[str, Any], k: int) -> float:
    best = row["best_rank"]
    return 1.0 if best and best <= k else 0.0


def paired_bootstrap(diffs: list[float], seed: int = SEED, resamples: int = RESAMPLES) -> float:
    """One-sided p: share of resampled mean differences that are <= 0."""
    if not diffs:
        return 1.0
    rng = random.Random(seed)  # noqa: S311 - reproducible statistics, not cryptography
    n = len(diffs)
    not_better = 0
    for _ in range(resamples):
        if sum(diffs[rng.randrange(n)] for _ in range(n)) <= 0:
            not_better += 1
    return (not_better + 1) / (resamples + 1)


def compare(
    before: list[dict[str, Any]], after: list[dict[str, Any]], split: str | None = None
) -> dict[str, Any]:
    old = {r["id"]: r for r in before if split in (None, r["split"])}
    new = {r["id"]: r for r in after if split in (None, r["split"])}
    ids = sorted(old.keys() & new.keys())
    out: dict[str, Any] = {"cases": len(ids), "split": split or "all"}
    metrics: tuple[tuple[str, Callable[[dict[str, Any]], float]], ...] = (
        ("recall_at_5", lambda r: _hit(r, 5)),
        ("recall_at_3", lambda r: _hit(r, 3)),
        ("ndcg_at_5", lambda r: r["ndcg_at_5"]),
        ("mrr", lambda r: 1 / r["best_rank"] if r["best_rank"] else 0.0),
    )
    for name, value in metrics:
        diffs = [value(new[i]) - value(old[i]) for i in ids]
        out[name] = {
            "before": round(fmean(value(old[i]) for i in ids), 3) if ids else None,
            "after": round(fmean(value(new[i]) for i in ids), 3) if ids else None,
            "mean_diff": round(fmean(diffs), 4) if diffs else None,
            "p_one_sided": round(paired_bootstrap(diffs), 4),
            "improved": sum(d > 0 for d in diffs),
            "worsened": sum(d < 0 for d in diffs),
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", type=Path, help="measure the current retriever and save per case")
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("BEFORE", "AFTER"))
    parser.add_argument("--split", choices=("dev", "holdout"))
    args = parser.parse_args()
    if args.save:
        from scripts import evaluate_corpus as corpus

        report = corpus.retrieval(corpus.load())
        args.save.write_text(json.dumps(report["per_case"], ensure_ascii=False) + "\n")
        return 0
    if args.compare:
        before, after = (json.loads(p.read_text()) for p in args.compare)
        print(json.dumps(compare(before, after, args.split), indent=2))
        return 0
    parser.error("give --save or --compare")
    return 2


if __name__ == "__main__":
    sys.exit(main())
