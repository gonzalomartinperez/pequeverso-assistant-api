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


def test_sql_stays_in_the_sqlite_adapter() -> None:
    for path in APP.rglob('*.py'):
        if path.is_relative_to(APP / 'adapters' / 'sqlite'):
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
        test_sql_stays_in_the_sqlite_adapter()


def test_ordinary_prose_is_not_treated_as_sql(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / 'app'
    path = root / 'domain' / 'example.py'
    path.parent.mkdir(parents=True)
    path.write_text('"""Topic words select evidence, never create product facts."""\n')
    monkeypatch.setitem(globals(), 'APP', root)
    test_sql_stays_in_the_sqlite_adapter()


def test_a_folder_named_sqlite_is_not_a_storage_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / 'app'
    path = root / 'application' / 'sqlite' / 'example.py'
    path.parent.mkdir(parents=True)
    path.write_text('import sqlite3\n')
    monkeypatch.setitem(globals(), 'APP', root)
    with pytest.raises(AssertionError):
        test_sql_stays_in_the_sqlite_adapter()
