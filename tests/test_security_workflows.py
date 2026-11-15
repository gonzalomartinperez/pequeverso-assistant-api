"""Pin the scheduled security workflows (PVA-M1.6): Scorecard and the daily vulnerability job."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+$")


def load(name: str) -> dict:
    data = yaml.safe_load((WORKFLOWS / name).read_text())
    # PyYAML reads the bare `on` key as True.
    data["on"] = data.pop(True)
    return data


def uses(value: dict) -> list[str]:
    found: list[str] = []
    for job in value["jobs"].values():
        if "uses" in job:
            found.append(job["uses"])
        found.extend(step["uses"] for step in job.get("steps", []) if "uses" in step)
    return found


def raw_uses(name: str) -> list[str]:
    return [
        line.split("uses:", 1)[1].strip()
        for line in (WORKFLOWS / name).read_text().splitlines()
        if line.strip().startswith(("uses:", "- uses:"))
    ]


def test_scorecard_is_weekly_least_privilege_and_pinned():
    value = load("scorecard.yml")
    assert value["permissions"] == {}
    assert "schedule" in value["on"]
    assert "pull_request" not in value["on"] and "pull_request_target" not in value["on"]
    job = value["jobs"]["analysis"]
    assert job["permissions"] == {
        "contents": "read",
        "security-events": "write",
        "id-token": "write",
    }
    assert any(item.startswith("ossf/scorecard-action@") for item in uses(value))
    assert all(PINNED.match(item) for item in raw_uses("scorecard.yml"))


def test_vuln_daily_calls_the_shared_job_with_issue_write_only():
    value = load("vuln-daily.yml")
    assert value["permissions"] == {}
    assert value["on"]["schedule"] == [{"cron": "0 10 * * *"}]
    job = value["jobs"]["vuln"]
    assert job["uses"].startswith(
        "gonzalomartinperez/engineering-standards/.github/workflows/vuln-daily.yml@"
    )
    assert job["permissions"] == {"contents": "read", "issues": "write"}
    assert all(PINNED.match(item) for item in raw_uses("vuln-daily.yml"))


def test_settings_check_is_read_only():
    script = (ROOT / "scripts/check_repo_settings.sh").read_text()
    assert re.search(r"gh api [^\n]*-X|--method|PATCH|PUT|DELETE", script) is None


def test_mutation_workflow_is_least_privilege_pinned_and_frozen():
    value = load("mutation.yml")
    assert value["permissions"] == {}
    assert value["concurrency"]["cancel-in-progress"] == (
        "${{ github.event_name == 'pull_request' }}"
    )
    for job in value["jobs"].values():
        assert job["permissions"] == {"contents": "read"}
        assert "secrets" not in job
    assert all(PINNED.match(item) for item in raw_uses("mutation.yml"))
    text = (WORKFLOWS / "mutation.yml").read_text()
    assert text.count("persist-credentials: false") == len(value["jobs"])
    assert "secrets." not in text
    runs = [
        line.strip()
        for line in text.splitlines()
        if "uv run" in line and not line.lstrip().startswith("#")
    ]
    assert runs and all("uv run --frozen" in line for line in runs)
    assert value["env"]["AI_PROVIDER"] == "fixture"
    assert value["env"]["ALLOW_PAID_AI"] == "false"
    shard = value["jobs"]["mutation-shard"]["strategy"]["matrix"]["shard"]
    assert shard == [1, 2, 3, 4]
