"""Check scoped mutmut 3.8 JSON metadata; never run mutation tests from this CLI.

Scores are raw killed / (killed + survived + timeout + suspicious) percentages.
Equivalent-mutant annotations are review evidence and do not inflate the scores.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "ratchets/mutation.json"
SCOPED_FILES = frozenset(
    {
        "app/application/answers.py",
        "app/application/sessions.py",
        "app/application/embedding_budget.py",
        "app/ai/prompt.py",
        "app/ai/evidence.py",
        "app/ai/output.py",
    }
)
# mutmut.stats.status_by_exit_code in 3.8.1. Unexpected exits (including crashes)
# count as suspicious rather than silently improving a score.
IGNORED_CODES = {None, 2, 5, 33, 34, 37}
TIMEOUT_CODES = {36, -24, 24, 152, 255}


def scoped(path: str) -> bool:
    return path in SCOPED_FILES or (path.startswith("app/domain/") and path.endswith(".py"))


def mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError("expected a JSON object with string keys")
    return dict(value)


def percentage(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("expected a percentage")
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 100:
        raise ValueError("percentage must be finite and between 0 and 100")
    return number


@dataclass
class Baseline:
    pr_break: float
    weekly_target: float
    modules: dict[str, float]
    equivalent_mutants: dict[str, str]

    @classmethod
    def load(cls, path: Path) -> Baseline:
        data = mapping(json.loads(path.read_text(encoding="utf-8")))
        if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
            raise ValueError("unsupported mutation ratchet schema")
        modules = {key: percentage(value) for key, value in mapping(data["modules"]).items()}
        if any(not scoped(key) for key in modules):
            raise ValueError("baseline contains a module outside the mutation scope")
        equivalents = mapping(data["equivalent_mutants"])
        if any(
            not isinstance(reason, str) or not reason.strip() for reason in equivalents.values()
        ):
            raise ValueError("equivalent mutants require non-empty reasons")
        return cls(
            percentage(data["pr_break"]),
            percentage(data["weekly_target"]),
            modules,
            {key: str(reason) for key, reason in equivalents.items()},
        )

    def write(self, path: Path, scores: dict[str, float]) -> None:
        """Raise measured values only; preserve unmeasured modules and annotations."""
        raised = self.modules.copy()
        for module, score in scores.items():
            raised[module] = max(raised.get(module, 0.0), percentage(score))
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "pr_break": self.pr_break,
                    "weekly_target": self.weekly_target,
                    "modules": dict(sorted(raised.items())),
                    "equivalent_mutants": self.equivalent_mutants,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


@dataclass
class Results:
    killed: int = 0
    survived: int = 0
    timeout: int = 0
    suspicious: int = 0
    excluded: int = 0

    def add(self, code: object) -> None:
        if code is not None and type(code) is not int:
            raise ValueError("mutmut exit code must be an integer or null")
        if code in IGNORED_CODES:
            self.excluded += 1
        elif code in {1, 3}:
            self.killed += 1
        elif code == 0:
            self.survived += 1
        elif code in TIMEOUT_CODES:
            self.timeout += 1
        else:
            self.suspicious += 1

    @property
    def score(self) -> float | None:
        total = self.killed + self.survived + self.timeout + self.suspicious
        return round(100 * self.killed / total, 2) if total else None


def read_results(directory: Path) -> dict[str, Results]:
    """Read SourceFileMutationData.exit_code_by_key without importing mutmut."""
    results: dict[str, Results] = {}
    for path in sorted(directory.rglob("*.py.meta")):
        module = path.relative_to(directory).as_posix().removesuffix(".meta")
        if not scoped(module):
            continue
        data = mapping(json.loads(path.read_text(encoding="utf-8")))
        codes = mapping(data["exit_code_by_key"])
        result = Results()
        for code in codes.values():
            result.add(code)
        results[module] = result
    return results


# A change to these files re-measures the whole scope (the run that records the baseline).
FULL_SCOPE_TRIGGERS = frozenset({".github/workflows/mutation.yml", "scripts/mutation_ratchet.py"})


def patterns(changed: list[str]) -> list[str] | None:
    """Return mutmut name patterns for changed scoped modules; None means the full scope."""
    paths = {Path(path).as_posix() for path in changed}
    if paths & FULL_SCOPE_TRIGGERS:
        return None
    modules = sorted(path for path in paths if scoped(path) and (ROOT / path).is_file())
    return [path.removesuffix(".py").replace("/", ".") + ".*" for path in modules]


def check(baseline: Baseline, scores: dict[str, float], changed: list[str]) -> list[str]:
    problems: list[str] = []
    required = baseline.modules.keys() | {
        str(Path(path)) for path in changed if scoped(str(Path(path)))
    }
    for module in sorted(required):
        score = scores.get(module)
        if score is None:
            problems.append(f"{module}: missing measured results; run scoped mutmut first")
            continue
        floor = baseline.modules.get(module, 0.0)
        if module in {str(Path(path)) for path in changed}:
            floor = max(floor, baseline.pr_break)
        if score < floor:
            problems.append(f"{module}: {score:.2f}% below required {floor:.2f}%")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=ROOT / "mutants")
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--changed", nargs="*", default=[], metavar="PATH")
    parser.add_argument("--write", action="store_true", help="raise measured baselines only")
    parser.add_argument(
        "--select",
        action="store_true",
        help="print the mutmut patterns for --changed ('*' for the full scope) and exit",
    )
    args = parser.parse_args(argv)
    if args.select:
        selected = patterns(args.changed)
        print("*" if selected is None else " ".join(selected))
        return 0
    try:
        baseline = Baseline.load(args.baseline)
        results = read_results(args.results)
        scores = {
            module: result.score for module, result in results.items() if result.score is not None
        }
        if not scores:
            print("no measured scoped mutants; run scoped mutmut first", file=sys.stderr)
            return 1
        if args.write:
            baseline.write(args.baseline, scores)
        problems = check(baseline, scores, args.changed)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"mutation ratchet: {exc}", file=sys.stderr)
        return 1
    for module, score in scores.items():
        result = results[module]
        print(
            f"{module}: {score:.2f}% (killed={result.killed}, survived={result.survived}, "
            f"timeout={result.timeout}, suspicious={result.suspicious}, excluded={result.excluded}); "
            f"weekly target {baseline.weekly_target:g}%"
        )
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print(f"mutation ratchet ok: {len(scores)} measured modules")
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
