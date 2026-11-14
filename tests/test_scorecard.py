"""Scorecard aggregation (PVA-M2.12): statuses, axes and failure on a regressed baseline."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from scripts import scorecard
from scripts.scorecard import Metric

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

GOLDEN_OK = {"overall": {"items": 60, "passed": 60}}
LOAD = {  # a 2026-11-14 nightly measurement
    "ttfe_seconds": {"p95": 0.247},
    "gap_seconds": {"p95": 0.076},
    "error_rate": 0.0,
}


def test_metric_status_by_direction() -> None:
    assert Metric("a", "D2", 3, 5, "max", "x").status == "ok"
    assert Metric("a", "D2", 6, 5, "max", "x").status == "regressed"
    assert Metric("a", "D3", 80, 76, "min", "x").status == "ok"
    assert Metric("a", "D3", 70, 76, "min", "x").status == "regressed"
    assert Metric("a", "D3", None, 76, "min", "x").status == "unmeasured"
    assert Metric("a", "D3", 80, None, "min", "x").status == "unmeasured"


def test_axes_pass_only_when_every_metric_is_ok() -> None:
    metrics = [
        Metric("golden_items", "P3", 60, 60, "min", "x"),
        Metric("golden_pass_percent", "P3", 100, 100, "min", "x"),
        Metric("branch_coverage_percent", "D3", None, 76, "min", "x"),
    ]
    document = scorecard.build(metrics, "sha", "2026-11-14T00:00:00Z")
    assert document["axes"]["P3"]["automatic_pass"] is True
    assert document["axes"]["D3"]["automatic_pass"] is False
    assert document["axes"]["D1"]["automatic_pass"] is False
    assert document["unmeasured"] == ["branch_coverage_percent"]
    assert document["regressions"] == []


def run(tmp_path: Path, golden: dict[str, object], *extra: str) -> tuple[int, dict]:
    path = tmp_path / "golden.json"
    path.write_text(json.dumps(golden), encoding="utf-8")
    load = tmp_path / "load.json"
    load.write_text(json.dumps(LOAD), encoding="utf-8")
    out = tmp_path / "scorecard.json"
    code = scorecard.main(
        ["--skip-static", "--golden", str(path), "--load", str(load), "--out", str(out), *extra]
    )
    return code, json.loads(out.read_text(encoding="utf-8"))


def test_committed_baselines_pass_with_a_green_golden_run(tmp_path: Path) -> None:
    code, document = run(tmp_path, GOLDEN_OK)
    assert code == 0
    assert document["metrics"]["golden_pass_percent"]["status"] == "ok"


def test_a_failing_golden_item_is_a_regression(tmp_path: Path) -> None:
    code, document = run(tmp_path, {"overall": {"items": 60, "passed": 59}})
    assert code == 1
    assert document["regressions"] == ["golden_pass_percent"]


def test_a_deliberately_regressed_baseline_fails_the_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ratchets = tmp_path / "ratchets"
    ratchets.mkdir()
    for name in ("golden.json", "coverage.json", "mutation.json", "perf.json"):
        source = scorecard.RATCHETS / name
        if source.is_file():
            (ratchets / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    golden = json.loads((ratchets / "golden.json").read_text(encoding="utf-8"))
    golden["items"] = 61  # a baseline the current set cannot meet
    (ratchets / "golden.json").write_text(json.dumps(golden), encoding="utf-8")
    monkeypatch.setattr(scorecard, "RATCHETS", ratchets)
    code, document = run(tmp_path, GOLDEN_OK)
    assert code == 1
    assert "golden_items" in document["regressions"]


def test_load_metrics_use_a_twenty_percent_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        scorecard, "_ratchet", lambda name: {"ttfe_p95_seconds": 1.0, "gap_p95_seconds": 0.1}
    )
    by_name = {m.name: m for m in scorecard.load_metrics(LOAD)}
    assert by_name["ttfe_p95_seconds"].status == "ok"  # 0.247 <= 1.2
    assert by_name["gap_p95_seconds"].status == "ok"  # 0.076 <= 0.12
    slow = {**LOAD, "gap_seconds": {"p95": 0.2}}
    assert scorecard.load_metrics(slow)[1].status == "regressed"  # 0.2 > 0.12
    assert by_name["load_error_percent"].status == "ok"


def test_nightly_workflow_is_pinned_least_privilege_and_secret_free() -> None:
    import re

    import yaml

    text = (scorecard.ROOT / ".github/workflows/nightly.yml").read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    events = workflow.get("on", workflow.get(True))
    assert set(events) == {"schedule", "workflow_dispatch", "push", "pull_request"}
    assert events["push"] == {"branches": ["develop"]}
    assert set(events["pull_request"]["paths"]) == {
        ".github/workflows/nightly.yml",
        "scripts/scorecard.py",
    }
    assert workflow["permissions"] == {}
    assert "secrets." not in text
    assert workflow["env"]["AI_PROVIDER"] == "fixture"
    assert workflow["env"]["ALLOW_PAID_AI"] == "false"
    (job,) = workflow["jobs"].values()
    assert job["permissions"] == {"contents": "read"}
    for step in job["steps"]:
        if "uses" in step:
            assert re.fullmatch(r"[\w./-]+@[a-f0-9]{40}", step["uses"]), step["uses"]
    runs = "\n".join(step.get("run", "") for step in job["steps"])
    for command in (
        "pytest -q -n auto --cov",
        "HYPOTHESIS_PROFILE",
        "evals.runner golden --replay",
        "tests.load.sse_load --streams 12 --duration 900",
        "scripts.scorecard",
    ):
        assert command in runs or command in text, command


def test_coverage_uses_the_static_floor_and_fails_closed_without_branch_data() -> None:
    floor = scorecard._ratchet("coverage.json")["static_branch_floor"]
    above = {"files": {"app/x.py": {}}, "totals": {"num_branches": 100, "covered_branches": 99}}
    below = {"files": {"app/x.py": {}}, "totals": {"num_branches": 100, "covered_branches": 1}}
    lost = {"files": {}, "totals": {"num_branches": 0, "covered_branches": 0}}
    (ok,) = scorecard.coverage_metrics(above)
    assert (ok.name, ok.baseline, ok.status) == ("static_branch_coverage_percent", floor, "ok")
    assert scorecard.coverage_metrics(below)[0].status == "regressed"
    assert scorecard.coverage_metrics(lost)[0].status == "unmeasured"


def test_a_requested_input_that_was_not_produced_fails(tmp_path: Path) -> None:
    golden = tmp_path / "golden.json"
    golden.write_text(json.dumps(GOLDEN_OK), encoding="utf-8")
    out = tmp_path / "scorecard.json"
    missing = tmp_path / "sse-load.json"
    argv = ["--skip-static", "--golden", str(golden), "--load", str(missing), "--out", str(out)]
    assert scorecard.main(argv) == 1
    assert json.loads(out.read_text(encoding="utf-8"))["missing_inputs"][0] == str(missing)


def test_an_unusable_requested_input_fails(tmp_path: Path) -> None:
    lost = tmp_path / "coverage.json"
    lost.write_text(json.dumps({"files": {}, "totals": {"num_branches": 0}}), encoding="utf-8")
    code, document = run(tmp_path, GOLDEN_OK, "--coverage", str(lost))
    assert code == 1
    assert "static_branch_coverage_percent (unmeasured)" in document["missing_inputs"]
    garbage = tmp_path / "golden-bad.json"
    garbage.write_text("", encoding="utf-8")
    out = tmp_path / "out.json"
    assert scorecard.main(["--skip-static", "--golden", str(garbage), "--out", str(out)]) == 1


def test_load_fails_on_a_harness_check_or_no_completed_run() -> None:
    failing = {**LOAD, "checks": {"observations": True, "rss_growth": False}}
    by_name = {m.name: m for m in scorecard.load_metrics(failing)}
    assert by_name["load_checks_failed"].status == "regressed"
    assert by_name["ttfe_p95_seconds"].baseline <= scorecard.LOAD_LIMITS["ttfe_p95_seconds"]
    dead = {**LOAD, "ttfe_seconds": {"p95": None}, "gap_seconds": {"p95": None}}
    assert {m.status for m in scorecard.load_metrics(dead)[:2]} == {"unmeasured"}


def test_import_contracts_are_parsed_from_lint_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    real = subprocess.run

    def fake(stdout: str):
        def run(command, *args, **kwargs):
            if str(command[0]).endswith("lint-imports"):
                return subprocess.CompletedProcess(command, 1, stdout=stdout, stderr="")
            return real(command, *args, **kwargs)

        return run

    monkeypatch.setattr(scorecard.subprocess, "run", fake("Contracts: 9 kept, 1 broken."))
    by_name = {m.name: m for m in scorecard.static_metrics()}
    assert by_name["import_contracts_broken"].status == "regressed"
    monkeypatch.setattr(scorecard.subprocess, "run", fake(""))
    by_name = {m.name: m for m in scorecard.static_metrics()}
    assert by_name["import_contracts_broken"].status == "unmeasured"
