"""Synthetic native mutmut metadata; no mutation processes in these tests."""

import json

import pytest

from scripts.mutation_ratchet import Baseline, Results, check, main, read_results

BUDGET = "app/domain/budget.py"
REDACTION = "app/domain/redaction.py"


def metadata(root, module, codes):
    path = root / (module + ".meta")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"exit_code_by_key": codes, "durations_by_key": {}}))


def baseline_file(tmp_path, modules=None):
    path = tmp_path / "mutation.json"
    Baseline(60, 75, modules or {}, {"mutant": "reviewed equivalent"}).write(path, {})
    return path


def test_native_metadata_score_and_exclusions(tmp_path):
    metadata(tmp_path, BUDGET, dict(enumerate([1, 3, 0, 36, 35, 34, None, 5, 33, 2, 37])))
    metadata(tmp_path, "app/adapters/ignored.py", {"x": 0})
    results = read_results(tmp_path)
    assert list(results) == [BUDGET]
    assert results[BUDGET] == Results(killed=2, survived=1, timeout=1, suspicious=1, excluded=6)
    assert results[BUDGET].score == 40


@pytest.mark.parametrize("code", [-24, 24, 152, 255, 36])
def test_timeout_exit_codes(code):
    result = Results()
    result.add(code)
    assert result.timeout == 1
    assert result.score == 0


@pytest.mark.parametrize("code", [35, 99, -11, -9])
def test_unknown_and_crashed_workers_are_suspicious(code):
    result = Results()
    result.add(code)
    assert result.suspicious == 1
    assert result.score == 0


def test_unchecked_is_unmeasured():
    result = Results()
    result.add(None)
    assert result.score is None


def test_baseline_regression_and_changed_floor_are_independent():
    baseline = Baseline(60, 75, {BUDGET: 81.2}, {})
    problems = check(baseline, {BUDGET: 81.19, REDACTION: 59.99}, [REDACTION])
    assert len(problems) == 2
    assert "81.20%" in problems[0]
    assert "60.00%" in problems[1]
    assert not check(baseline, {BUDGET: 81.2, REDACTION: 60}, [REDACTION])


def test_weekly_target_is_advisory_and_floor_only_applies_to_changed_scope():
    baseline = Baseline(60, 75, {BUDGET: 40}, {})
    assert not check(baseline, {BUDGET: 40, REDACTION: 20}, ["CONTRIBUTING.md"])
    assert check(baseline, {BUDGET: 40}, ["./app/domain/budget.py"])


def test_missing_baselined_and_changed_results_fail():
    baseline = Baseline(60, 75, {BUDGET: 80}, {})
    assert len(check(baseline, {}, [REDACTION])) == 2


def test_write_only_raises_and_preserves_unmeasured_and_equivalents(tmp_path):
    path = baseline_file(tmp_path, {BUDGET: 81.2, REDACTION: 50})
    baseline = Baseline.load(path)
    baseline.write(path, {BUDGET: 70, "app/application/sessions.py": 61.25})
    loaded = Baseline.load(path)
    assert loaded.modules == {BUDGET: 81.2, REDACTION: 50, "app/application/sessions.py": 61.25}
    assert loaded.equivalent_mutants == {"mutant": "reviewed equivalent"}
    loaded.write(path, {BUDGET: 90})
    assert Baseline.load(path).modules[BUDGET] == 90


@pytest.mark.parametrize("value", [True, "60", -1, 101, float("nan"), float("inf")])
def test_invalid_baseline_percentages_fail(tmp_path, value):
    path = baseline_file(tmp_path)
    data = json.loads(path.read_text())
    data["modules"] = {BUDGET: value}
    path.write_text(json.dumps(data))
    with pytest.raises((ValueError, TypeError), match="percentage"):
        Baseline.load(path)


@pytest.mark.parametrize("code", ["0", True, [], {}])
def test_invalid_exit_codes_fail(tmp_path, code):
    metadata(tmp_path, BUDGET, {"mutant": code})
    with pytest.raises(ValueError, match="exit code"):
        read_results(tmp_path)


def test_cli_write_check_and_regression(tmp_path, capsys):
    path = baseline_file(tmp_path)
    results = tmp_path / "mutants"
    metadata(results, BUDGET, {"killed": 1, "survivor": 0})
    args = ["--baseline", str(path), "--results", str(results)]
    assert main([*args, "--write"]) == 0
    assert Baseline.load(path).modules == {BUDGET: 50}
    assert main(args) == 0
    assert main([*args, "--changed", BUDGET]) == 1
    metadata(results, BUDGET, {"survivor": 0})
    assert main([*args, "--write"]) == 1
    assert Baseline.load(path).modules[BUDGET] == 50
    assert "below required" in capsys.readouterr().err


def test_cli_fails_without_results_or_on_corrupt_metadata(tmp_path):
    path = baseline_file(tmp_path)
    args = ["--baseline", str(path), "--results", str(tmp_path / "missing")]
    assert main(args) == 1
    metadata(tmp_path, BUDGET, {"x": None})
    args[-1] = str(tmp_path)
    assert main(args) == 1
    (tmp_path / (BUDGET + ".meta")).write_text("{broken")
    assert main(args) == 1


def test_select_maps_changed_scoped_modules_to_mutant_patterns():
    from scripts.mutation_ratchet import patterns

    changed = [BUDGET, "app/adapters/sqlite/store.py", "README.md", "app/domain/gone.py"]
    assert patterns(changed) == ["app.domain.budget.*"]
    assert patterns(["docs/x.md"]) == []
    assert patterns([".github/workflows/mutation.yml", BUDGET]) is None


def test_select_cli_prints_patterns(capsys):
    assert main(["--select", "--changed", BUDGET, "app/application/sessions.py"]) == 0
    assert capsys.readouterr().out.split() == ["app.application.sessions.*", "app.domain.budget.*"]
    assert main(["--select", "--changed", "scripts/mutation_ratchet.py"]) == 0
    assert capsys.readouterr().out.strip() == "*"
