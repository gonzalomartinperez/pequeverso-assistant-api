"""Keep repository Markdown links pointed at existing local files."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "node_modules"}
LINK = re.compile(r"!?\[[^\]]*\]\((?:<([^>]+)>|([^\s)]+))(?:\s+[^)]*)?\)")
REFERENCE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(?:<([^>]+)>|(\S+))", re.MULTILINE)

OLD_PATHS = (
    "docs/knowledge-operations.md",
    "docs/dependency-updates.md",
    "docs/api-contract.md",
    "docs/catalog.md",
    "docs/deployment-contract.md",
    "docs/product-analytics.md",
    "docs/ci.md",
    "docs/evaluation.md",
    "docs/agent-skills.md",
    "docs/runtime-baseline.md",
    "docs/architecture.md",
    "docs/security.md",
    "docs/graph-retrieval.md",
    "docs/official-web-evidence.md",
    "docs/reference-adoption.md",
    "docs/business-questions.md",
    "docs/execution-plan.md",
    "docs/observability/README.md",
    "docs/handoffs",
    "docs/architecture",
)


def markdown_files() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*.md")
        if path.name != ".codex-task.md"
        if not (set(path.relative_to(ROOT).parts) & SKIP_DIRS)
        and not path.relative_to(ROOT).as_posix().startswith("docs/verification/")
    ]


def targets(content: str) -> list[str]:
    found = [match.group(1) or match.group(2) for match in LINK.finditer(content)]
    found.extend(match.group(1) or match.group(2) for match in REFERENCE.finditer(content))
    return found


def test_relative_markdown_targets_exist() -> None:
    missing: list[str] = []
    for markdown in markdown_files():
        content = markdown.read_text(encoding="utf-8")
        for target in targets(content):
            parsed = urlsplit(target)
            if parsed.scheme in {"http", "https", "mailto"} or target.startswith("#"):
                continue
            path = unquote(parsed.path)
            if not path:
                continue
            destination = (
                (ROOT / path.lstrip("/")) if path.startswith("/") else (markdown.parent / path)
            )
            destination = destination.resolve()
            if not destination.exists():
                missing.append(f"{markdown.relative_to(ROOT)} -> {target}")
    assert not missing, "Broken relative Markdown targets:\n" + "\n".join(missing)


def test_old_top_level_document_paths_are_gone() -> None:
    remaining = [path for path in OLD_PATHS if (ROOT / path).exists()]
    assert not remaining, f"Old documentation paths still exist: {remaining}"
