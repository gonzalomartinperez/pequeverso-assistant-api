"""Coverage gate (PVA-M2.3): branch-coverage floor and diff coverage on changed lines.

Reads a coverage.py JSON report (`coverage json`, branch mode) and checks:

- whole-repository branch coverage against `ratchets/coverage.json` (`branch_floor`), which only rises;
- diff coverage: of the executable lines added or changed against `--base`, at least `diff_floor`
  percent were executed (`testing.md` section 1: 90%).

Changed lines come from `git diff --unified=0 <base> HEAD` restricted to measured files, so the gate
needs nothing beyond coverage.py (no diff-cover dependency tree to review against the licence
allow-list).

    python -m scripts.coverage_gate coverage.json --base FETCH_HEAD
    python -m scripts.coverage_gate coverage.json --write-floor   # raise the floor (never lowers)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RATCHET = ROOT / "ratchets" / "coverage.json"
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def load_ratchet(path: Path = RATCHET) -> dict[str, Any]:
    """Read the committed floors."""
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def branch_percent(report: dict[str, Any]) -> float:
    """Return whole-report branch coverage (covered branches / branches) in percent."""
    totals = report["totals"]
    branches = int(totals.get("num_branches", 0))
    if branches == 0:
        return 100.0
    return 100.0 * int(totals["covered_branches"]) / branches


def changed_lines(diff: str) -> dict[str, set[int]]:
    """Map each file in a `--unified=0` diff to its added or changed line numbers (new side)."""
    result: dict[str, set[int]] = {}
    current: str | None = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            target = line[4:].strip()
            current = None if target == "/dev/null" else target.removeprefix("b/")
            continue
        match = HUNK.match(line)
        if match and current is not None:
            start, count = int(match[1]), int(match[2] if match[2] is not None else 1)
            result.setdefault(current, set()).update(range(start, start + count))
    return result


def diff_coverage(
    report: dict[str, Any], changed: dict[str, set[int]]
) -> tuple[int, int, dict[str, list[int]]]:
    """Return (executed, executable, missed lines per file) for the changed lines."""
    executed = executable = 0
    missed: dict[str, list[int]] = {}
    for name, data in report["files"].items():
        lines = changed.get(Path(name).as_posix())
        if not lines:
            continue
        measured = set(data["executed_lines"]) | set(data["missing_lines"])
        hit = lines & set(data["executed_lines"])
        miss = (lines & measured) - hit
        executed += len(hit)
        executable += len(hit) + len(miss)
        if miss:
            missed[Path(name).as_posix()] = sorted(miss)
    return executed, executable, missed


def _git_diff(base: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "--unified=0", "--no-color", base, "HEAD", "--", "*.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"cannot diff against {base!r}: {result.stderr.strip()}")
    return result.stdout


def check(
    report: dict[str, Any],
    ratchet: dict[str, Any],
    changed: dict[str, set[int]] | None,
    floor_key: str = "branch_floor",
) -> list[str]:
    """Return gate failures for the report."""
    problems: list[str] = []
    branch = branch_percent(report)
    if branch + 1e-9 < float(ratchet[floor_key]):
        problems.append(f"branch coverage {branch:.2f}% is below {floor_key} {ratchet[floor_key]}%")
    if changed is not None:
        hit, total, missed = diff_coverage(report, changed)
        if total and 100.0 * hit / total + 1e-9 < float(ratchet["diff_floor"]):
            detail = "; ".join(f"{name}: {lines[:12]}" for name, lines in sorted(missed.items()))
            problems.append(
                f"diff coverage {100.0 * hit / total:.1f}% ({hit}/{total} changed lines) is below "
                f"{ratchet['diff_floor']}%; untested: {detail}"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    """Run the gate, or raise the floor to the measured value."""
    parser = argparse.ArgumentParser(description="Branch-coverage floor and diff-coverage gate.")
    parser.add_argument("report", type=Path, help="coverage.py JSON report")
    parser.add_argument("--base", help="git revision the change is compared with")
    parser.add_argument(
        "--floor", default="branch_floor", choices=["branch_floor", "static_branch_floor"]
    )
    parser.add_argument("--write-floor", action="store_true", help="raise the floor, never lower")
    args = parser.parse_args(argv)
    report = json.loads(args.report.read_text(encoding="utf-8"))
    ratchet = load_ratchet()
    branch = branch_percent(report)
    if args.write_floor:
        floor = max(float(ratchet[args.floor]), int(branch * 100) / 100)
        updated = {**ratchet, args.floor: floor}
        RATCHET.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")
        sys.stdout.write(f"{args.floor} {floor}%\n")
        return 0
    changed = changed_lines(_git_diff(args.base)) if args.base else None
    problems = check(report, ratchet, changed, args.floor)
    for problem in problems:
        sys.stderr.write(problem + "\n")
    hit, total, _ = diff_coverage(report, changed or {})
    diff_text = f", diff {hit}/{total} changed lines" if changed is not None else ""
    sys.stdout.write(
        f"branch coverage {branch:.2f}% ({args.floor} {ratchet[args.floor]}%){diff_text}\n"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
