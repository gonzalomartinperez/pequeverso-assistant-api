#!/usr/bin/env python3
"""guard-files: PreToolUse hook for file tools (Read, Edit, Write, MultiEdit, NotebookEdit, Grep,
Glob) and Codex `apply_patch`.

Blocks reading or writing `.env*` files (except `*.example`, `*.sample`, `*.template`, `*.dist`)
and private keys, and blocks hand edits of lockfiles (they change only through the package
manager). For `apply_patch` the paths come from the `*** Add/Update/Delete File:` and
`*** Move to:` lines of the patch. Exit 2 with a reason on stderr blocks the call. Fails closed on
an internal error. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ENV = re.compile(r"(^|/)\.env(\.[^/]*)?$")
SAFE_ENV_SUFFIX = re.compile(r"\.(example|sample|template|dist)(\.|$)")
PRIVATE_KEY = re.compile(r"(^|/)(id_(rsa|dsa|ecdsa|ed25519)|[^/]*\.(key|p12|pfx)|[^/]*(privkey|private[-_]key)[^/]*\.pem)$")
LOCKFILES = {"package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock", "uv.lock", "poetry.lock",
             "bun.lock", "bun.lockb"}
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch"}
PATCH_PATH = re.compile(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+?)\s*$", re.M)


def patch_text(tool_input: dict) -> str:
    for key in ("patch", "input", "command"):
        value = tool_input.get(key)
        if isinstance(value, list):
            value = value[-1] if value else ""
        if isinstance(value, str) and "*** " in value:
            return value
    return ""


def paths_of(event: dict) -> list[str]:
    tool_input = event.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return []
    keys = ["file_path", "path", "notebook_path", "glob"] + (["pattern"] if event.get("tool_name") == "Glob" else [])
    found = [str(tool_input[k]) for k in keys if tool_input.get(k)]
    if event.get("tool_name") == "apply_patch" or "*** Begin Patch" in patch_text(tool_input):
        found += PATCH_PATH.findall(patch_text(tool_input))
    return found


def private_pem(path: str) -> bool:
    if not path.endswith(".pem"):
        return False
    try:
        with open(path, "rb") as fh:
            return b"PRIVATE KEY-----" in fh.read(4096)
    except OSError:
        return False


def reason_for(tool: str, path: str) -> str | None:
    posix = pathlib.PurePath(path).as_posix()
    name = posix.rsplit("/", 1)[-1]
    env_glob = (re.search(r"(^|/)\.e[^/]*[*?\[]", posix) or re.search(r"(^|/)[*?]+env", posix)
                or re.search(r"(^|/)\.[*?\[]", posix) or re.search(r"[*?]\.env($|[.*])", posix))
    if (ENV.search(posix) and not SAFE_ENV_SUFFIX.search(name)) or env_glob or PRIVATE_KEY.search(posix) or private_pem(path):
        return f"{posix} may hold secrets; it never enters the context (use .env.example)"
    if tool in WRITE_TOOLS and name in LOCKFILES:
        return f"{posix} changes only through the package manager (npm install, uv lock), never by hand"
    return None


def main() -> int:
    try:
        event = json.loads(sys.stdin.read())
    except ValueError:
        return 0
    try:
        if not isinstance(event, dict):
            return 0
        tool = str(event.get("tool_name", ""))
        if "*** Begin Patch" in patch_text(event.get("tool_input") or {}) and tool not in WRITE_TOOLS:
            tool = "apply_patch"
        for path in paths_of(event):
            why = reason_for(tool, path)
            if why:
                print(f"BLOCKED by guard-files: {why}. Do not work around this; ask the owner.", file=sys.stderr)
                return 2
    except Exception as exc:  # noqa: BLE001 - fail closed
        print(f"BLOCKED by guard-files: internal error ({exc.__class__.__name__}); failing closed.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
