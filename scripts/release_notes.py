"""Read the release version and its CHANGELOG section (PVA-M1.10, ADR-0018).

The version is `[project].version` in pyproject.toml (the single source); the notes are the
`## [X.Y.Z] - YYYY-MM-DD` section of CHANGELOG.md. Run by the CI runner's system python3, so the
syntax stays 3.12-compatible and only the standard library is used.

    python3 -m scripts.release_notes --github-output "$GITHUB_OUTPUT" --notes notes.md
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"\d+\.\d+\.\d+")


def version(root: Path = ROOT) -> str:
    """Return the project version, failing when it is not X.Y.Z."""
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    value = str(data["project"]["version"])
    if not VERSION.fullmatch(value):
        raise SystemExit(f"version {value!r} is not X.Y.Z")
    return value


def section(changelog: str, number: str) -> str | None:
    """Return the body of `## [number] - date`, None when absent; an empty section fails."""
    pattern = rf"^## \[{re.escape(number)}\] - \d{{4}}-\d{{2}}-\d{{2}}[^\n]*\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, changelog, re.MULTILINE | re.DOTALL)
    if match is None:
        return None
    body = match.group(1).strip()
    if not body:
        raise SystemExit(f"CHANGELOG section [{number}] is empty")
    return body + "\n"


def main(argv: list[str] | None = None) -> int:
    """Write `version` and `has_section` outputs and the notes file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-output", type=Path, required=True)
    parser.add_argument("--notes", type=Path, required=True)
    args = parser.parse_args(argv)
    number = version()
    body = section((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), number)
    with args.github_output.open("a", encoding="utf-8") as out:
        out.write(f"version={number}\nhas_section={'true' if body else 'false'}\n")
    if body:
        args.notes.write_text(body, encoding="utf-8")
    sys.stdout.write(f"version {number}, section {'found' if body else 'absent'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
