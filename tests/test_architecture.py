"""Dependency direction between layers (AST-based, no third-party tool)."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / 'app'
STDLIB = sys.stdlib_module_names

ALLOWED: dict[str, set[str]] = {
    'domain': {'domain'},
    'application': {'domain', 'application'},
    'ai': {'domain', 'application', 'ai'},
    'adapters': {'domain', 'application', 'ai', 'adapters'},
    'presentation': {'domain', 'application', 'presentation'},
    'bootstrap': {'domain', 'application', 'ai', 'adapters', 'presentation', 'bootstrap'},
}
THIRD_PARTY: dict[str, set[str]] = {
    'domain': set(),
    'application': set(),
    'ai': set(),
    'adapters': {
        'pydantic',
        'httpx',
        'openai',
        'opentelemetry',
        'prometheus_client',
        'requests',
        'starlette',
        'psycopg',
        'psycopg_pool',
        'neo4j',
        'langgraph',
        'langchain_core',
        'langsmith',
    },
    'presentation': {'fastapi', 'starlette', 'pydantic'},
    'bootstrap': {'fastapi', 'openai', 'pydantic', 'pydantic_settings'},
}


def _imports(path: Path) -> list[str]:
    """Resolve imported names, including relative modules and package re-export aliases."""
    names: list[str] = []
    package = ('app', *path.relative_to(APP).parts[:-1])
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level > len(package):
                names.append('__invalid_relative_import__')
                continue
            base = '.'.join(package[: len(package) - node.level + 1]) if node.level else ''
            if node.module:
                base = f'{base}.{node.module}' if base else node.module
            names.extend(f'{base}.{alias.name}' if base else alias.name for alias in node.names)
    return names


def test_layers_depend_inwards_only() -> None:
    violations: list[str] = []
    for layer, allowed in ALLOWED.items():
        for path in (APP / layer).rglob('*.py'):
            for name in _imports(path):
                root = name.split('.')[0]
                if root == '__future__' or root in STDLIB:
                    continue
                if root == 'app':
                    target = name.split('.')[1] if '.' in name else '__bare_app__'
                    if target not in allowed:
                        violations.append(f'{path.relative_to(APP)} imports app.{target}')
                elif root not in THIRD_PARTY[layer]:
                    violations.append(f'{path.relative_to(APP)} imports {root}')
    assert violations == []


def test_sql_stays_in_storage_adapters() -> None:
    for path in APP.rglob('*.py'):
        if any(path.is_relative_to(APP / 'adapters' / name) for name in ('sqlite', 'postgres')):
            continue
        assert not any(name.split('.')[0] == 'sqlite3' for name in _imports(path)), path
        statements = re.compile(
            r'^\s*(?:SELECT\s+|INSERT\s+INTO\b|UPDATE\s+\w+\s+SET\b|DELETE\s+FROM\b|'
            r'CREATE\s+(?:TABLE|INDEX)\b|ALTER\s+TABLE\b|DROP\s+TABLE\b|PRAGMA\s+\w+)',
            re.IGNORECASE | re.MULTILINE,
        )
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert not statements.search(node.value), path


def test_relative_imports_are_resolved_before_layer_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / 'app'
    path = root / 'application' / 'example.py'
    path.parent.mkdir(parents=True)
    path.write_text('from ..adapters.sqlite import stores\n')
    monkeypatch.setitem(globals(), 'APP', root)
    assert 'app.adapters.sqlite.stores' in _imports(path)


def test_from_package_alias_cannot_hide_an_outer_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / 'app'
    path = root / 'domain' / 'example.py'
    path.parent.mkdir(parents=True)
    path.write_text('from app import adapters as infrastructure\n')
    monkeypatch.setitem(globals(), 'APP', root)
    assert 'app.adapters' in _imports(path)


def test_inward_relative_import_remains_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / 'app'
    path = root / 'application' / 'example.py'
    path.parent.mkdir(parents=True)
    path.write_text('from ..domain.catalog import Product as Item\n')
    monkeypatch.setitem(globals(), 'APP', root)
    test_layers_depend_inwards_only()


def test_outer_relative_import_is_rejected_by_the_real_layer_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / 'app'
    path = root / 'application' / 'example.py'
    path.parent.mkdir(parents=True)
    path.write_text('from .. import adapters as infrastructure\n')
    monkeypatch.setitem(globals(), 'APP', root)
    with pytest.raises(AssertionError, match=r'imports app\.adapters'):
        test_layers_depend_inwards_only()


def test_absolute_package_alias_is_rejected_by_the_real_layer_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / 'app'
    path = root / 'domain' / 'example.py'
    path.parent.mkdir(parents=True)
    path.write_text('from app import presentation as wire\n')
    monkeypatch.setitem(globals(), 'APP', root)
    with pytest.raises(AssertionError, match=r'imports app\.presentation'):
        test_layers_depend_inwards_only()


@pytest.mark.parametrize(
    'statement',
    [
        "cursor.execute('update records set value = 1')",
        "cursor.execute('delete from records')",
        "cursor.execute('select 1')",
        "cursor.execute('PRAGMA journal_mode = WAL')",
        'import sqlite3 as storage',
    ],
)
def test_sql_and_driver_cannot_bypass_the_adapter_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, statement: str
) -> None:
    root = tmp_path / 'app'
    path = root / 'application' / 'example.py'
    path.parent.mkdir(parents=True)
    path.write_text(statement + '\n')
    monkeypatch.setitem(globals(), 'APP', root)
    with pytest.raises(AssertionError):
        test_sql_stays_in_storage_adapters()


def test_ordinary_prose_is_not_treated_as_sql(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / 'app'
    path = root / 'domain' / 'example.py'
    path.parent.mkdir(parents=True)
    path.write_text('"""Topic words select evidence, never create product facts."""\n')
    monkeypatch.setitem(globals(), 'APP', root)
    test_sql_stays_in_storage_adapters()


def test_a_folder_named_sqlite_is_not_a_storage_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / 'app'
    path = root / 'application' / 'sqlite' / 'example.py'
    path.parent.mkdir(parents=True)
    path.write_text('import sqlite3\n')
    monkeypatch.setitem(globals(), 'APP', root)
    with pytest.raises(AssertionError):
        test_sql_stays_in_storage_adapters()


def test_external_runtime_sdks_stay_in_exact_adapters() -> None:
    boundaries = {
        'sqlite3': 'sqlite',
        'psycopg': 'postgres',
        'psycopg_pool': 'postgres',
        'neo4j': 'neo4j',
        'langgraph': 'graph',
        'langchain_core': 'graph',
        'langsmith': 'graph',
    }
    for path in APP.rglob('*.py'):
        for name in _imports(path):
            root = name.split('.')[0]
            if root in boundaries:
                if root == 'sqlite3' and path == APP / 'adapters' / 'postgres' / 'import_sqlite.py':
                    # Explicit offline, read-only legacy import; not a runtime PG driver.
                    continue
                assert path.is_relative_to(APP / 'adapters' / boundaries[root]), (path, root)


def test_cypher_stays_in_neo4j_adapter() -> None:
    statements = re.compile(
        r'^\s*(?:MATCH\s*\(|OPTIONAL\s+MATCH\b|MERGE\s*\(|UNWIND\s+\$|'
        r'CREATE\s+CONSTRAINT\b|DETACH\s+DELETE\b)',
        re.IGNORECASE | re.MULTILINE,
    )
    for path in APP.rglob('*.py'):
        if path.is_relative_to(APP / 'adapters' / 'neo4j'):
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert not statements.search(node.value), path


@pytest.mark.parametrize(
    ('module', 'placement'),
    [
        ('psycopg', 'adapters/neo4j'),
        ('sqlite3', 'adapters/postgres'),
        ('psycopg_pool', 'application'),
        ('neo4j', 'adapters/postgres'),
        ('langgraph', 'application'),
        ('langchain_core', 'ai'),
        ('langsmith', 'bootstrap'),
    ],
)
def test_storage_and_graph_sdks_cannot_hide_in_other_outer_folders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module: str, placement: str
) -> None:
    root = tmp_path / 'app'
    path = root / placement / 'example.py'
    path.parent.mkdir(parents=True)
    path.write_text(f'from {module} import client as sdk\n')
    monkeypatch.setitem(globals(), 'APP', root)
    with pytest.raises(AssertionError):
        test_external_runtime_sdks_stay_in_exact_adapters()


@pytest.mark.parametrize('placement', ['application', 'ai', 'adapters/postgres', 'bootstrap'])
def test_cypher_cannot_hide_outside_its_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, placement: str
) -> None:
    root = tmp_path / 'app'
    path = root / placement / 'example.py'
    path.parent.mkdir(parents=True)
    path.write_text('QUERY = "MATCH (n:PublicEntity) RETURN n"\n')
    monkeypatch.setitem(globals(), 'APP', root)
    with pytest.raises(AssertionError):
        test_cypher_stays_in_neo4j_adapter()


@pytest.mark.parametrize('placement', ['adapters/neo4j', 'adapters/graph', 'application/postgres'])
def test_postgres_folder_name_cannot_bypass_sql_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, placement: str
) -> None:
    root = tmp_path / 'app'
    path = root / placement / 'example.py'
    path.parent.mkdir(parents=True)
    path.write_text('QUERY = "SELECT * FROM public_chunks"\n')
    monkeypatch.setitem(globals(), 'APP', root)
    with pytest.raises(AssertionError):
        test_sql_stays_in_storage_adapters()


def test_application_import_graph_is_acyclic() -> None:
    modules = {
        '.'.join(('app', *path.relative_to(APP).with_suffix('').parts)).removesuffix('.__init__'): path
        for path in APP.rglob('*.py')
    }
    edges: dict[str, set[str]] = {}
    for module, path in modules.items():
        edges[module] = set()
        for name in _imports(path):
            target = name
            while target and target not in modules:
                target = target.rpartition('.')[0]
            if target and target != module:
                edges[module].add(target)
    visited: set[str] = set()
    active: list[str] = []

    def visit(module: str) -> None:
        assert module not in active, f'import cycle: {" -> ".join([*active, module])}'
        if module in visited:
            return
        active.append(module)
        for dependency in sorted(edges[module]):
            visit(dependency)
        active.pop()
        visited.add(module)

    for module in sorted(modules):
        visit(module)


def test_transitive_same_layer_cycles_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / 'app'
    folder = root / 'application'
    folder.mkdir(parents=True)
    (folder / 'first.py').write_text('from .second import run\n')
    (folder / 'second.py').write_text('from .third import run\n')
    (folder / 'third.py').write_text('from .first import run\n')
    monkeypatch.setitem(globals(), 'APP', root)
    with pytest.raises(AssertionError, match='import cycle'):
        test_application_import_graph_is_acyclic()


@pytest.mark.parametrize('placement', ['application', 'adapters/graph', 'adapters/postgres/nested'])
def test_legacy_import_filename_cannot_open_other_sqlite_driver_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, placement: str
) -> None:
    root = tmp_path / 'app'
    path = root / placement / 'import_sqlite.py'
    path.parent.mkdir(parents=True)
    path.write_text('import sqlite3\n')
    monkeypatch.setitem(globals(), 'APP', root)
    with pytest.raises(AssertionError):
        test_external_runtime_sdks_stay_in_exact_adapters()
