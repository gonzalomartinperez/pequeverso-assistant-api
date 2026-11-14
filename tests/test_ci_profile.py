"""Assert the paired graph and execute its fail-closed aggregate without services."""

from __future__ import annotations

import json
import os
import re
import subprocess
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from scripts import ci_identity

ROOT = Path(__file__).resolve().parents[1]
NAMES = {
    "workflows": "Workflow validation",
    "secrets": "Secret scan",
    "static": "Static checks",
    "database": "Database tests",
    "container": "Container verification",
    "checks": "checks",
}
REUSABLE = ("classify", "docs", "security")
GATED = ("docs", "security", "workflows", "secrets", "static", "database", "container")
NEEDS = {
    "workflows": ["classify"],
    "secrets": ["classify"],
    "static": ["classify"],
    "database": ["classify", "static"],
    "container": ["classify", "static"],
    "checks": ["ci-gate"],
}
STANDARDS = "gonzalomartinperez/engineering-standards/"
SELECTED = "contains(fromJSON(needs.classify.outputs.jobs), '{}')"
IFS = {
    **{key: SELECTED.format(key) for key in ("workflows", "secrets", "static")},
    **{
        key: "${{ !cancelled() && !failure() && needs.static.result == 'success' && "
        + SELECTED.format(key)
        + " }}"
        for key in ("database", "container")
    },
    "checks": "always()",
}
PROFILE = ROOT / ".github/ci-profile.json"
COMMANDS = {
    "workflows": [],
    "secrets": [".github/scripts/secret-scan.sh"],
    "static": [
        "uv sync --frozen",
        "ruff check",
        "ruff format --check",
        "python -m scripts.ruff_ratchet",
        "python -m scripts.prompt_lock --base=FETCH_HEAD",
        "uv run lint-imports",
        "uv run python -m scripts.complexity_ratchet",
        "uv run vulture",
        "python -m scripts.validate_skills",
        "uv run mypy",
        "pyrefly@",
        "uv run pytest -q",
        "contracts.export --check",
        "scripts/evaluate_retrieval.py",
        "scripts/evaluate_conversations.py",
    ],
    "database": [
        "infra/docker/postgres/Dockerfile",
        "infra/docker/neo4j/Dockerfile",
        "scripts/smoke_knowledge_postgres.sh",
        "scripts.smoke_knowledge_neo4j",
        "scripts.smoke_graph_runtime",
        "--with-index-jobs --with-evaluation-tests",
    ],
    "container": [
        "infra/docker/app/Dockerfile",
        "scripts/smoke_container.sh pequeverso-assistant-api:smoke",
        "container-structure-test",
        "infra/docker/app/structure-test.yaml",
        "sha256sum -c",
        "dockle",
        "--exit-level warn",
        "rewrite-timestamp=true",
        "SOURCE_DATE_EPOCH",
        "scripts.compare_oci_images",
    ],
}


def workflow():
    return yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())


def validate(value):
    events = value.get("on", value.get(True))
    assert value["name"] == "ci"
    assert events["pull_request"] == {
        "branches": ["develop", "main"],
        "types": [
            "opened",
            "synchronize",
            "reopened",
            "labeled",
            "unlabeled",
            "edited",
            "ready_for_review",
        ],
    }
    assert events["push"] == {"branches": ["develop", "main"]}
    assert {"merge_group", "workflow_dispatch"} <= events.keys()
    assert not ({"pull_request_target", "workflow_run"} & events.keys())
    assert value["permissions"] == {}
    assert (
        value["concurrency"]["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"
    )
    assert value["concurrency"]["group"] == (
        "ci-${{ github.workflow }}-${{ github.event_name == 'pull_request' && github.ref || github.sha }}"
    )
    assert value["env"]["AI_PROVIDER"] == "fixture"
    assert value["env"]["ALLOW_PAID_AI"] == "false"
    assert value["env"]["LANGSMITH_TRACING"] == "false"
    assert set(value["jobs"]) == {*NAMES, *REUSABLE, "ci-gate"}
    validate_shared(value["jobs"])
    for key, display in NAMES.items():
        job = value["jobs"][key]
        assert job["name"] == display
        assert needs_of(job) == NEEDS[key]
        assert job["runs-on"] == "ubuntu-24.04"
        assert not job.get("continue-on-error")
        assert job.get("if") == IFS[key]
        assert job["permissions"] == ({} if key == "checks" else {"contents": "read"})
        for step in job["steps"]:
            assert "if" not in step
            assert not step.get("continue-on-error")
            if "uses" in step:
                assert re.fullmatch(r"[\w./-]+@[a-f0-9]{40}", step["uses"])
                assert "upload-artifact" not in step["uses"] or key == "container"
                assert "trivy" not in step["uses"]
            if step.get("uses", "").startswith("actions/checkout@"):
                assert step["with"]["persist-credentials"] is False
                assert "ref" not in step["with"]
        commands = "\n".join(step.get("run", "") for step in job["steps"])
        for command in COMMANDS.get(key, []):
            assert command in commands
        if key != "checks":
            assert "python3 -m scripts.ci_identity" in commands
    container = value["jobs"]["container"]
    assert container["timeout-minutes"] <= 30
    uses = {step["uses"].split("@")[0]: step for step in container["steps"] if "uses" in step}
    assert {"hadolint/hadolint-action", "anchore/sbom-action", "anchore/scan-action"} <= uses.keys()
    assert uses["hadolint/hadolint-action"]["with"]["config"] == ".hadolint.yaml"
    assert uses["anchore/sbom-action"]["with"]["format"] == "cyclonedx-json"
    assert uses["anchore/scan-action"]["with"]["config"] == ".grype.yaml"
    assert uses["anchore/scan-action"]["with"]["fail-build"] is True
    assert uses["anchore/scan-action"]["with"]["only-fixed"] is True
    assert uses["anchore/scan-action"]["with"]["severity-cutoff"] == "high"
    upload = uses["actions/upload-artifact"]["with"]
    assert upload["name"] == "sbom-app-cyclonedx"
    assert upload["retention-days"] == 14
    assert all("${{" not in step.get("run", "") for step in container["steps"])
    static_steps = value["jobs"]["static"]["steps"]
    setup = [
        step for step in static_steps if step.get("uses", "").startswith("actions/setup-node@")
    ]
    assert len(setup) == 1
    assert setup[0]["uses"] == "actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1"
    assert setup[0]["with"] == {"node-version": "24.22.0", "package-manager-cache": False}
    fixture = [
        step
        for step in static_steps
        if step.get("run")
        == "timeout 10s node --test tests/fixtures/product-analytics-pointer.test.cjs"
    ]
    assert len(fixture) == 1
    assert static_steps.index(setup[0]) < static_steps.index(fixture[0])
    actions = [step.get("uses", "") for step in value["jobs"]["workflows"]["steps"]]
    assert any(action.startswith("raven-actions/actionlint@") for action in actions)
    assert any(action.startswith("zizmorcore/zizmor-action@") for action in actions)
    assert value["jobs"]["secrets"]["steps"][0]["with"]["fetch-depth"] == 0
    alias = value["jobs"]["checks"]
    assert len(alias["steps"]) == 1
    assert alias["steps"][0]["run"].strip() == 'test "$CI_GATE_RESULT" = success'
    assert alias["steps"][0]["env"] == {"CI_GATE_RESULT": "${{ needs.ci-gate.result }}"}


def needs_of(job):
    needs = job.get("needs", [])
    return [needs] if isinstance(needs, str) else needs


def validate_shared(jobs):
    for key in REUSABLE:
        assert jobs[key]["uses"].startswith(STANDARDS + ".github/workflows/" + key + ".yml@")
        assert needs_of(jobs[key]) == ([] if key == "classify" else ["classify"])
        assert jobs[key].get("if") == (None if key == "classify" else SELECTED.format(key))
    assert jobs["classify"]["permissions"] == {"contents": "read", "pull-requests": "read"}
    security = jobs["security"]["with"]
    assert security["dependency-review"] is True
    # gitleaks runs in the local `secrets` job with the repository's reviewed config.
    assert security["gitleaks"] is False
    licences = {item.strip() for item in security["allow-licenses"].split(",")}
    # ADR-0015: the only copyleft additions are LGPL-3.0 (psycopg) and MPL-2.0.
    assert {"LGPL-3.0-only", "LGPL-3.0-or-later", "MPL-2.0"} <= licences
    assert not {item for item in licences if "GPL" in item and not item.startswith("LGPL-3.0")}
    assert jobs["security"]["permissions"] == {"contents": "read", "pull-requests": "read"}
    assert jobs["docs"]["permissions"] == {"contents": "read"}
    assert "docs/verification" in jobs["docs"]["with"]["lychee-args"]
    gate = jobs["ci-gate"]
    assert gate["if"] == "always()" and gate["permissions"] == {}
    assert gate["needs"] == ["classify", *GATED]
    action = next(
        step for step in gate["steps"] if STANDARDS + "actions/ci-gate@" in step.get("uses", "")
    )
    assert action["with"] == {
        "needs": "${{ toJSON(needs) }}",
        "expected": "${{ needs.classify.outputs.jobs }}",
    }


def test_actual_profile_preserves_required_work():
    validate(workflow())
    assert all((ROOT / name).is_file() for name in ci_identity.BUILD_INPUTS)


@pytest.mark.parametrize("key", NAMES)
def test_missing_or_renamed_job_and_wrong_dependency_are_rejected(key):
    for field, replacement in (("name", "placeholder"), ("needs", ["unknown"])):
        value = workflow()
        value["jobs"][key][field] = replacement
        with pytest.raises(AssertionError):
            validate(value)
    value = workflow()
    del value["jobs"][key]
    with pytest.raises(AssertionError):
        validate(value)


@pytest.mark.parametrize(
    "mode", ["path", "write", "action", "skip", "continue", "empty_gate", "missing_command"]
)
def test_filtered_privileged_or_missing_work_cannot_pass(mode):
    value = workflow()
    job = value["jobs"]["database"]
    if mode == "path":
        value.get("on", value.get(True))["pull_request"]["paths"] = ["app/**"]
    elif mode == "write":
        job["permissions"]["contents"] = "write"
    elif mode == "action":
        job["steps"][0]["uses"] = "actions/checkout@main"
    elif mode == "skip":
        job["steps"][-1]["if"] = "false"
    elif mode == "continue":
        job["continue-on-error"] = True
    elif mode == "empty_gate":
        value["jobs"]["checks"]["steps"][0]["env"] = {}
    else:
        job["steps"] = [
            s for s in job["steps"] if "scripts.smoke_graph_runtime" not in s.get("run", "")
        ]
    with pytest.raises(AssertionError):
        validate(value)


def test_actual_aggregate_shell_fails_for_every_missing_or_unsuccessful_job():
    gate = workflow()["jobs"]["checks"]["steps"][0]
    assert set(gate["env"]) == {"CI_GATE_RESULT"}
    green = dict.fromkeys(gate["env"], "success")
    clean = {name: value for name, value in os.environ.items() if name not in green}

    def run(results):
        return subprocess.run(  # noqa: S603 -- execute only the owned aggregate, with synthetic results
            ["/bin/bash", "-e", "-c", gate["run"]],
            env={**clean, **results},
            capture_output=True,
            check=False,
        ).returncode

    assert run(green) == 0
    for key in green:
        for result in ("failure", "cancelled", "skipped", "pending", ""):
            assert run({**green, key: result}) != 0
        missing = deepcopy(green)
        del missing[key]
        assert run(missing) != 0


def test_required_check_name_is_unique_across_workflows():
    names = []
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        value = yaml.safe_load(path.read_text())
        names.extend(job.get("name", key) for key, job in value["jobs"].items())
    assert names.count("Required checks") == 0
    assert names.count("checks") == 1
    assert len(names) == len(set(names))


def identity_environment():
    return {
        "GITHUB_SHA": "a" * 40,
        "GITHUB_WORKFLOW_SHA": "b" * 40,
        "CI_BASE_SHA": "c" * 40,
        "GITHUB_RUN_ID": "17",
        "GITHUB_RUN_ATTEMPT": "1",
        "PRIVATE_SENTINEL": "never copied",
    }


def test_identity_records_hashes_not_environment_and_rejects_other_source(tmp_path):
    for name in ci_identity.BUILD_INPUTS:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("reviewed input")
    with (
        patch.object(ci_identity.subprocess, "check_output", return_value="a" * 40),
        patch.object(
            ci_identity.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)
        ),
    ):
        report = ci_identity.identity(tmp_path, identity_environment())
        assert report["source_sha"] == "a" * 40
        assert report["base_sha"] == "c" * 40
        assert set(report["build_inputs_sha256"]) == set(ci_identity.BUILD_INPUTS)
        assert "never copied" not in str(report)
        with pytest.raises(ValueError, match="candidate"):
            ci_identity.identity(tmp_path, {**identity_environment(), "GITHUB_SHA": "d" * 40})


@pytest.mark.parametrize("result", [1, 128])
def test_identity_rejects_dirty_or_unverifiable_source(tmp_path, result):
    with (
        patch.object(ci_identity.subprocess, "check_output", return_value="a" * 40),
        patch.object(
            ci_identity.subprocess, "run", return_value=subprocess.CompletedProcess([], result)
        ),
        pytest.raises(ValueError, match="Tracked inputs"),
    ):
        ci_identity.identity(tmp_path, identity_environment())


def test_image_identity_rejects_unknown_image_and_invalid_digest():
    with pytest.raises(ValueError, match="Unexpected"):
        ci_identity.image_identity("foreign:latest")
    with (
        patch.object(ci_identity.subprocess, "check_output", return_value="bad"),
        pytest.raises(ValueError, match="Invalid"),
    ):
        ci_identity.image_identity("pv-knowledge-pg:ci")
    with patch.object(ci_identity.subprocess, "check_output", return_value="sha256:" + "a" * 64):
        assert ci_identity.image_identity("pv-knowledge-pg:ci") == "sha256:" + "a" * 64


@pytest.mark.parametrize(
    "mutation", ["skip", "wrong_result", "empty_gate", "unconditional_success"]
)
def test_required_aggregate_cannot_skip_or_replace_any_prerequisite(mutation):
    value = workflow()
    gate = value["jobs"]["checks"]
    if mutation == "skip":
        gate["if"] = "success()"
    elif mutation == "wrong_result":
        gate["steps"][0]["env"]["CI_GATE_RESULT"] = "${{ needs.static.result }}"
    elif mutation == "empty_gate":
        gate["steps"] = []
    else:
        gate["steps"][0]["run"] = "true"
    with pytest.raises(AssertionError):
        validate(value)


@pytest.mark.parametrize("mutation", ["missing_setup", "version", "unpin", "missing_test", "order"])
def test_pointer_fixture_regression_cannot_be_removed_or_unpinned(mutation):
    value = workflow()
    steps = value["jobs"]["static"]["steps"]
    setup = next(step for step in steps if "actions/setup-node@" in step.get("uses", ""))
    fixture = next(step for step in steps if "node --test" in step.get("run", ""))
    if mutation == "missing_setup":
        steps.remove(setup)
    elif mutation == "version":
        setup["with"]["node-version"] = "24"
    elif mutation == "unpin":
        setup["uses"] = "actions/setup-node@main"
    elif mutation == "missing_test":
        steps.remove(fixture)
    else:
        steps.remove(setup)
        steps.append(setup)
    with pytest.raises(AssertionError):
        validate(value)


def test_container_gate_pins_are_strict():
    job = workflow()["jobs"]["container"]
    for key in ("DOCKLE_SHA256", "CST_SHA256"):
        assert re.fullmatch(r"[0-9a-f]{64}", job["env"][key]), key
    steps = {step.get("name", ""): step for step in job["steps"]}
    hadolint = next(
        step for step in job["steps"] if "hadolint/hadolint-action@" in step.get("uses", "")
    )
    assert hadolint["with"]["failure-threshold"] == "warning"
    dockle = next(step["run"] for step in steps.values() if "dockle" in step.get("run", ""))
    assert set(re.findall(r"--ignore (\S+)", dockle)) == {"CIS-DI-0008", "DKL-DI-0005"}
    repro = next(
        step["run"] for step in steps.values() if "rewrite-timestamp=true" in step.get("run", "")
    )
    assert "--provenance=false" in repro and "--sbom=false" in repro


def test_static_suite_runs_in_parallel_and_service_runs_keep_a_fixed_order():
    steps = workflow()["jobs"]["static"]["steps"]
    assert any(step.get("run", "").strip() == "uv run pytest -q -n auto" for step in steps)
    for script in (
        "scripts/smoke_knowledge_postgres.sh",
        "scripts/smoke_knowledge_neo4j.py",
        "scripts/smoke_graph_runtime.py",
    ):
        text = (ROOT / script).read_text()
        assert "no:randomly" in text, script


def glob_to_regex(pattern):
    """Mirror engineering-standards classify.yml: `**/` crosses directories, `*` stays in one segment."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + r"\Z")


def profile_map():
    return json.loads(PROFILE.read_text())


def classify_paths(paths, config=None):
    """Return the jobs classify selects for a pull request changing `paths`; None means run everything."""
    profiles = (config or profile_map())["profiles"]
    selected = set()
    for path in paths:
        hit = [
            n
            for n, spec in profiles.items()
            if any(glob_to_regex(g).match(path) for g in spec.get("paths", []))
        ]
        if not hit or path == ".github/ci-profile.json":
            return None
        selected.update(hit)
    return {job for name in selected for job in profiles[name]["adds"]}


def tracked_files():
    out = subprocess.run(
        ["git", "ls-files"],  # noqa: S607 -- fixed git query
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return out.splitlines()


def test_profile_map_shape_and_job_ids_exist_in_the_workflow():
    config = profile_map()
    assert config["version"] == 1 and config["required"] == "ci-gate"
    assert set(config['profiles']) == {
        'docs', 'code', 'contract', 'assistant-quality', 'container', 'database', 'workflow',
        'deps-weekly', 'release',
    }  # fmt: skip
    jobs = set(workflow()["jobs"])
    named = set(config.get("base", []))
    for name, spec in config["profiles"].items():
        assert spec.get("paths") or spec.get("trigger"), name
        named |= set(spec["adds"]) - {"all-profiles"}
    assert named <= jobs - {"classify", "ci-gate", "checks"}
    assert named == set(GATED)
    for name in ("deps-weekly", "release"):
        assert config["profiles"][name]["adds"] == ["all-profiles"]


def test_every_tracked_file_is_in_a_profile_so_nothing_falls_through_to_run_everything():
    profiles = profile_map()["profiles"]
    regexes = [glob_to_regex(g) for spec in profiles.values() for g in spec.get("paths", [])]
    orphans = [f for f in tracked_files() if not any(r.match(f) for r in regexes)]
    assert orphans == []


def test_gate_lists_every_job_except_classify_alias_and_itself_and_the_alias_depends_only_on_it():
    jobs = workflow()["jobs"]
    assert set(jobs["ci-gate"]["needs"]) == set(jobs) - {"ci-gate", "checks"}
    assert needs_of(jobs["checks"]) == ["ci-gate"]
    assert jobs["checks"]["if"] == "always()"


def test_every_standards_reference_is_pinned_to_one_commit():
    refs = set()
    for job in workflow()["jobs"].values():
        refs |= {s["uses"] for s in job.get("steps", []) if "uses" in s}
        refs |= {job["uses"]} if "uses" in job else set()
    shared = [r for r in refs if r.startswith(STANDARDS)]
    assert len(shared) >= 4
    pins = [re.fullmatch(r"[\w./-]+@([a-f0-9]{40})", r) for r in shared]
    assert all(pins), shared
    shas = {pin.group(1) for pin in pins if pin}
    assert len(shas) == 1


def test_docs_only_change_runs_docs_and_skips_code_database_and_container():
    jobs = classify_paths(["docs/ci.md", "docs/security.md", "CHANGELOG.md"])
    assert jobs == {"docs", "secrets"}
    assert not {"static", "database", "container"} & jobs


@pytest.mark.parametrize(
    ("paths", "present", "absent"),
    [
        (
            ["app/domain/language.py"],
            {"static", "secrets", "security", "database", "container"},
            set(),
        ),
        (["app/adapters/postgres/knowledge.py"], {"static", "database", "container"}, set()),
        (["tests/test_skills.py"], {"static", "secrets", "security"}, {"database", "container"}),
        (["README.md"], {"docs", "static"}, {"database", "container"}),
        (["migrations/001_initial.sql"], {"static", "database", "container"}, set()),
        (["infra/docker/app/Dockerfile"], {"static", "database", "container"}, set()),
        (
            [".github/workflows/ci.yml"],
            {"workflows", "security", "static", "secrets", "container", "database"},
            set(),
        ),
        (["contracts/openapi.json"], {"static", "secrets", "security"}, {"docs", "database"}),
        (["uv.lock"], {"static", "database", "container"}, set()),
        (["scripts/smoke_container.sh"], {"static", "database", "container"}, set()),
        ([".agents/skills/x/SKILL.md"], {"static", "docs"}, {"container"}),
    ],
)
def test_path_changes_select_the_expected_jobs(paths, present, absent):
    jobs = classify_paths(paths)
    assert present <= jobs
    assert not absent & jobs


@pytest.mark.parametrize(
    "paths", [["unmapped/file.bin"], ["docs/ci.md", "surprise.txt"], [".github/ci-profile.json"]]
)
def test_unknown_paths_and_profile_edits_run_everything(paths):
    assert classify_paths(paths) is None
