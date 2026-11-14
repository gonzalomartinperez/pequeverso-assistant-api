r"""Scorecard aggregation (PVA-M2.12): measured inputs to `scorecard.json`, failing on regression.

Each metric has a committed baseline in `ratchets/` and a direction (`min`: must stay at or above the
baseline, `max`: at or below). The scorecard maps metrics to the rubric axes of
`docs/master-plan/scorecard.md` and reports, per axis, which automatic criteria pass. A metric without
an input in this run is `unmeasured` (never a pass); a metric worse than its baseline is a regression and
makes the exit code 1. Judgement axes (narrative quality, CRO) are scored by an independent evaluator,
not here.

    uv run python -m scripts.scorecard --golden golden.json --coverage coverage.json \\
        --load sse-load.json --out scorecard.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[1]
RATCHETS = ROOT / "ratchets"
SCHEMA_VERSION = 1
Direction = Literal["min", "max"]


@dataclass(frozen=True)
class Metric:
    """One measured value against its committed baseline."""

    name: str
    axis: str
    value: float | None
    baseline: float | None
    direction: Direction
    source: str

    @property
    def status(self) -> str:
        """Return `unmeasured`, `regressed` or `ok`."""
        if self.value is None or self.baseline is None:
            return "unmeasured"
        worse = (
            self.value < self.baseline if self.direction == "min" else self.value > self.baseline
        )
        return "regressed" if worse else "ok"


def _ratchet(name: str) -> dict[str, Any] | None:
    path = RATCHETS / name
    if not path.is_file():
        return None
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _read(path: Path | None) -> dict[str, Any] | None:
    """Return a JSON report, or None when absent or unreadable (main fails on requested ones)."""
    if path is None or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError, UnicodeDecodeError:
        return None
    return data if isinstance(data, dict) else None


# --- measurements (each returns metrics; a missing input yields `unmeasured`) ----------------------


def static_metrics() -> list[Metric]:
    """Ruff legacy findings, complexity and import contracts, measured from the working tree."""
    from scripts import complexity_ratchet, ruff_ratchet

    ruff = _ratchet("ruff.json")
    complexity = _ratchet("complexity.json")
    functions = complexity_ratchet.findings()
    contracts = subprocess.run(
        [str(Path(sys.executable).parent / "lint-imports"), "--no-cache"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    broken = re.search(r"Contracts: \d+ kept, (\d+) broken", contracts.stdout)
    return [
        Metric(
            "ruff_legacy_findings",
            "D2",
            float(len(ruff_ratchet.findings())),
            None if ruff is None else float(ruff["total"]),
            "max",
            "scripts/ruff_ratchet.py",
        ),
        Metric(
            "functions_above_complexity_10",
            "D2",
            float(len(functions)),
            None if complexity is None else float(len(complexity["functions"])),
            "max",
            "scripts/complexity_ratchet.py",
        ),
        Metric(
            "max_function_complexity",
            "D2",
            float(max(functions.values(), default=0)),
            None if complexity is None else float(max(complexity["functions"].values(), default=0)),
            "max",
            "scripts/complexity_ratchet.py",
        ),
        Metric(
            "import_contracts_broken",
            "D1",
            None if broken is None else float(broken[1]),
            0.0,
            "max",
            "lint-imports",
        ),
    ]


def coverage_metrics(report: dict[str, Any] | None) -> list[Metric]:
    """Static-lane branch coverage against `static_branch_floor` in `ratchets/coverage.json`.

    The nightly job runs the static suite only (no PostgreSQL or Neo4j), so it is compared with the
    static floor; the combined floor is enforced by the CI database job. A report without branch
    data is `unmeasured`, never a pass.
    """
    from scripts import coverage_gate

    floors = _ratchet("coverage.json")
    value = None
    if report is not None:
        try:
            value = coverage_gate.branch_percent(report)
        except SystemExit:
            value = None
    baseline = None if floors is None else float(floors["static_branch_floor"])
    return [Metric("static_branch_coverage_percent", "D3", value, baseline, "min", "coverage.py")]


def golden_metrics(report: dict[str, Any] | None) -> list[Metric]:
    """Golden replay: 100% of the items in `ratchets/golden.json` must pass."""
    golden = _ratchet("golden.json")
    items = passed = unused = None
    if report is not None:
        items = float(report["overall"]["items"])
        passed = 100.0 * report["overall"]["passed"] / max(1, report["overall"]["items"])
        unused = float(len(report.get("unused_cassettes", [])))
    return [
        Metric("golden_unused_cassettes", "P3", unused, 0.0, "max", "evals/runner.py"),
        Metric(
            "golden_items",
            "P3",
            items,
            None if golden is None else float(golden["items"]),
            "min",
            "evals/runner.py",
        ),
        Metric(
            "golden_pass_percent",
            "P3",
            passed,
            None if golden is None else float(golden["pass_percent"]),
            "min",
            "evals/runner.py",
        ),
    ]


# Absolute harness limits (tests/load/sse_load.py), the ceiling until ratchets/perf.json records a
# measured baseline (then the baseline plus a 20% budget, never above these limits).
LOAD_LIMITS = {"ttfe_p95_seconds": 1.5, "gap_p95_seconds": 0.5}


def load_metrics(report: dict[str, Any] | None) -> list[Metric]:
    """SSE load (fixture provider): latencies, error rate and the harness's own threshold checks."""
    perf = _ratchet("perf.json") or {}
    values: dict[str, float | None] = dict.fromkeys(LOAD_LIMITS)
    error = failed = None
    if report is not None:
        values = {
            "ttfe_p95_seconds": report["ttfe_seconds"]["p95"],
            "gap_p95_seconds": report["gap_seconds"]["p95"],
        }
        error = 100.0 * float(report["error_rate"])
        # observations, premature closes and RSS growth: any False check counts.
        failed = float(sum(value is False for value in report.get("checks", {}).values()))
    source = "tests/load/sse_load.py"
    metrics = []
    for name, value in values.items():
        limit = LOAD_LIMITS[name]
        base = min(limit, float(perf[name]) * 1.2) if name in perf else limit
        metrics.append(Metric(name, "D6", value, base, "max", source))
    metrics.append(Metric("load_error_percent", "D6", error, 0.5, "max", source))
    metrics.append(Metric("load_checks_failed", "D6", failed, 0.0, "max", source))
    return metrics


def mutation_metrics() -> list[Metric]:
    """Read the committed mutation scores per module (measured by the weekly run)."""
    mutation = _ratchet("mutation.json")
    if mutation is None:
        return [Metric("mutation_score_min_module", "D3", None, None, "min", "mutmut")]
    scores = [float(v) for v in mutation.get("modules", {}).values()]
    value = min(scores) if scores else None
    return [
        Metric(
            "mutation_score_min_module",
            "D3",
            value,
            float(mutation.get("pr_break", 60)),
            "min",
            "ratchets/mutation.json",
        )
    ]


def retrieval_metrics() -> list[Metric]:
    """Lexical retrieval recall@3 over the corpus against `ratchets/retrieval.json`."""
    from scripts import evaluate_corpus

    retrieval = _ratchet("retrieval.json")
    measured = evaluate_corpus.retrieval(evaluate_corpus.load())
    value = measured["overall"].get(f"recall_at_{evaluate_corpus.K}")
    baseline = (
        None if retrieval is None else retrieval["overall"].get(f"recall_at_{evaluate_corpus.K}")
    )
    return [
        Metric(
            f"retrieval_recall_at_{evaluate_corpus.K}",
            "P3",
            value,
            baseline,
            "min",
            "scripts/evaluate_corpus.py",
        )
    ]


AXES = {
    "D1": "Architecture",
    "D2": "Code quality",
    "D3": "Tests",
    "D6": "Performance",
    "P3": "Assistant message quality",
}


def build(metrics: list[Metric], revision: str, generated_at: str) -> dict[str, Any]:
    """Assemble the scorecard document."""
    axes = {}
    for axis, title in AXES.items():
        members = [m for m in metrics if m.axis == axis]
        axes[axis] = {
            "title": title,
            "criteria": {m.name: m.status for m in members},
            "automatic_pass": bool(members) and all(m.status == "ok" for m in members),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": revision,
        "generated_at": generated_at,
        "metrics": {m.name: {**asdict(m), "status": m.status} for m in metrics},
        "axes": axes,
        "regressions": sorted(m.name for m in metrics if m.status == "regressed"),
        "unmeasured": sorted(m.name for m in metrics if m.status == "unmeasured"),
    }


def _revision() -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() or "unknown"


Collector = Callable[[], list[Metric]]
# Metrics that must be measured when their input group is requested (mutation is read from the
# committed ratchet and may legitimately be unmeasured until PVA-M2.9 records a baseline).
GROUPS = {
    "coverage": ("static_branch_coverage_percent",),
    "golden": ("golden_items", "golden_pass_percent", "golden_unused_cassettes"),
    "load": ("ttfe_p95_seconds", "gap_p95_seconds", "load_error_percent", "load_checks_failed"),
    "static": (
        "ruff_legacy_findings",
        "functions_above_complexity_10",
        "max_function_complexity",
        "import_contracts_broken",
    ),
}


def main(argv: list[str] | None = None) -> int:
    """Measure, write `scorecard.json` and fail on any regression."""
    parser = argparse.ArgumentParser(description="Aggregate quality inputs into scorecard.json.")
    parser.add_argument("--coverage", type=Path, help="coverage.py JSON report")
    parser.add_argument("--golden", type=Path, help="evals.runner golden replay report")
    parser.add_argument("--load", type=Path, help="tests.load.sse_load report")
    parser.add_argument("--generated-at", default="", help="timestamp to record (ISO 8601)")
    parser.add_argument("--out", type=Path, default=Path("scorecard.json"))
    parser.add_argument("--skip-static", action="store_true", help="skip the working-tree metrics")
    args = parser.parse_args(argv)
    metrics = [
        *([] if args.skip_static else static_metrics()),
        *coverage_metrics(_read(args.coverage)),
        *golden_metrics(_read(args.golden)),
        *load_metrics(_read(args.load)),
        *mutation_metrics(),
        *([] if args.skip_static else retrieval_metrics()),
    ]
    document = build(metrics, _revision(), args.generated_at)
    # A requested input that was not produced or is unusable (a crashed step, no branch data, no
    # completed run) fails, as does an unmeasured static metric: never a silent pass.
    requested = {
        "coverage": args.coverage is not None,
        "golden": args.golden is not None,
        "load": args.load is not None,
        "static": not args.skip_static,
    }
    missing = [
        str(path) for path in (args.coverage, args.golden, args.load) if path and not path.is_file()
    ]
    missing += [
        f"{name} (unmeasured)"
        for group, names in GROUPS.items()
        if requested[group]
        for name in names
        if name in document["metrics"] and document["metrics"][name]["status"] == "unmeasured"
    ]
    document["missing_inputs"] = missing
    args.out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    for name in document["regressions"]:
        metric = document["metrics"][name]
        sys.stderr.write(
            f"regression: {name} = {metric['value']} ({metric['direction']} baseline {metric['baseline']})\n"
        )
    sys.stdout.write(
        f"scorecard: {len(metrics)} metrics, {len(document['regressions'])} regressions, "
        f"{len(document['unmeasured'])} unmeasured -> {args.out}\n"
    )
    for path in missing:
        sys.stderr.write(f"missing input: {path}\n")
    return 1 if document["regressions"] or missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
