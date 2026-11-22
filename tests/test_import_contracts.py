"""Exercise the real contracts, including violations in isolated miniature packages."""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from configparser import ConfigParser
from pathlib import Path

import grimp
import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".importlinter"
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
    result = lint(ROOT, CONFIG)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "11 kept, 0 broken" in result.stdout


def assert_all_modules_are_in_import_graph(package: Path) -> None:
    modules = [
        ".".join((package.name, *path.relative_to(package).with_suffix("").parts)).removesuffix(
            ".__init__"
        )
        for path in package.rglob("*.py")
    ]
    assert len(modules) == len(set(modules)), "Application files must have distinct import names"
    graph = grimp.build_graph(package.name, cache_dir=None)
    # The graph must describe this tree, not another `app` earlier on sys.path.
    resolved = importlib.util.find_spec(package.name)
    assert resolved is not None and resolved.origin is not None
    assert Path(resolved.origin).resolve().parent == package.resolve()
    assert not (missing := set(modules) - graph.modules), f"Modules outside import graph: {missing}"


def test_import_contracts_see_every_real_module() -> None:
    assert_all_modules_are_in_import_graph(ROOT / "app")


def test_modules_skipped_by_import_linter_are_rejected(tmp_path, monkeypatch) -> None:
    package = tmp_path / "fixture_app"
    hidden = package / "namespace" / "example.py"
    hidden.parent.mkdir(parents=True)
    (package / "__init__.py").touch()
    hidden.write_text("import sqlite3\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(AssertionError, match=r"fixture_app\.namespace\.example"):
        assert_all_modules_are_in_import_graph(package)


def test_import_contract_baseline_is_empty() -> None:
    config = ConfigParser()
    config.read_string(CONFIG.read_text())
    for section in config.values():
        assert "ignore_imports" not in section, section.name
        assert section.get("unmatched_ignore_imports_alerting", "error") == "error", section.name


def test_miniature_package_keeps_all_contracts(tmp_path: Path) -> None:
    config = write_fixture(tmp_path, {})
    result = lint(tmp_path, config)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "11 kept, 0 broken" in result.stdout


@pytest.mark.parametrize(
    ("placement", "statement", "contract"),
    [
        ("domain", "from fixture_app.application import example", "Inward layer dependencies"),
        (
            "application",
            "from ..adapters.sqlite import example as stores",
            "Inward layer dependencies",
        ),
        ("application", "from .. import adapters as infrastructure", "Inward layer dependencies"),
        ("domain", "from fixture_app import presentation as wire", "Inward layer dependencies"),
        ("adapters", "import fixture_app.presentation", "Inward layer dependencies"),
        ("ai", "import fixture_app.adapters", "Inward layer dependencies"),
        (
            "presentation",
            "from fixture_app.adapters.postgres import example",
            "Presentation uses ports rather than concrete adapters",
        ),
        (
            "presentation",
            "import fixture_app.ai",
            "Presentation uses ports rather than concrete adapters",
        ),
        (
            "application",
            "import fastapi",
            "Inner layers and AI do not import web, database, model or telemetry SDKs",
        ),
        ("adapters/neo4j", "import psycopg", "postgres SDK confinement"),
        ("application", "from psycopg_pool import client as sdk", "postgres SDK confinement"),
        ("adapters/postgres", "import neo4j", "neo4j SDK confinement"),
        ("adapters/postgres", "import langgraph", "graph SDK confinement"),
        ("ai", "from langchain_core import client as sdk", "graph SDK confinement"),
        ("bootstrap", "from langsmith import client as sdk", "graph SDK confinement"),
        ("adapters/graph", "import openai as sdk", "providers SDK confinement"),
        (
            "adapters/postgres",
            "from openai.types import response as sdk",
            "providers SDK confinement",
        ),
        ("ai", "from openai import AsyncOpenAI", "providers SDK confinement"),
        ("adapters/postgres", "import opentelemetry", "telemetry SDK confinement"),
        ("bootstrap", "from opentelemetry import trace as telemetry", "telemetry SDK confinement"),
        (
            "adapters/providers",
            "import opentelemetry.sdk.trace as telemetry",
            "telemetry SDK confinement",
        ),
        ("adapters/graph", "from prometheus_client import Counter", "telemetry SDK confinement"),
        (
            "application/observability",
            "import prometheus_client as metrics",
            "telemetry SDK confinement",
        ),
        ("adapters/postgres", "import sqlite3", "sqlite SDK confinement"),
        ("adapters/graph", "import sqlite3.dbapi2 as storage", "sqlite SDK confinement"),
        ("application/sqlite", "import sqlite3 as storage", "sqlite SDK confinement"),
        (
            "adapters/neo4j",
            "from fixture_app.adapters.postgres import example",
            "Adapter capabilities remain independent",
        ),
    ],
)
def test_violations_break_the_named_real_contract(tmp_path, placement, statement, contract):
    config = write_fixture(tmp_path, {f"{placement}/example.py": statement + "\n"})
    assert_contract_broken(tmp_path, config, contract)


@pytest.mark.parametrize(
    "modules",
    [
        ("first", "second"),
        ("first", "second", "third"),
    ],
    ids=["two-module-cycle", "transitive-three-module-cycle"],
)
@pytest.mark.parametrize(
    "placement", ["application", "adapters/graph", "adapters/postgres/nested", "domain"]
)
def test_cycles_break_the_acyclic_contract(tmp_path, placement, modules):
    contents = {
        f"{placement}/{source}.py": f"from .{target} import run\n"
        for source, target in zip(modules, (*modules[1:], modules[0]), strict=True)
    }
    config = write_fixture(tmp_path, contents)
    assert_contract_broken(tmp_path, config, "Application modules form an acyclic graph")


@pytest.mark.parametrize(
    "path",
    [
        "application/import_sqlite.py",
        "adapters/graph/import_sqlite.py",
        "adapters/postgres/nested/import_sqlite.py",
        "adapters/postgres/import_sqlite/nested.py",
    ],
)
def test_legacy_import_filename_cannot_open_other_sqlite_driver_boundaries(tmp_path, path):
    config = write_fixture(tmp_path, {path: "import sqlite3\n"})
    assert_contract_broken(tmp_path, config, "sqlite SDK confinement")


def write_fixture(root: Path, contents: dict[str, str]) -> Path:
    app = root / "fixture_app"
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
    packages.extend(str(Path(path).parent) for path in contents)
    for package in packages:
        directory = app / package
        directory.mkdir(parents=True, exist_ok=True)
        for parent in (directory, *directory.parents):
            if parent.is_relative_to(app):
                (parent / "__init__.py").touch()
        (directory / "example.py").write_text("")
    # Protected external modules must exist in Grimp's graph, via allowed imports.
    for adapter, imports in {
        "postgres": "import psycopg\nimport psycopg_pool\n",
        "neo4j": "import neo4j\n",
        "graph": "import langgraph\nimport langchain_core\nimport langsmith\n",
        "providers": "import openai.types as sdk\n",
        "observability": "from opentelemetry import trace\nimport prometheus_client\n",
        "sqlite": "import sqlite3\n",
    }.items():
        (app / "adapters" / adapter / "sdk.py").write_text(imports)
    migration_module = app / "adapters/postgres/import_sqlite"
    if not migration_module.is_dir():
        migration_module.with_suffix(".py").write_text("import sqlite3\n")
    (app / "bootstrap/sdk.py").write_text("from openai import AsyncOpenAI\n")
    for path, source in contents.items():
        (app / path).write_text(source)
    config = root / ".importlinter"
    config.write_text(
        re.sub(r"(?<![\w.])app\.", "fixture_app.", CONFIG.read_text())
        # Module-boundary rewrite only: `webapp.` or prose containing "app." stays untouched.
        .replace("root_package = app", "root_package = fixture_app")
        .replace("    app\n", "    fixture_app\n")
    )
    return config


def assert_contract_broken(root: Path, config: Path, contract: str) -> None:
    result = lint(root, config)
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"{contract} BROKEN" in result.stdout, result.stdout + result.stderr


def test_cycle_between_sibling_packages_breaks_the_acyclic_contract(tmp_path):
    contents = {
        "application/left/__init__.py": "",
        "application/left/a.py": "from ..right.b import run\n",
        "application/right/__init__.py": "",
        "application/right/b.py": "from ..left.a import run\n",
    }
    config = write_fixture(tmp_path, contents)
    assert_contract_broken(tmp_path, config, "Application modules form an acyclic graph")
