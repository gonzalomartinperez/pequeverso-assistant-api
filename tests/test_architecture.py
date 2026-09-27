"""Dependency direction between layers (AST-based, no third-party tool)."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

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
    'adapters': {'pydantic', 'httpx', 'openai'},
    'presentation': {'fastapi', 'starlette', 'pydantic'},
    'bootstrap': {'fastapi', 'openai', 'pydantic', 'pydantic_settings'},
}


def _imports(path: Path) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
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
                    target = name.split('.')[1]
                    if target not in allowed:
                        violations.append(f'{path.relative_to(APP)} imports app.{target}')
                elif root not in THIRD_PARTY[layer]:
                    violations.append(f'{path.relative_to(APP)} imports {root}')
    assert violations == []


def test_sql_stays_in_the_sqlite_adapter() -> None:
    for path in APP.rglob('*.py'):
        if 'sqlite' in path.parts:
            continue
        text = path.read_text()
        assert 'SELECT ' not in text and 'INSERT INTO' not in text, path
