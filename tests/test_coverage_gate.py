"""Coverage gate (PVA-M2.3): branch floor and diff coverage."""

from __future__ import annotations

import json

from scripts import coverage_gate

DIFF = """\
diff --git a/app/x.py b/app/x.py
--- a/app/x.py
+++ b/app/x.py
@@ -10,0 +11,3 @@ def f():
+    a = 1
+    b = 2
+    return a + b
@@ -40 +43 @@ def g():
-    old()
+    new()
diff --git a/app/gone.py b/app/gone.py
--- a/app/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-x = 1
-y = 2
"""

REPORT = {
    "totals": {"num_branches": 200, "covered_branches": 160},
    "files": {
        "app/x.py": {"executed_lines": [11, 12, 43], "missing_lines": [13, 50]},
        "app/other.py": {"executed_lines": [1], "missing_lines": [2]},
    },
}
RATCHET = {"branch_floor": 76.0, "static_branch_floor": 70.0, "diff_floor": 90.0}


def test_changed_lines_reads_new_side_hunks_and_skips_deletions() -> None:
    assert coverage_gate.changed_lines(DIFF) == {"app/x.py": {11, 12, 13, 43}}


def test_diff_coverage_counts_only_executable_changed_lines() -> None:
    hit, total, missed = coverage_gate.diff_coverage(REPORT, {"app/x.py": {11, 12, 13, 43, 99}})
    assert (hit, total) == (3, 4)
    assert missed == {"app/x.py": [13]}


def test_branch_floor_and_diff_floor() -> None:
    assert coverage_gate.branch_percent(REPORT) == 80.0
    assert coverage_gate.check(REPORT, RATCHET, None) == []
    high = {**RATCHET, "branch_floor": 81.0}
    assert coverage_gate.check(REPORT, high, None) == [
        "branch coverage 80.00% is below branch_floor 81.0%"
    ]
    problems = coverage_gate.check(REPORT, RATCHET, {"app/x.py": {11, 12, 13, 43}})
    assert len(problems) == 1
    assert "diff coverage 75.0% (3/4 changed lines) is below 90.0%" in problems[0]
    assert coverage_gate.check(REPORT, RATCHET, {"app/x.py": {11, 12, 43}}) == []
    assert coverage_gate.check(REPORT, RATCHET, {}, "static_branch_floor") == []


def test_no_branches_counts_as_full_coverage() -> None:
    assert coverage_gate.branch_percent({"totals": {"num_branches": 0}}) == 100.0


def test_write_floor_only_rises(tmp_path, monkeypatch) -> None:
    ratchet = tmp_path / "coverage.json"
    ratchet.write_text(json.dumps(RATCHET), encoding="utf-8")
    report = tmp_path / "report.json"
    report.write_text(json.dumps(REPORT), encoding="utf-8")
    monkeypatch.setattr(coverage_gate, "RATCHET", ratchet)
    monkeypatch.setattr(coverage_gate, "load_ratchet", lambda: json.loads(ratchet.read_text()))
    assert coverage_gate.main([str(report), "--write-floor"]) == 0
    assert json.loads(ratchet.read_text())["branch_floor"] == 80.0
    lower = {**REPORT, "totals": {"num_branches": 200, "covered_branches": 100}}
    report.write_text(json.dumps(lower), encoding="utf-8")
    assert coverage_gate.main([str(report), "--write-floor"]) == 0
    assert json.loads(ratchet.read_text())["branch_floor"] == 80.0
    assert coverage_gate.main([str(report)]) == 1


def test_committed_ratchet_has_the_planned_floors() -> None:
    data = coverage_gate.load_ratchet()
    assert data["branch_floor"] >= 76.0
    assert data["static_branch_floor"] >= 76.0
    assert data["diff_floor"] == 90.0
