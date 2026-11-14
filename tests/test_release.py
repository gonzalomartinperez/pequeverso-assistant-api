"""Release automation (PVA-M1.10, ADR-0018): version, CHANGELOG sections and release.yml shape."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from scripts import release_notes

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_changelog_keeps_an_unreleased_section_in_keep_a_changelog_form() -> None:
    assert re.search(r"^## \[Unreleased\]$", CHANGELOG, re.MULTILINE)
    headings = re.findall(r"^### (\w+)$", CHANGELOG.split("## [Unreleased]", 1)[1], re.MULTILINE)
    allowed = {"Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"}
    assert set(headings) <= allowed


def test_current_version_has_a_section_or_predates_the_flow() -> None:
    version = release_notes.version()
    if version == "1.0.0":  # tagged before this flow; the next release PR adds `## [X.Y.Z] - date`
        assert release_notes.section(CHANGELOG, version) is None
        assert re.search(r"^## 1\.0\.0 ", CHANGELOG, re.MULTILINE)
    else:
        assert release_notes.section(CHANGELOG, version)


def test_section_extraction_and_empty_section_failure() -> None:
    text = "# Changelog\n\n## [Unreleased]\n\n## [1.1.0] - 2026-12-20\n\n### Added\n\n- x\n\n## 1.0.0 old\n"
    assert release_notes.section(text, "1.1.0") == "### Added\n\n- x\n"
    assert release_notes.section(text, "1.2.0") is None
    with pytest.raises(SystemExit):
        release_notes.section("## [1.1.0] - 2026-12-20\n\n## [1.0.0] - 2026-10-17\n", "1.1.0")


def test_main_writes_outputs(tmp_path: Path) -> None:
    out, notes = tmp_path / "out", tmp_path / "notes.md"
    assert release_notes.main(["--github-output", str(out), "--notes", str(notes)]) == 0
    assert f"version={release_notes.version()}\n" in out.read_text(encoding="utf-8")


def test_release_workflow_is_main_only_least_privilege_and_pinned() -> None:
    text = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    events = workflow.get("on", workflow.get(True))
    assert events == {"push": {"branches": ["main"]}}
    assert workflow["permissions"] == {}
    (job,) = workflow["jobs"].values()
    assert job["permissions"] == {"contents": "write"}
    assert "secrets." not in text
    for step in job["steps"]:
        if "uses" in step:
            assert re.fullmatch(r"[\w./-]+@[a-f0-9]{40}", step["uses"]), step["uses"]
    assert "persist-credentials: false" in text
    assert "python3 -m scripts.release_notes" in text
