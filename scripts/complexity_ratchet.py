"""Keep the C901 baseline moving only toward complexity ten (PVA-M2.2)."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COUNTS = ROOT / "ratchets" / "complexity.json"
MAX_COMPLEXITY = 10
MESSAGE = re.compile(r"`(.+)` is too complex \((\d+) > 10\)")


def function_keys(source: str) -> dict[int, str]:
    """Resolve definition lines to stable fully qualified names (lexical scope)."""
    definitions: list[tuple[int, str, str]] = []

    def visit(node: ast.AST, scope: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qualified = (*scope, child.name)
                if not isinstance(child, ast.ClassDef):
                    definitions.append((child.lineno, child.name, ".".join(qualified)))
                visit(child, qualified)
            else:
                visit(child, scope)

    visit(ast.parse(source), ())
    # Always the full lexical name (`Class.method`, `outer.inner`), so adding an unrelated
    # same-named function never renames a baselined key. Same-scope duplicates (property
    # setters, overloads) get an occurrence suffix in source order.
    seen: Counter[str] = Counter()
    keys: dict[int, str] = {}
    for line, _, qualified in sorted(definitions):
        seen[qualified] += 1
        keys[line] = qualified if seen[qualified] == 1 else f"{qualified}#{seen[qualified]}"
    return keys


def findings() -> dict[str, int]:
    """Run Ruff offline; reject unexpected diagnostics rather than dropping findings."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "app",
            "contracts",
            "--select",
            "C901",
            "--config",
            "lint.mccabe.max-complexity = 10",
            "--output-format",
            "json",
            "--exit-zero",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    current: dict[str, int] = {}
    keys_by_file: dict[Path, dict[int, str]] = {}
    for item in json.loads(result.stdout):
        match = MESSAGE.fullmatch(item["message"])
        if item["code"] != "C901" or match is None:
            raise ValueError("unexpected Ruff complexity diagnostic")
        path = Path(item["filename"]).resolve()
        if path not in keys_by_file:
            keys_by_file[path] = function_keys(path.read_text(encoding="utf-8"))
        name = keys_by_file[path][item["location"]["row"]]
        key = f"{path.relative_to(ROOT).as_posix()}::{name}"
        if key in current:
            raise ValueError(f"duplicate complexity identity: {key}")
        current[key] = int(match[2])
    return current


def load_counts() -> dict[str, int]:
    data = json.loads(COUNTS.read_text(encoding="utf-8"))
    if data["schema_version"] != 1 or data["max_complexity"] != MAX_COMPLEXITY:
        raise ValueError("unsupported complexity ratchet schema or threshold")
    functions = data["functions"]
    if not isinstance(functions, dict) or any(
        not isinstance(key, str) or type(value) is not int or value <= MAX_COMPLEXITY
        for key, value in functions.items()
    ):
        raise ValueError("invalid complexity baseline")
    return {str(key): int(value) for key, value in functions.items()}


def check(current: dict[str, int]) -> list[str]:
    allowed = load_counts()
    problems: list[str] = []
    for key in sorted(current.keys() | allowed.keys()):
        found, limit = current.get(key, 0), allowed.get(key, 0)
        if found > limit:
            problems.append(f"{key}: complexity {found} > {limit}; new or increased complexity")
        elif found < limit:
            problems.append(f"{key}: complexity {found} < {limit}; run --write to tighten")
    return problems


def write(current: dict[str, int], *, init: bool = False) -> None:
    if not init:
        if not COUNTS.exists():
            raise SystemExit(
                f"{COUNTS} is missing; refusing to create a new baseline without --init"
            )
        allowed = load_counts()
        if any(value > allowed.get(key, 0) for key, value in current.items()):
            raise SystemExit("refusing to grow the complexity ratchet")
    COUNTS.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "max_complexity": MAX_COMPLEXITY,
                "functions": dict(sorted(current.items())),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _commit_exists(ref: str) -> bool:
    probe = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-e", f"{ref}^{{commit}}"],
        capture_output=True,
        check=False,
    )
    return probe.returncode == 0


def against_base(ref: str) -> list[str]:
    """Refuse a committed baseline that adds a function or raises a value against `ref`."""
    shown = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{ref}:ratchets/complexity.json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if shown.returncode != 0:
        if not _commit_exists(ref):
            return [f"base revision {ref!r} is not available; refusing to skip the base check"]
        return []  # the base predates the ratchet
    before: dict[str, int] = json.loads(shown.stdout)["functions"]
    return [
        f"{key}: complexity ratchet raised from {before.get(key, 0)} to {value} against the base"
        for key, value in sorted(load_counts().items())
        if value > before.get(key, 0)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--base", metavar="REF", help="also refuse growth against this git ref")
    args = parser.parse_args(argv)
    if args.init and not args.write:
        parser.error("--init requires --write")
    current = findings()
    if args.write:
        write(current, init=args.init)
        print(f"complexity ratchet written: {len(current)} functions")
        return 0
    problems = check(current) + (against_base(args.base) if args.base else [])
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print(
            f"complexity ratchet ok: {len(current)} functions, max {max(current.values(), default=0)}"
        )
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
