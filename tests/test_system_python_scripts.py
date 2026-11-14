"""Scripts that CI runs with the runner's system python3 must parse on Python 3.12.

The uv environment and the image run Python 3.14, but `python3 -m scripts.ci_identity`,
`python3 -m scripts.compare_oci_images` and the smoke shell scripts use the Ubuntu 24.04 system
interpreter (3.12). Syntax such as unparenthesized `except A, B:` (PEP 758, 3.14) breaks them.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_PYTHON_SCRIPTS = (
    "scripts/ci_identity.py",
    "scripts/compare_oci_images.py",
    "scripts/postgres_fixture_identity.py",
    "scripts/container_fixture_probe.py",
)


@pytest.mark.parametrize("name", SYSTEM_PYTHON_SCRIPTS)
def test_script_parses_with_python_3_12_grammar(name: str) -> None:
    source = (ROOT / name).read_text(encoding="utf-8")
    ast.parse(source, filename=name, feature_version=(3, 12))
    # ast.parse cannot reject PEP 758 by feature_version, so check that form explicitly.
    assert not re.search(r"^\s*except\s+[\w.]+\s*,", source, re.MULTILINE), name


def test_ruff_keeps_these_scripts_on_the_3_12_target() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    line = next(line for line in pyproject.splitlines() if "per-file-target-version" in line)
    assert '"py312"' in line
    for name in SYSTEM_PYTHON_SCRIPTS:
        assert Path(name).stem in line


def test_every_system_python3_invocation_is_listed() -> None:
    texts = [
        (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"),
        *(path.read_text(encoding="utf-8") for path in (ROOT / "scripts").glob("*.sh")),
    ]
    invoked = set()
    for text in texts:
        invoked |= {f"scripts/{m}.py" for m in re.findall(r"python3 -m scripts\.(\w+)", text)}
        pattern = r'python3 "?(?:\$script_dir/|scripts/)(\w+)\.py'
        invoked |= {f"scripts/{m}.py" for m in re.findall(pattern, text)}
    assert invoked <= set(SYSTEM_PYTHON_SCRIPTS), invoked - set(SYSTEM_PYTHON_SCRIPTS)
