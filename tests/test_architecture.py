"""Architecture rules that the import contracts cannot express."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
STDLIB = sys.stdlib_module_names

THIRD_PARTY: dict[str, set[str]] = {
    "domain": set(),
    "application": set(),
    "ai": set(),
    "adapters": {
        "pydantic",
        "httpx",
        "openai",
        "opentelemetry",
        "prometheus_client",
        "requests",
        "starlette",
        "psycopg",
        "psycopg_pool",
        "neo4j",
        "langgraph",
        "langchain_core",
        "langsmith",
    },
    "presentation": {"fastapi", "starlette", "pydantic"},
    "bootstrap": {"fastapi", "openai", "pydantic", "pydantic_settings"},
}


def _imports(path: Path) -> list[str]:
    """Resolve imported names, including relative modules and package re-export aliases."""
    names: list[str] = []
    package = ("app", *path.relative_to(APP).parts[:-1])
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level > len(package):
                names.append("__invalid_relative_import__")
                continue
            base = ".".join(package[: len(package) - node.level + 1]) if node.level else ""
            if node.module:
                base = f"{base}.{node.module}" if base else node.module
            names.extend(f"{base}.{alias.name}" if base else alias.name for alias in node.names)
    return names


def _module_layer(path: Path) -> str | None:
    """Classify every module; only two reviewed root-package exceptions exist."""
    relative = path.relative_to(APP)
    if relative == Path("__init__.py"):
        body = ast.parse(path.read_text()).body
        assert all(
            isinstance(node, ast.Pass)
            or (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            )
            for node in body
        ), f"root package initializer {relative} must remain inert"
        return None
    if relative == Path("main.py"):
        expected = ast.parse("from app.bootstrap.container import create_app\napp = create_app()\n")
        assert ast.dump(ast.parse(path.read_text())) == ast.dump(expected), (
            f"root entrypoint {relative} must only expose the bootstrap application"
        )
        return "bootstrap"
    assert len(relative.parts) > 1 and relative.parts[0] in THIRD_PARTY, (
        f"unclassified application module: {relative}"
    )
    return relative.parts[0]


def test_layers_depend_inwards_only() -> None:
    """Classify modules and check imports of root modules outside the layer contract."""
    for path in APP.rglob("*.py"):
        if _module_layer(path) is None:
            continue
        for name in _imports(path):
            root, _, target = name.partition(".")
            if root == "app":
                assert target.split(".")[0] in THIRD_PARTY, (
                    f"{path.relative_to(APP)} imports {name} outside the declared layers"
                )


def test_third_party_imports_stay_within_the_layer_allowlist() -> None:
    violations: list[str] = []
    for path in APP.rglob("*.py"):
        layer = _module_layer(path)
        if layer is None:
            continue
        for name in _imports(path):
            root = name.split(".")[0]
            if root not in {"app", "__future__"} and root not in STDLIB | THIRD_PARTY[layer]:
                violations.append(f"{path.relative_to(APP)} imports {root}")
    assert violations == []


def test_allowlist_distinguishes_relative_and_external_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "app"
    path = root / "application" / "example.py"
    path.parent.mkdir(parents=True)
    path.write_text("from ..domain.catalog import Product as Item\n")
    monkeypatch.setitem(globals(), "APP", root)
    test_third_party_imports_stay_within_the_layer_allowlist()
    path.write_text("import unlisted_sdk as sdk\n")
    with pytest.raises(AssertionError, match="imports unlisted_sdk"):
        test_third_party_imports_stay_within_the_layer_allowlist()


@pytest.mark.parametrize("statement", ["import app as root", "from .. import main"])
def test_imports_outside_the_declared_layers_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, statement: str
) -> None:
    root = tmp_path / "app"
    path = root / "application" / "example.py"
    path.parent.mkdir(parents=True)
    path.write_text(statement + "\n")
    monkeypatch.setitem(globals(), "APP", root)
    with pytest.raises(AssertionError, match="outside the declared layers"):
        test_layers_depend_inwards_only()


def test_sql_stays_in_storage_adapters() -> None:
    for path in APP.rglob("*.py"):
        if any(path.is_relative_to(APP / "adapters" / name) for name in ("sqlite", "postgres")):
            continue
        statements = re.compile(
            r"^\s*(?:SELECT\s+|INSERT\s+INTO\b|UPDATE\s+\w+\s+SET\b|DELETE\s+FROM\b|"
            r"CREATE\s+(?:TABLE|INDEX)\b|ALTER\s+TABLE\b|DROP\s+TABLE\b|PRAGMA\s+\w+)",
            re.IGNORECASE | re.MULTILINE,
        )
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert not statements.search(node.value), path


@pytest.mark.parametrize(
    "statement",
    [
        "cursor.execute('update records set value = 1')",
        "cursor.execute('delete from records')",
        "cursor.execute('select 1')",
        "cursor.execute('PRAGMA journal_mode = WAL')",
    ],
)
def test_sql_cannot_bypass_the_adapter_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, statement: str
) -> None:
    root = tmp_path / "app"
    path = root / "application" / "example.py"
    path.parent.mkdir(parents=True)
    path.write_text(statement + "\n")
    monkeypatch.setitem(globals(), "APP", root)
    with pytest.raises(AssertionError):
        test_sql_stays_in_storage_adapters()


def test_ordinary_prose_is_not_treated_as_sql(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "app"
    path = root / "domain" / "example.py"
    path.parent.mkdir(parents=True)
    path.write_text('"""Topic words select evidence, never create product facts."""\n')
    monkeypatch.setitem(globals(), "APP", root)
    test_sql_stays_in_storage_adapters()


def test_a_folder_named_sqlite_is_not_a_storage_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "app"
    path = root / "application" / "sqlite" / "example.py"
    path.parent.mkdir(parents=True)
    path.write_text('QUERY = "PRAGMA journal_mode = WAL"\n')
    monkeypatch.setitem(globals(), "APP", root)
    with pytest.raises(AssertionError):
        test_sql_stays_in_storage_adapters()


def test_cypher_stays_in_neo4j_adapter() -> None:
    statements = re.compile(
        r"^\s*(?:MATCH\s*\(|OPTIONAL\s+MATCH\b|MERGE\s*\(|UNWIND\s+\$|"
        r"CREATE\s+CONSTRAINT\b|DETACH\s+DELETE\b)",
        re.IGNORECASE | re.MULTILINE,
    )
    for path in APP.rglob("*.py"):
        if path.is_relative_to(APP / "adapters" / "neo4j"):
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert not statements.search(node.value), path


@pytest.mark.parametrize("placement", ["application", "ai", "adapters/postgres", "bootstrap"])
def test_cypher_cannot_hide_outside_its_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, placement: str
) -> None:
    root = tmp_path / "app"
    path = root / placement / "example.py"
    path.parent.mkdir(parents=True)
    path.write_text('QUERY = "MATCH (n:PublicEntity) RETURN n"\n')
    monkeypatch.setitem(globals(), "APP", root)
    with pytest.raises(AssertionError):
        test_cypher_stays_in_neo4j_adapter()


@pytest.mark.parametrize("placement", ["adapters/neo4j", "adapters/graph", "application/postgres"])
def test_postgres_folder_name_cannot_bypass_sql_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, placement: str
) -> None:
    root = tmp_path / "app"
    path = root / placement / "example.py"
    path.parent.mkdir(parents=True)
    path.write_text('QUERY = "SELECT * FROM public_chunks"\n')
    monkeypatch.setitem(globals(), "APP", root)
    with pytest.raises(AssertionError):
        test_sql_stays_in_storage_adapters()


def _local_import_target(name: str, modules: dict[str, Path]) -> str:
    while name and name not in modules:
        name = name.rpartition(".")[0]
    return name


def _reaches(edges: dict[str, set[str]], source: str, target: str) -> bool:
    pending = {source}
    visited: set[str] = set()
    while pending:
        module = pending.pop()
        if module == target:
            return True
        visited.add(module)
        pending.update(edges[module] - visited)
    return False


def test_package_initializers_do_not_form_import_cycles() -> None:
    """Acyclic sibling contracts omit edges between a package and its descendants."""
    modules = {
        ".".join(("app", *path.relative_to(APP).with_suffix("").parts)).removesuffix(
            ".__init__"
        ): path
        for path in APP.rglob("*.py")
    }
    edges = {
        module: {
            target
            for name in _imports(path)
            if (target := _local_import_target(name, modules)) and target != module
        }
        for module, path in modules.items()
    }
    for module, targets in edges.items():
        for target in targets:
            if module.startswith(f"{target}."):
                assert not _reaches(edges, target, module), (
                    f"import cycle through package initializer: {module} -> {target}"
                )


def test_package_initializer_cycles_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "app"
    folder = root / "application"
    folder.mkdir(parents=True)
    (folder / "__init__.py").write_text("from . import first\n")
    (folder / "first.py").write_text("from .second import run\n")
    (folder / "second.py").write_text("from . import run\n")
    monkeypatch.setitem(globals(), "APP", root)
    with pytest.raises(AssertionError, match="import cycle through package initializer"):
        test_package_initializers_do_not_form_import_cycles()


def test_sdk_importer_file_paths_match_the_contracts() -> None:
    # Import-linter sees the same import name for a module file and a package initializer.
    wrong_paths = {
        "sqlite.py": {"sqlite3"},
        "postgres.py": {"psycopg", "psycopg_pool"},
        "neo4j.py": {"neo4j"},
        "graph.py": {"langgraph", "langchain_core", "langsmith"},
        "providers.py": {"openai"},
        "observability.py": {"opentelemetry", "prometheus_client"},
        "postgres/import_sqlite/__init__.py": {"sqlite3"},
    }
    for relative, sdks in wrong_paths.items():
        path = APP / "adapters" / relative
        if path.is_file():
            assert not sdks.intersection(name.split(".")[0] for name in _imports(path)), path


@pytest.mark.parametrize(
    ("relative", "statement"),
    [
        ("postgres/import_sqlite/__init__.py", "import sqlite3"),
        ("postgres.py", "import psycopg"),
    ],
)
def test_sdk_importers_cannot_claim_a_boundary_with_the_wrong_file_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str, statement: str
) -> None:
    root = tmp_path / "app"
    path = root / "adapters" / relative
    path.parent.mkdir(parents=True)
    path.write_text(statement + "\n")
    monkeypatch.setitem(globals(), "APP", root)
    with pytest.raises(AssertionError):
        test_sdk_importer_file_paths_match_the_contracts()
