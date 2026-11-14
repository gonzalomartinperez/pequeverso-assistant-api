"""Synthetic native mutmut metadata; no mutation processes in these tests."""

import json

import pytest

from scripts import mutation_ratchet
from scripts.mutation_ratchet import (
    Baseline,
    Results,
    check,
    eligible_modules,
    main,
    patterns,
    prune_meta,
    read_changed_file,
    read_results,
    shard_modules,
)

BUDGET = "app/domain/budget.py"
REDACTION = "app/domain/redaction.py"
ANSWERS = "app/application/answers.py"


def res(**counts):
    return Results(**counts)


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
    assert results[BUDGET] == Results(
        killed=2, survived=2, timeout=1, suspicious=1, excluded=3, unchecked=2
    )
    assert results[BUDGET].score == pytest.approx(100 * 2 / 6, abs=0.01)


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
    results = {BUDGET: res(killed=8119, survived=1881), REDACTION: res(killed=5999, survived=4001)}
    problems = check(baseline, results, [BUDGET, REDACTION])
    assert len(problems) == 2
    assert "81.20%" in problems[0]
    assert "60.00%" in problems[1]
    ok = {BUDGET: res(killed=812, survived=188), REDACTION: res(killed=6, survived=4)}
    assert not check(baseline, ok, [BUDGET, REDACTION])


def test_pr_mode_ignores_unchanged_baseline_modules():
    baseline = Baseline(60, 75, {ANSWERS: 80, BUDGET: 50}, {})
    results = {BUDGET: res(killed=6, survived=4)}
    assert not check(baseline, results, [BUDGET])
    assert check(baseline, {BUDGET: res(killed=5, survived=5)}, [BUDGET])
    assert not check(baseline, {}, ["CONTRIBUTING.md"])


def test_changed_module_without_results_or_with_zero_keys():
    baseline = Baseline(60, 75, {}, {})
    assert "missing" in check(baseline, {}, [BUDGET])[0]
    assert not check(baseline, {BUDGET: res()}, [BUDGET])
    assert not check(baseline, {}, ["app/domain/__init__.py"])


@pytest.mark.parametrize("mode", ["pr", "full"])
def test_unchecked_makes_required_module_incomplete(mode):
    baseline = Baseline(60, 75, {}, {})
    results = {name: res(killed=1) for name in eligible_modules()}
    results[BUDGET] = res(killed=9, survived=1, unchecked=1)
    problems = check(baseline, results, [BUDGET], mode)
    assert len(problems) == 1 and "incomplete run" in problems[0]


def test_full_mode_requires_every_module_with_keys_and_skips_zero_key():
    baseline = Baseline(60, 75, {BUDGET: 70}, {})
    results = {name: res(killed=1) for name in eligible_modules()}
    results[BUDGET] = res(killed=1, survived=1)
    results[REDACTION] = res()
    results["app/domain/language.py"] = res(unchecked=2)
    problems = check(baseline, results, [], "full")
    assert [p.split(":")[0] for p in problems] == ["app/domain/budget.py", "app/domain/language.py"]
    assert "below required 70.00%" in problems[0]
    assert "incomplete" in problems[1]


def test_full_mode_reports_modules_missing_from_the_merge():
    baseline = Baseline(60, 75, {}, {})
    results = {name: res(killed=1) for name in eligible_modules() if name != BUDGET}
    assert check(baseline, results, [], "full") == [
        f"{BUDGET}: missing measured results; run mutmut first"
    ]


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
    assert main([*args, "--write", "--mode", "full"]) == 1
    assert Baseline.load(path).modules[BUDGET] == 50
    assert "below required" in capsys.readouterr().err


def test_cli_write_refuses_unchecked_and_check_fails_incomplete(tmp_path, capsys):
    path = baseline_file(tmp_path)
    results = tmp_path / "mutants"
    metadata(results, BUDGET, {"a": 1, "b": 1, "c": None})
    args = ["--baseline", str(path), "--results", str(results)]
    assert main([*args, "--write"]) == 1
    assert Baseline.load(path).modules == {}
    assert "refusing --write" in capsys.readouterr().err
    assert main([*args, "--changed", BUDGET]) == 1
    assert "incomplete run" in capsys.readouterr().err
    metadata(results, BUDGET, {"a": 1, "b": 2})
    assert main([*args, "--changed", BUDGET]) == 1


def test_no_tests_exit_code_counts_as_survived():
    result = Results()
    for code in (1, 33):
        result.add(code)
    assert result.survived == 1 and result.score == 50


def test_cli_pr_mode_reviewer_repro(tmp_path):
    path = baseline_file(tmp_path, {ANSWERS: 80, "app/domain/budget.py": 50})
    results = tmp_path / "mutants"
    metadata(results, BUDGET, {"a": 1, "b": 1, "c": 1, "d": 0})
    args = ["--baseline", str(path), "--results", str(results)]
    assert main([*args, "--mode", "pr", "--changed", BUDGET]) == 0


def test_cli_full_mode_empty_baseline_notice_and_incomplete(tmp_path, capsys):
    path = baseline_file(tmp_path)
    results = tmp_path / "mutants"
    for module in eligible_modules():
        metadata(results, module, {"a": 1, "b": 0})
    metadata(results, REDACTION, {})
    args = ["--baseline", str(path), "--results", str(results), "--mode", "full"]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "::notice::baseline not yet recorded; run --write from these results" in out
    assert "below the weekly target" in out
    assert main([*args, "--write"]) == 0
    assert Baseline.load(path).modules.keys() == set(eligible_modules()) - {REDACTION}
    metadata(results, BUDGET, {"a": 1, "b": None})
    assert main(args) == 1


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
    changed = [BUDGET, "app/adapters/sqlite/store.py", "README.md", "app/domain/gone.py"]
    assert patterns(changed) == ["app.domain.budget.*"]
    assert patterns(["docs/x.md"]) == []
    assert patterns([".github/workflows/mutation.yml", BUDGET]) is None
    assert patterns(["-weird.py", "./" + BUDGET]) == ["app.domain.budget.*"]


def test_patterns_omit_init_and_function_less_files(tmp_path, monkeypatch):
    domain = tmp_path / "app/domain"
    domain.mkdir(parents=True)
    (domain / "__init__.py").write_text("def f():\n    pass\n")
    (domain / "consts.py").write_text("X = 1\n")
    (domain / "funcs.py").write_text("class A:\n    async def m(self):\n        pass\n")
    monkeypatch.setattr(mutation_ratchet, "ROOT", tmp_path)
    monkeypatch.setattr(mutation_ratchet, "SCOPED_FILES", frozenset())
    assert eligible_modules() == ["app/domain/funcs.py"]
    changed = ["app/domain/__init__.py", "app/domain/consts.py", "app/domain/funcs.py"]
    assert patterns(changed) == ["app.domain.funcs.*"]


def test_real_scope_has_no_init_or_function_less_files():
    modules = eligible_modules()
    assert modules and BUDGET in modules
    assert all(not m.endswith("__init__.py") for m in modules)


def test_shards_cover_every_module_exactly_once():
    for count in (1, 3, 4, 7):
        shards = [shard_modules(i, count) for i in range(1, count + 1)]
        flat = [m for shard in shards for m in shard]
        assert sorted(flat) == eligible_modules()
        assert len(flat) == len(set(flat))
    with pytest.raises(ValueError, match="shard index"):
        shard_modules(5, 4)


def test_select_cli_prints_patterns(capsys):
    assert main(["--select", "--changed", BUDGET, "app/application/sessions.py"]) == 0
    assert capsys.readouterr().out.split() == ["app.application.sessions.*", "app.domain.budget.*"]
    assert main(["--select", "--changed", "scripts/mutation_ratchet.py"]) == 0
    assert capsys.readouterr().out.strip() == "*"


def test_select_shard_cli(capsys):
    seen: list[str] = []
    for i in range(1, 5):
        assert main(["--select", "--shard", f"{i}/4"]) == 0
        seen += capsys.readouterr().out.split()
    assert sorted(seen) == sorted(
        m.removesuffix(".py").replace("/", ".") + ".*" for m in eligible_modules()
    )
    with pytest.raises(SystemExit):
        main(["--select", "--shard", "0/4"])


def test_changed_file_accepts_nul_and_newlines(tmp_path, capsys):
    nul = tmp_path / "nul"
    nul.write_bytes(f"{BUDGET}\0-evil name.py\0\0README.md\0".encode())
    assert read_changed_file(nul) == [BUDGET, "-evil name.py", "README.md"]
    nl = tmp_path / "nl"
    nl.write_text(f"\n{BUDGET}\n\napp/application/sessions.py\n")
    assert read_changed_file(nl) == [BUDGET, "app/application/sessions.py"]
    assert main(["--select", f"--changed-file={nl}"]) == 0
    assert capsys.readouterr().out.split() == ["app.application.sessions.*", "app.domain.budget.*"]
    assert main(["--select", f"--changed-file={nul}"]) == 0
    assert capsys.readouterr().out.strip() == "app.domain.budget.*"


def test_shard_prune_then_merge_takes_the_checking_shard(tmp_path):
    modules = eligible_modules()
    merged = tmp_path / "merged"
    for index in range(1, 5):
        shard_dir = tmp_path / f"shard{index}"
        for module in modules:  # mutmut leaves every module, unchecked outside the run
            mine = module in shard_modules(index, 4)
            metadata(shard_dir, module, {"a": 1, "b": 0} if mine else {"a": None, "b": None})
        assert main(["--results", str(shard_dir), "--prune-meta", "--shard", f"{index}/4"]) == 0
        assert {p.relative_to(shard_dir).as_posix()[:-5] for p in shard_dir.rglob("*.meta")} == set(
            shard_modules(index, 4)
        )
        for path in shard_dir.rglob("*.meta"):  # merge-multiple: plain union of disjoint files
            target = merged / path.relative_to(shard_dir)
            assert not target.exists()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
    results = read_results(merged)
    assert set(results) == set(modules)
    assert all(r.unchecked == 0 and r.score == 50 for r in results.values())
    base = baseline_file(tmp_path)
    assert main(["--baseline", str(base), "--results", str(merged), "--mode", "full"]) == 0


def test_prune_meta_requires_shard(tmp_path, capsys):
    assert main(["--results", str(tmp_path), "--prune-meta"]) == 1
    metadata(tmp_path, BUDGET, {"a": 1})
    assert prune_meta(tmp_path, []) == [BUDGET]
