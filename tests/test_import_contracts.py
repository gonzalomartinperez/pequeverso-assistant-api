"""Exercise the real contracts, including violations in isolated miniature packages."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LINTER = shutil.which("lint-imports", path=str(Path(sys.executable).parent)) or "lint-imports"


def lint(root: Path, config: Path):
    return subprocess.run(  # noqa: S603 -- fixed local linter, isolated synthetic package
        [LINTER, "--config", str(config), "--no-cache"],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root)},
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def test_real_contracts_are_kept():
    result = lint(ROOT, ROOT / ".importlinter")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "10 kept, 0 broken" in result.stdout


@pytest.mark.parametrize(
    ("placement", "statement", "contract"),
    [
        ("domain", "from fixture_app.application import example", "Inward layer dependencies"),
        (
            "application",
            "import fastapi",
            "Inner layers and AI do not import web, database, model or telemetry SDKs",
        ),
        ("adapters/neo4j", "import psycopg", "postgres SDK confinement"),
        ("adapters/postgres", "import sqlite3", "sqlite SDK confinement"),
        (
            "adapters/neo4j",
            "from fixture_app.adapters.postgres import example",
            "Adapter capabilities remain independent",
        ),
    ],
)
def test_violations_break_the_named_real_contract(tmp_path, placement, statement, contract):
    packages = ["", "domain", "application", "ai", "presentation", "bootstrap", "adapters"]
    packages += [
        f"adapters/{name}"
        for name in (
            "sqlite",
            "postgres",
            "neo4j",
            "graph",
            "providers",
            "observability",
            "catalog",
        )
    ]
    for package in packages:
        directory = tmp_path / "fixture_app" / package
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "__init__.py").write_text("")
        (directory / "example.py").write_text("")
    # Protected external modules must exist in Grimp's graph, via allowed imports.
    for adapter, imports in {
        "postgres": "import psycopg\nimport psycopg_pool\n",
        "neo4j": "import neo4j\n",
        "graph": "import langgraph\nimport langchain_core\nimport langsmith\n",
        "providers": "import openai\n",
        "observability": "import opentelemetry\nimport prometheus_client\n",
        "sqlite": "import sqlite3\n",
    }.items():
        (tmp_path / "fixture_app/adapters" / adapter / "sdk.py").write_text(imports)
    (tmp_path / "fixture_app/adapters/postgres/import_sqlite.py").write_text("")
    (tmp_path / "fixture_app" / placement / "example.py").write_text(statement + "\n")
    config = tmp_path / ".importlinter"
    config.write_text(
        (ROOT / ".importlinter")
        .read_text()
        .replace("app.", "fixture_app.")
        .replace("root_package = app", "root_package = fixture_app")
    )
    result = lint(tmp_path, config)
    assert result.returncode != 0, result.stdout + result.stderr
    assert f"{contract} BROKEN" in result.stdout, result.stdout + result.stderr
