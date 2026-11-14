"""The complexity baseline only tightens and function identities survive line shifts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import complexity_ratchet

CURRENT = {"app/a.py::run": 12, "app/b.py::start": 15}


@pytest.fixture
def ratchet(tmp_path, monkeypatch):
    path = tmp_path / "complexity.json"
    monkeypatch.setattr(complexity_ratchet, "COUNTS", path)
    complexity_ratchet.write(CURRENT, init=True)
    return path


def test_unchanged_findings_pass(ratchet):
    assert complexity_ratchet.check(CURRENT) == []


@pytest.mark.parametrize(
    "current", [dict(CURRENT, **{"app/new.py::run": 11}), {**CURRENT, "app/a.py::run": 13}]
)
def test_new_or_increased_complexity_fails(ratchet, current):
    assert any("new or increased" in p for p in complexity_ratchet.check(current))
    with pytest.raises(SystemExit, match="refusing to grow"):
        complexity_ratchet.write(current)
    assert complexity_ratchet.load_counts() == CURRENT


@pytest.mark.parametrize("current", [{"app/a.py::run": 12}, {**CURRENT, "app/a.py::run": 11}, {}])
def test_reductions_require_write_and_only_tighten(ratchet, current):
    assert any("run --write" in p for p in complexity_ratchet.check(current))
    complexity_ratchet.write(current)
    assert complexity_ratchet.load_counts() == current
    assert complexity_ratchet.check(current) == []
    with pytest.raises(SystemExit, match="refusing to grow"):
        complexity_ratchet.write(CURRENT)


def test_missing_baseline_fails_closed(ratchet):
    ratchet.unlink()
    with pytest.raises(FileNotFoundError):
        complexity_ratchet.check(CURRENT)
    with pytest.raises(SystemExit, match="without --init"):
        complexity_ratchet.write(CURRENT)
    complexity_ratchet.write(CURRENT, init=True)
    assert complexity_ratchet.check(CURRENT) == []


def test_duplicate_methods_have_distinct_line_independent_keys():
    source = "class A:\n    def run(self): pass\nclass B:\n    async def run(self): pass\n"
    keys = complexity_ratchet.function_keys(source)
    assert set(keys.values()) == {"A.run", "B.run"}
    shifted = complexity_ratchet.function_keys("\n\n" + source)
    assert {line + 2: key for line, key in keys.items()} == shifted


def test_nested_names_do_not_collide():
    source = "def a():\n    def run(): pass\ndef b():\n    def run(): pass\n"
    assert set(complexity_ratchet.function_keys(source).values()) == {"a", "b", "a.run", "b.run"}


def test_same_scope_duplicates_get_an_occurrence_suffix():
    keys = complexity_ratchet.function_keys("def run(): pass\ndef run(): pass\n")
    assert keys == {1: "run", 2: "run#2"}


def test_adding_a_same_named_function_elsewhere_keeps_existing_keys():
    before = complexity_ratchet.function_keys("class A:\n    def start(self): pass\n")
    after = complexity_ratchet.function_keys(
        "class A:\n    def start(self): pass\nclass B:\n    def start(self): pass\n"
    )
    assert before[2] == after[2] == "A.start"


@pytest.mark.parametrize(
    ("field", "value"), [("schema_version", 2), ("max_complexity", 11), ("functions", {"x": 10})]
)
def test_invalid_baseline_is_rejected(ratchet, field, value):
    data = json.loads(ratchet.read_text())
    data[field] = value
    ratchet.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=r"unsupported|invalid"):
        complexity_ratchet.load_counts()


def test_real_findings_match_committed_baseline():
    current = complexity_ratchet.findings()
    assert current == complexity_ratchet.load_counts()
    assert all(not Path(key.split("::")[0]).is_absolute() for key in current)
    assert complexity_ratchet.check(current) == []


def test_init_requires_write():
    with pytest.raises(SystemExit, match="2"):
        complexity_ratchet.main(["--init"])


def test_raising_the_committed_baseline_fails_against_the_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    counts = tmp_path / "complexity.json"
    counts.write_text(
        json.dumps({"schema_version": 1, "max_complexity": 10, "functions": {"app/a.py::f": 12}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(complexity_ratchet, "COUNTS", counts)

    class Shown:
        returncode = 0
        stdout = json.dumps({"functions": {"app/a.py::f": 11}})

    monkeypatch.setattr(complexity_ratchet.subprocess, "run", lambda *a, **k: Shown())
    assert complexity_ratchet.against_base("BASE") == [
        "app/a.py::f: complexity ratchet raised from 11 to 12 against the base"
    ]
