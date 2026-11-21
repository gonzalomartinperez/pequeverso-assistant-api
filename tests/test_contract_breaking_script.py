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
PUBLIC = "contracts/openapi.json"
INTERNAL = "contracts/openapi.internal.json"


def _git(repo: Path, *args: str) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)  # noqa: S603, S607


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "contracts").mkdir()
    (tmp_path / PUBLIC).write_text('{"public":true}')
    (tmp_path / INTERNAL).write_text('{"internal":true}')
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(
        tmp_path,
        "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
        "commit", "-q", "-m", "base",
    )  # fmt: skip
    return tmp_path


def _run(
    repo: Path,
    tmp_path: Path,
    base: str,
    oasdiff_status: int | None,
    labels: str,
    failing_spec: str = PUBLIC,
    extra: tuple[tuple[str, int], ...] = (),
):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")} | {"PR_LABELS": labels}
    args = [str(SCRIPT), base]
    if oasdiff_status is not None:
        fake = bin_dir / "oasdiff"
        log = tmp_path / "oasdiff.log"
        fake.write_text(
            "#!/usr/bin/env bash\n"
            f'echo "$1 $2 $3 $5" >> "{log}"\n'
            f'cat "$4" >> "{log}"\n'
            f'echo >> "{log}"\n'
            f'if [ "$5" = "{failing_spec}" ]; then exit {oasdiff_status}; fi\n'
            + "".join(f'if [ "$5" = "{name}" ]; then exit {code}; fi\n' for name, code in extra)
        )
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
@pytest.mark.parametrize("spec", [PUBLIC, INTERNAL])
def test_label_overrides_only_breaking_changes(repo, tmp_path, status, labels, expected, spec):
    assert _run(repo, tmp_path, "HEAD", status, labels, spec).returncode == expected


@pytest.mark.parametrize(("internal", "expected"), [(102, 102), (0, 0), (1, 0)])
def test_a_labelled_public_break_still_checks_the_internal_spec(repo, tmp_path, internal, expected):
    result = _run(repo, tmp_path, "HEAD", 1, LABEL, PUBLIC, extra=((INTERNAL, internal),))
    assert result.returncode == expected


def test_missing_binary_is_a_hard_failure_even_with_the_label(repo, tmp_path):
    assert _run(repo, tmp_path, "HEAD", None, LABEL).returncode == 127


def test_base_ref_that_is_not_a_commit_fails(repo, tmp_path):
    result = _run(repo, tmp_path, "no-such-ref", 0, LABEL)
    assert result.returncode == 2 and "not a commit" in result.stdout


def test_oasdiff_compares_the_base_spec_and_fails_on_errors(repo, tmp_path):
    assert _run(repo, tmp_path, "HEAD", 0, "[]").returncode == 0
    assert (tmp_path / "oasdiff.log").read_text().splitlines() == [
        f"breaking --fail-on ERR {PUBLIC}",
        '{"public":true}',
        f"breaking --fail-on ERR {INTERNAL}",
        '{"internal":true}',
    ]


@pytest.mark.parametrize("missing", [PUBLIC, INTERNAL])
def test_path_absent_at_the_base_passes_with_a_notice(repo, tmp_path, missing):
    _git(repo, "rm", "-q", missing)
    _git(
        repo,
        "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
        "commit", "-q", "-m", "drop",
    )  # fmt: skip
    (repo / missing).write_text("{}")
    result = _run(repo, tmp_path, "HEAD", 1, "[]", missing)
    assert result.returncode == 0 and f"no {missing} at the base revision" in result.stdout
    present = INTERNAL if missing == PUBLIC else PUBLIC
    assert (tmp_path / "oasdiff.log").read_text().splitlines()[0] == (
        f"breaking --fail-on ERR {present}"
    )
