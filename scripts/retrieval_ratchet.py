"""Retrieval ratchet and baseline report of the full set (PVA-M2.6).

`ratchets/retrieval.json` records recall@3, recall@5, nDCG@5 and MRR overall, per family and per input
language (`locale`); a measurement below it fails (`tests/test_retrieval_ratchet.py`), so values only
rise. `evals/full/baseline/corpus-fixture.json` is the committed baseline: counts and metrics with the
catalog pin, no transcripts (ids only). Offline and deterministic (lexical retriever, no model calls).

    uv run python -m scripts.retrieval_ratchet                    # check
    uv run python -m scripts.retrieval_ratchet --update           # raise the ratchet (never lowers)
    uv run python -m scripts.retrieval_ratchet --write-baseline   # regenerate the baseline report
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import evaluate_conversations as conv
from scripts import evaluate_corpus as corpus

RATCHET = ROOT / "ratchets" / "retrieval.json"
BASELINE = ROOT / "evals" / "full" / "baseline" / "corpus-fixture.json"
METRICS = ("recall_at_3", "recall_at_5", "ndcg_at_5", "mrr")
GROUPS = ("by_family", "by_language")
# Reference points: the recorded 2026-11-09 baseline, and the same retriever measured at PVA-M2.6 on
# the 190 cases that carried labels in corpus v1, with their original labels.
REFERENCE = {
    "recorded_2026_11_09": {"cases": 190, "recall_at_3": 0.689, "recall_at_5": 0.737, "mrr": 0.603},
    "remeasured_v1_labels_at_m2_6": {
        "cases": 190,
        "recall_at_3": 0.689,
        "recall_at_5": 0.737,
        "mrr": 0.603,
    },
}


def measure(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the ratchet-shaped metrics: overall, by_family and by_language."""
    report = corpus.retrieval(cases)
    return {
        "overall": report["overall"],
        **{group: {k: v for k, v in report[group].items() if v["cases"]} for group in GROUPS},
    }


def check(measured: dict[str, Any], ratchet: dict[str, Any]) -> list[str]:
    """Every metric that dropped below the committed ratchet, plus groups that vanished."""
    problems: list[str] = []
    blocks = [("overall", ratchet["overall"], measured["overall"])]
    for group in GROUPS:
        for name, floor in ratchet[group].items():
            if name not in measured[group]:
                problems.append(f"{group}.{name}: no scored case left")
                continue
            blocks.append((f"{group}.{name}", floor, measured[group][name]))
    for label, floor, value in blocks:
        problems += [
            f"{label}.{metric}: {value[metric]} is below the ratchet {floor[metric]}"
            for metric in METRICS
            if value[metric] < floor[metric]
        ]
    return problems


def raised(measured: dict[str, Any], ratchet: dict[str, Any] | None) -> dict[str, Any]:
    """Return the ratchet with every metric at the max of the committed and the measured value."""

    def merge(now: dict[str, Any], old: dict[str, Any] | None) -> dict[str, Any]:
        best = {m: max(now[m], (old or {}).get(m, 0.0)) for m in METRICS}
        return {"cases": now["cases"], **best}

    return {
        "schema_version": 1,
        "description": "Retrieval metrics of the full set; every value only rises (PVA-M2.6).",
        "k": corpus.K,
        "corpus_version": corpus.CORPUS_VERSION,
        "overall": merge(measured["overall"], (ratchet or {}).get("overall")),
        **{
            group: {
                name: merge(value, ((ratchet or {}).get(group) or {}).get(name))
                for name, value in measured[group].items()
            }
            for group in GROUPS
        },
    }


def counts(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Case counts per family, split, locale, behavior, provenance and abstain reason."""

    def by(key: str) -> dict[str, int]:
        return dict(sorted(Counter(str(c.get(key)) for c in cases).items()))

    return {
        "total": len(cases),
        "scored": sum(bool(c["gold_evidence_ids"]) for c in cases),
        "unscored_by_reason": dict(
            sorted(Counter(c["abstain_reason"] for c in cases if c.get("abstain_reason")).items())
        ),
        "by_family": by("family"),
        "by_split": by("split"),
        "by_locale": by("locale"),
        "by_response_language": by("response_language"),
        "by_behavior": by("expected_behavior"),
        "by_provenance": by("provenance"),
    }


def baseline(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the committed baseline report: no case text, ids only."""
    report = corpus.retrieval(cases)
    return {
        "schema_version": 1,
        "corpus_version": corpus.CORPUS_VERSION,
        "catalog_sha256": corpus.catalog_sha256(),
        "catalog_revision": conv.CATALOG.source_revision,
        "mode": "fixture",
        "metrics_engine": "stdlib (scripts/evaluate_corpus.py); ranx spike not adopted, see docs/reference/evaluation.md",
        "retriever": "lexical (app/ai/evidence.py) with Spanish folding and the query lexicon (PVA-M2.6 part B)",
        "cases": counts(cases),
        "retrieval": {k: report[k] for k in ("overall", "by_split", "by_family", "by_language")},
        "misses_at_3": [{k: m[k] for k in ("id", "family", "best_rank")} for m in report["misses"]],
        "reference": REFERENCE,
    }


def _write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="raise the ratchet (never lowers)")
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args()
    cases = corpus.load()
    if problems := corpus.validate(cases):
        print("\n".join(problems))
        return 1
    measured = measure(cases)
    ratchet = json.loads(RATCHET.read_text(encoding="utf-8")) if RATCHET.exists() else None
    if args.write_baseline:
        _write(BASELINE, baseline(cases))
    if args.update:
        _write(RATCHET, raised(measured, ratchet))
        return 0
    if ratchet is None:
        print("ratchets/retrieval.json is missing; run with --update")
        return 1
    problems = check(measured, ratchet)
    print("\n".join(problems) or "retrieval ratchet holds")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
