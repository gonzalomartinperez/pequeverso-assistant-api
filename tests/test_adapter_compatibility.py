"""Concrete capability modules and normal observability package exports."""

from __future__ import annotations

import ast
import hashlib
import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ('module_name', 'exports'),
    [
        ('fixture_provider', ('FixtureProvider',)),
        ('openai_provider', ('OpenAIResponsesProvider', 'usage_of')),
        ('openai_embeddings', ('OpenAIEmbeddings', 'FixtureHashEmbeddings')),
    ],
)
def test_providers_have_one_canonical_implementation(module_name: str, exports: tuple[str, ...]) -> None:
    module = importlib.import_module(f'app.adapters.providers.{module_name}')
    for name in exports:
        assert getattr(module, name).__module__ == module.__name__
    assert not (ROOT / 'app' / 'adapters' / f'{module_name}.py').exists()
    assert module.__file__ is not None
    tree = ast.parse(Path(module.__file__).read_text())
    definitions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert set(exports) <= definitions


def test_observability_package_exports_keep_concrete_identity() -> None:
    package = importlib.import_module('app.adapters.observability')
    implementation = importlib.import_module('app.adapters.observability.telemetry')
    for name in (
        'RuntimeTelemetry',
        'TelemetryMiddleware',
        'SafeExporter',
        'DeadlineSession',
        'resources',
    ):
        exported = getattr(package, name)
        assert exported is getattr(implementation, name)
        assert exported.__module__ == implementation.__name__
    assert package.__file__ is not None
    tree = ast.parse(Path(package.__file__).read_text())
    assert all(
        (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))
        or (isinstance(node, ast.ImportFrom) and node.module == implementation.__name__)
        for node in tree.body
    )


def test_evaluation_fingerprint_hashes_the_real_embedding_implementation() -> None:
    """Hash the concrete implementation that determines embedding accounting."""
    from app.bootstrap.knowledge_evaluation import _source_hashes

    hashes = _source_hashes()
    actual = 'app/adapters/providers/openai_embeddings.py'
    assert hashes[actual] == hashlib.sha256((ROOT / actual).read_bytes()).hexdigest()
    assert 'app/adapters/openai_embeddings.py' not in hashes
