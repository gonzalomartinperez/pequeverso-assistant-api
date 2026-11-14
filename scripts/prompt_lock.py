"""Prompt lock (ADR-0017): pins of every `PROMPT_VERSION`, append-only.

`python -m scripts.prompt_lock` checks the lock; `--append` records the current version after a
prompt change. It refuses to overwrite an existing version or to reuse a version number.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.ai.prompt import PROMPT_VERSION, prompt_fingerprint

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "app" / "ai" / "prompt.lock.json"
CHANGELOG = ROOT / "docs" / "reference" / "prompt-changelog.md"
VERSION = re.compile(r"\d{4}-\d{2}-\d{2}\.\d+")


def _key(version: str) -> tuple[str, int]:
    date, n = version.rsplit(".", 1)
    return date, int(n)


def load(path: Path = LOCK) -> dict[str, Any]:
    """Read the lock file."""
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def problems(
    lock: dict[str, Any], version: str, fingerprint: dict[str, str], changelog: str
) -> list[str]:
    """Return every way the current prompt disagrees with the lock and the changelog."""
    found: list[str] = []
    entries = lock["versions"]
    versions = [entry["version"] for entry in entries]
    if not VERSION.fullmatch(version):
        found.append(f"PROMPT_VERSION {version!r} is not YYYY-MM-DD.N")
    if any(not VERSION.fullmatch(v) for v in versions):
        found.append("lock holds a malformed version")
    elif [_key(v) for v in versions] != sorted({_key(v) for v in versions}):
        found.append("lock versions must be unique and in increasing order (append-only)")
    hashes = [entry["prompt_sha256"] for entry in entries]
    if len(hashes) != len(set(hashes)):
        found.append("two lock versions share the same prompt_sha256")
    if not entries or entries[-1]["version"] != version:
        found.append(
            f"PROMPT_VERSION {version} is not the last lock entry; after a prompt change bump "
            "the version and run `uv run python -m scripts.prompt_lock --append`"
        )
    elif {k: entries[-1][k] for k in fingerprint} != fingerprint:
        found.append(
            f"the instructions or output schema changed but PROMPT_VERSION is still {version}; "
            "bump it, run `uv run python -m scripts.prompt_lock --append` and add a changelog row"
        )
    for entry in entries:
        row = f"| {entry['version']} | `{entry['prompt_sha256'][:12]}` |"
        if row not in changelog:
            found.append(f"docs/reference/prompt-changelog.md has no row starting {row!r}")
    return found


def against_base(lock: dict[str, Any], base: dict[str, Any]) -> list[str]:
    """Every version locked at the base revision must stay, unchanged and in the same order."""
    before = base["versions"]
    if lock["versions"][: len(before)] != before:
        return [
            "app/ai/prompt.lock.json: a version locked at the base revision was edited or removed"
        ]
    return []


def _base_lock(ref: str) -> dict[str, Any] | None:
    shown = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{ref}:app/ai/prompt.lock.json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if shown.returncode != 0:
        return None  # the base predates the lock
    data: dict[str, Any] = json.loads(shown.stdout)
    return data


def append(lock: dict[str, Any], version: str, fingerprint: dict[str, str]) -> dict[str, Any]:
    """Return the lock with the current version appended; refuse reuse of a version."""
    if any(entry["version"] == version for entry in lock["versions"]):
        raise SystemExit(f"{version} is already locked; versions are never edited, bump it")
    return {**lock, "versions": [*lock["versions"], {"version": version, **fingerprint}]}


def main(argv: list[str] | None = None) -> int:
    """Check the prompt lock or append the current version."""
    parser = argparse.ArgumentParser(description="Prompt lock: pins per PROMPT_VERSION.")
    parser.add_argument("--append", action="store_true", help="record the current version")
    parser.add_argument("--base", metavar="REF", help="also check append-only against this git ref")
    args = parser.parse_args(argv)
    lock, fingerprint = load(), prompt_fingerprint()
    if args.append:
        LOCK.write_text(json.dumps(append(lock, PROMPT_VERSION, fingerprint), indent=2) + "\n")
        print(
            f"locked {PROMPT_VERSION}: add the changelog row for {fingerprint['prompt_sha256'][:12]}"
        )
        return 0
    found = problems(lock, PROMPT_VERSION, fingerprint, CHANGELOG.read_text(encoding="utf-8"))
    if args.base and (base := _base_lock(args.base)) is not None:
        found += against_base(lock, base)
    for problem in found:
        print(problem, file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
