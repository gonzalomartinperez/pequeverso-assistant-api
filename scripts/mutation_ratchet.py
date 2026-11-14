"""Check scoped mutmut 3.8 JSON metadata; never run mutation tests from this CLI.

Scores are raw killed / (killed + survived + timeout + suspicious) percentages.
Equivalent-mutant annotations are review evidence and do not inflate the scores.
Unchecked mutants (never run, or interrupted) are not scored: a required module with any
unchecked mutant is an incomplete run and fails.

Modes: ``pr`` checks only changed scoped modules (floor: max(pr_break, recorded score));
``full`` checks every scoped module that has mutants (floor: recorded score).
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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
# mutmut.stats.status_by_exit_code in 3.8.1. Exit 33 (no tests) counts as survived: an
# unexercised mutant is not killed. Skipped (34), no tests (5) and type-check (37) are excluded
# but reported. None and 2 (interrupted) are unchecked. Unexpected exits are suspicious.
IGNORED_CODES = {5, 34, 37}
UNCHECKED_CODES = {None, 2}
SURVIVED_CODES = {0, 33}
TIMEOUT_CODES = {36, -24, 24, 152, 255}
Mode = Literal["pr", "full"]


def scoped(path: str) -> bool:
    return path in SCOPED_FILES or (path.startswith("app/domain/") and path.endswith(".py"))


def has_functions(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except OSError, SyntaxError:
        return False
    return any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree))


def eligible_modules() -> list[str]:
    """Sorted scoped files mutmut can mutate: not __init__.py, at least one function."""
    candidates = set(SCOPED_FILES)
    candidates.update(p.relative_to(ROOT).as_posix() for p in (ROOT / "app/domain").glob("*.py"))
    return sorted(
        path
        for path in candidates
        if Path(path).name != "__init__.py" and has_functions(ROOT / path)
    )


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
    unchecked: int = 0

    def add(self, code: object) -> None:
        if code is not None and type(code) is not int:
            raise ValueError("mutmut exit code must be an integer or null")
        if code in UNCHECKED_CODES:
            self.unchecked += 1
        elif code in IGNORED_CODES:
            self.excluded += 1
        elif code in {1, 3}:
            self.killed += 1
        elif code in SURVIVED_CODES:
            self.survived += 1
        elif code in TIMEOUT_CODES:
            self.timeout += 1
        else:
            self.suspicious += 1

    @property
    def keys(self) -> int:
        return (
            self.killed
            + self.survived
            + self.timeout
            + self.suspicious
            + self.excluded
            + self.unchecked
        )

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
        result = Results()
        for code in mapping(data["exit_code_by_key"]).values():
            result.add(code)
        results[module] = result
    return results


# A change to these files re-measures the whole scope (the run that records the baseline).
FULL_SCOPE_TRIGGERS = frozenset({".github/workflows/mutation.yml", "scripts/mutation_ratchet.py"})


def pattern(module: str) -> str:
    return module.removesuffix(".py").replace("/", ".") + ".*"


def normalize(path: str) -> str:
    return Path(path).as_posix()


def patterns(changed: list[str]) -> list[str] | None:
    """Return mutmut name patterns for changed scoped modules; None means the full scope."""
    paths = {normalize(path) for path in changed}
    if paths & FULL_SCOPE_TRIGGERS:
        return None
    return [pattern(module) for module in eligible_modules() if module in paths]


def weight(module: str) -> int:
    """Approximate mutation sites: AST nodes inside function bodies (operators, constants, calls)."""
    tree = ast.parse((ROOT / module).read_text(encoding="utf-8"))
    functions = [
        n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    return sum(1 for function in functions for _ in ast.walk(function))


def shard_modules(index: int, count: int) -> list[str]:
    """Greedy balance by `weight` (heaviest first onto the lightest shard); ``index`` is 1-based.

    Deterministic: ties break on path and on the lowest shard index.
    """
    if not 1 <= index <= count:
        raise ValueError("shard index must be between 1 and the shard count")
    loads = [0] * count
    shards: list[list[str]] = [[] for _ in range(count)]
    for module in sorted(eligible_modules(), key=lambda m: (-weight(m), m)):
        target = loads.index(min(loads))
        shards[target].append(module)
        loads[target] += weight(module)
    return sorted(shards[index - 1])


def parse_shard(value: str) -> tuple[int, int]:
    try:
        left, right = value.split("/")
        index, count = int(left), int(right)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected I/N, for example 1/4") from exc
    if not 1 <= index <= count:
        raise argparse.ArgumentTypeError("shard index must be between 1 and N")
    return index, count


def read_changed_file(path: Path) -> list[str]:
    """Paths separated by NUL (git diff -z) or newlines; empties are dropped."""
    text = path.read_bytes().decode("utf-8", errors="surrogateescape")
    return [item.strip() for item in text.replace("\0", "\n").splitlines() if item.strip()]


def prune_meta(directory: Path, keep: list[str]) -> list[str]:
    """Delete ``*.py.meta`` of modules outside ``keep`` so shard artifacts never overlap."""
    removed: list[str] = []
    for path in sorted(directory.rglob("*.py.meta")):
        module = path.relative_to(directory).as_posix().removesuffix(".meta")
        if module not in keep:
            path.unlink()
            removed.append(module)
    return removed


def required_modules(
    results: dict[str, Results], changed: list[str], mode: Mode
) -> tuple[list[str], list[str]]:
    """Return (required modules with mutants, modules whose results are missing)."""
    keyed = {module for module, result in results.items() if result.keys > 0}
    if mode == "full":
        missing = [m for m in eligible_modules() if m not in results]
        return sorted(keyed), missing
    changed_scoped = {normalize(path) for path in changed} & set(eligible_modules())
    return sorted(changed_scoped & keyed), sorted(changed_scoped - results.keys())


def check(
    baseline: Baseline,
    results: dict[str, Results],
    changed: list[str],
    mode: Mode = "pr",
) -> list[str]:
    problems: list[str] = []
    required, missing = required_modules(results, changed, mode)
    problems.extend(f"{m}: missing measured results; run mutmut first" for m in missing)
    for module in required:
        result = results[module]
        if result.unchecked:
            problems.append(f"{module}: incomplete run, {result.unchecked} unchecked mutants")
            continue
        score = result.score
        if score is None:
            problems.append(f"{module}: no scored mutants; run mutmut first")
            continue
        floor = baseline.modules.get(module, 0.0)
        if mode == "pr":
            floor = max(floor, baseline.pr_break)
        if score < floor:
            problems.append(f"{module}: {score:.2f}% below required {floor:.2f}%")
    return problems


def report(baseline: Baseline, results: dict[str, Results], mode: Mode) -> None:
    for module, result in results.items():
        if result.keys == 0:
            continue
        score = "n/a" if result.score is None else f"{result.score:.2f}%"
        print(
            f"{module}: {score} (killed={result.killed}, survived={result.survived}, "
            f"timeout={result.timeout}, suspicious={result.suspicious}, "
            f"excluded={result.excluded}, unchecked={result.unchecked}); "
            f"weekly target {baseline.weekly_target:g}%"
        )
        below = result.score is not None and result.score < baseline.weekly_target
        if mode == "full" and below:
            print(f"::notice::{module} is below the weekly target {baseline.weekly_target:g}%")
    if mode == "full" and not baseline.modules:
        print("::notice::baseline not yet recorded; run --write from these results")


def select(args: argparse.Namespace, changed: list[str]) -> int:
    if args.shard:
        selected: list[str] | None = [pattern(m) for m in shard_modules(*args.shard)]
    else:
        selected = patterns(changed)
    print("*" if selected is None else " ".join(selected))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=ROOT / "mutants")
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--mode", choices=["pr", "full"], default="pr")
    parser.add_argument("--changed", nargs="*", default=[], metavar="PATH", help="local use")
    parser.add_argument(
        "--changed-file",
        type=Path,
        help="file of NUL- or newline-separated changed paths (never word-split)",
    )
    parser.add_argument("--write", action="store_true", help="raise measured baselines only")
    parser.add_argument(
        "--select",
        action="store_true",
        help="print the mutmut patterns for the changed paths ('*' for the full scope) and exit",
    )
    parser.add_argument(
        "--shard",
        type=parse_shard,
        metavar="I/N",
        help="with --select: the full-scope patterns of shard I of N; with --prune-meta: keep it",
    )
    parser.add_argument(
        "--prune-meta",
        action="store_true",
        help="delete the .meta files of modules outside --shard, then exit",
    )
    return parser


def unchecked_modules(results: dict[str, Results]) -> list[str]:
    return sorted(module for module, result in results.items() if result.unchecked)


def run(args: argparse.Namespace, changed: list[str]) -> int:
    baseline = Baseline.load(args.baseline)
    results = read_results(args.results)
    scores = {m: r.score for m, r in results.items() if r.score is not None}
    if not scores:
        print("no measured scoped mutants; run scoped mutmut first", file=sys.stderr)
        return 1
    if args.write:
        incomplete = unchecked_modules(results)
        if incomplete:
            print(
                f"refusing --write: unchecked mutants in {', '.join(incomplete)}", file=sys.stderr
            )
            return 1
        baseline.write(args.baseline, scores)
    problems = check(baseline, results, changed, args.mode)
    report(baseline, results, args.mode)
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print(f"mutation ratchet ok ({args.mode}): {len(scores)} measured modules")
    return int(bool(problems))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        changed = list(args.changed)
        if args.changed_file:
            changed += read_changed_file(args.changed_file)
        if args.select:
            return select(args, changed)
        if args.prune_meta:
            if not args.shard:
                print("--prune-meta requires --shard I/N", file=sys.stderr)
                return 1
            keep = shard_modules(*args.shard)
            print(f"pruned {len(prune_meta(args.results, keep))} meta files outside the shard")
            return 0
        return run(args, changed)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"mutation ratchet: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
