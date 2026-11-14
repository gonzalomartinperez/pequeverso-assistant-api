"""scripts/contract_breaking.sh: the contract-major label overrides only oasdiff's exit 1."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "contract_breaking.sh"
LABEL = '["contract-major"]'


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)  # noqa: S603, S607


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "openapi.json").write_text("{}")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(
        tmp_path,
        "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
        "commit", "-q", "-m", "base",
    )  # fmt: skip
    return tmp_path


def _run(repo: Path, tmp_path: Path, base: str, oasdiff_status: int | None, labels: str):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    env = {**os.environ, "PR_LABELS": labels}
    args = [str(SCRIPT), base]
    if oasdiff_status is not None:
        fake = bin_dir / "oasdiff"
        fake.write_text(f"#!/usr/bin/env bash\nexit {oasdiff_status}\n")
        fake.chmod(0o755)
        args.append(str(fake))
    else:
        args.append(str(bin_dir / "missing-oasdiff"))
    return subprocess.run(  # noqa: S603
        [str(shutil.which("bash")), *args], cwd=repo, env=env, capture_output=True, text=True
    )


@pytest.mark.parametrize(
    ("status", "labels", "expected"),
    [
        (0, "[]", 0),
        (0, LABEL, 0),
        (1, "[]", 1),
        (1, LABEL, 0),
        (1, '["other"]', 1),
        (102, LABEL, 102),
        (102, "[]", 102),
        (2, LABEL, 2),
    ],
)
def test_label_overrides_only_breaking_changes(repo, tmp_path, status, labels, expected):
    assert _run(repo, tmp_path, "HEAD", status, labels).returncode == expected


def test_missing_binary_is_a_hard_failure_even_with_the_label(repo, tmp_path):
    assert _run(repo, tmp_path, "HEAD", None, LABEL).returncode == 127


def test_base_ref_that_is_not_a_commit_fails(repo, tmp_path):
    result = _run(repo, tmp_path, "no-such-ref", 0, LABEL)
    assert result.returncode != 0 and "not a commit" in result.stdout


def test_path_absent_at_the_base_passes_with_a_notice(repo, tmp_path):
    _git(repo, "rm", "-q", "-r", "contracts")
    _git(
        repo,
        "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
        "commit", "-q", "-m", "drop",
    )  # fmt: skip
    (repo / "contracts").mkdir()
    (repo / "contracts" / "openapi.json").write_text("{}")
    result = _run(repo, tmp_path, "HEAD", 1, "[]")
    assert result.returncode == 0 and "nothing to compare" in result.stdout
