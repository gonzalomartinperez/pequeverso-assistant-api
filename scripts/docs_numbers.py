"""Refresh the evaluation reference from repository fixtures and offline retrieval."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals import schema
from scripts import evaluate_corpus

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "docs" / "reference" / "evaluation.md"
START = "<!-- generated:eval-numbers:start -->"
END = "<!-- generated:eval-numbers:end -->"


def fixture_count(filename: str, key: str) -> int:
    """Count entries in a JSON evaluation fixture."""
    return len(json.loads((ROOT / "evals" / filename).read_text(encoding="utf-8"))[key])


def render_table() -> str:
    """Measure active cases using the same retrieval evaluator as the ratchet."""
    cases = [case for case in evaluate_corpus.load() if case["status"] == "active"]
    families = {case["family"] for case in cases}
    overall = evaluate_corpus.retrieval(cases)["overall"]
    scored = overall["cases"]
    explicitly_empty = sum(case["gold_evidence_ids"] == [] for case in cases)
    golden = sum(item["status"] == "active" for item in schema.load(schema.GOLDEN))
    attacks = sum(item["status"] == "active" for item in schema.load(schema.RED_TEAM))

    metrics = ", ".join(
        f"{label} = {overall[key]:.3f}" if overall[key] is not None else f"{label} = n/a"
        for label, key in (
            ("recall@3", "recall_at_3"),
            ("recall@5", "recall_at_5"),
            ("nDCG@5", "ndcg_at_5"),
            ("MRR", "mrr"),
        )
    )
    return "\n".join(
        [
            "| Suite | Cases and metrics |",
            "| --- | --- |",
            f"| Full set | {len(cases)} active items across {len(families)} intent families |",
            f"| Full-set retrieval | {scored} scored cases, {explicitly_empty} explicitly empty gold lists. {metrics} |",
            f"| Golden set | {golden} active items |",
            f"| Red-team pack | {attacks} active attacks |",
            f"| Guards | {fixture_count('guards.json', 'cases')} scripted cases |",
            f"| Conversations | {fixture_count('conversations.json', 'scenarios')} scenarios |",
            f"| Legacy retrieval | {fixture_count('retrieval.json', 'cases')} cases |",
        ]
    )


def update_document(path: Path, *, check: bool) -> int:
    """Refresh the marked block or return a failing status without writing."""
    document = path.read_text(encoding="utf-8")
    try:
        before, remainder = document.split(f"{START}\n")
        _, after = remainder.split(f"{END}\n")
    except ValueError:
        print(f"{path}: expected one generated evaluation numbers block with both markers.")
        return 1

    updated = f"{before}{START}\n\n{render_table()}\n\n{END}\n{after}"
    if document == updated:
        return 0
    if check:
        print(f"{path}: stale evaluation numbers. Run uv run python -m scripts.docs_numbers.")
        return 1
    path.write_text(updated, encoding="utf-8")
    return 0


def main() -> int:
    """Run the documentation generator or its read-only check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the generated block is stale")
    return update_document(DOCUMENT, check=parser.parse_args().check)


if __name__ == "__main__":
    raise SystemExit(main())
