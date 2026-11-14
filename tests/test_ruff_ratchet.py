"""The ruff legacy ratchet only tightens (PVA-M2.1)."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from scripts import ruff_ratchet

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ratchet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    legacy = tmp_path / "ruff-legacy.toml"
    counts = tmp_path / "ruff.json"
    legacy.write_text(
        '[lint.per-file-ignores]\n"../app/a.py" = ["D101", "TC003"]\n"../app/b.py" = ["TC003"]\n',
        encoding="utf-8",
    )
    by_file = {"app/a.py": {"D101": 2, "TC003": 1}, "app/b.py": {"TC003": 1}}
    counts.write_text(json.dumps({"by_file": by_file}), encoding="utf-8")
    monkeypatch.setattr(ruff_ratchet, "LEGACY", legacy)
    monkeypatch.setattr(ruff_ratchet, "COUNTS", counts)
    return tmp_path


CURRENT = [("app/a.py", "D101"), ("app/a.py", "D101"), ("app/a.py", "TC003"), ("app/b.py", "TC003")]


def test_unchanged_findings_pass(ratchet: Path) -> None:
    assert ruff_ratchet.check(CURRENT) == []


def test_new_code_in_a_legacy_file_fails(ratchet: Path) -> None:
    problems = ruff_ratchet.check([*CURRENT, ("app/b.py", "D101")])
    assert any("app/b.py: new D101" in p for p in problems)
    assert any("app/b.py: 1 D101 findings, ratchet allows 0" in p for p in problems)


def test_growth_inside_a_legacy_entry_fails(ratchet: Path) -> None:
    problems = ruff_ratchet.check([*CURRENT, ("app/a.py", "TC003")])
    assert problems == ["app/a.py: 2 TC003 findings, ratchet allows 1"]


def test_new_file_fails(ratchet: Path) -> None:
    problems = ruff_ratchet.check([*CURRENT, ("app/new.py", "ANN401")])
    assert any("app/new.py: new ANN401" in p for p in problems)


def test_fixed_entry_must_be_removed(ratchet: Path) -> None:
    problems = ruff_ratchet.check(CURRENT[:3])
    assert any("app/b.py: TC003 no longer occurs" in p for p in problems)
    assert any("app/b.py: 0 TC003 findings, below the ratchet (1)" in p for p in problems)


def test_write_shrinks_but_never_grows(ratchet: Path) -> None:
    ruff_ratchet.write(CURRENT[:3])
    assert ruff_ratchet.load_legacy() == {"app/a.py": {"D101", "TC003"}}
    assert ruff_ratchet.load_counts() == {("app/a.py", "D101"): 2, ("app/a.py", "TC003"): 1}
    with pytest.raises(SystemExit, match="refusing to grow"):
        ruff_ratchet.write([*CURRENT[:3], ("app/b.py", "TC003")])
    with pytest.raises(SystemExit, match="refusing to grow"):
        ruff_ratchet.write([*CURRENT[:3], ("app/a.py", "D101")])


def test_committed_ratchet_is_consistent() -> None:
    legacy = tomllib.loads((ROOT / "ratchets" / "ruff-legacy.toml").read_text(encoding="utf-8"))
    entries = legacy["lint"]["per-file-ignores"]
    assert all(path.startswith("../") for path in entries)
    counts = json.loads((ROOT / "ratchets" / "ruff.json").read_text(encoding="utf-8"))
    by_file = counts["by_file"]
    assert {f"../{path}": sorted(codes) for path, codes in by_file.items()} == entries
    per_code: dict[str, int] = {}
    for codes in by_file.values():
        for code, n in codes.items():
            per_code[code] = per_code.get(code, 0) + n
    assert per_code == counts["findings"]
    assert counts["total"] == sum(per_code.values())


def test_real_findings_match_the_committed_ratchet() -> None:
    """Runs ruff for real: the override drops only the legacy base, not the S2-S4 ignores."""
    current = ruff_ratchet.findings()
    assert current, "the legacy base should still hide findings until PVA-M4.11"
    assert all(not path.startswith(("/", "..")) for path, _ in current)
    assert not any(path.startswith("tests/") and code == "S101" for path, code in current)
    assert ruff_ratchet.check(current) == []


def test_write_fails_closed_without_committed_counts(ratchet: Path) -> None:
    (ratchet / "ruff.json").unlink()
    with pytest.raises(SystemExit, match="refusing to create a new baseline"):
        ruff_ratchet.write([*CURRENT, ("app/new.py", "ANN401")])
    ruff_ratchet.write(CURRENT, init=True)
    assert ruff_ratchet.check(CURRENT) == []
