"""Every application module must pass the real architecture gate, even without imports."""

from pathlib import Path

import pytest

from tests import test_architecture as architecture


def application_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str, content: str) -> None:
    root = tmp_path / 'app'
    module = root / relative
    module.parent.mkdir(parents=True)
    module.write_text(content)
    monkeypatch.setattr(architecture, 'APP', root)


@pytest.mark.parametrize('relative', ['unclassified/policy.py', 'unclassified/__init__.py', 'helper.py'])
def test_importless_unclassified_modules_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    application_fixture(tmp_path, monkeypatch, relative, 'VALUE = 1\n')
    with pytest.raises(AssertionError, match='unclassified application module'):
        architecture.test_layers_depend_inwards_only()


@pytest.mark.parametrize('layer', ['domain', 'application', 'ai', 'adapters', 'presentation', 'bootstrap'])
def test_each_declared_layer_remains_classified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, layer: str
) -> None:
    application_fixture(tmp_path, monkeypatch, f'{layer}/nested/policy.py', 'VALUE = 1\n')
    architecture.test_layers_depend_inwards_only()


@pytest.mark.parametrize('content', ['', '"""Application package."""\n', 'pass\n'])
def test_root_initializer_remains_inert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    application_fixture(tmp_path, monkeypatch, '__init__.py', content)
    architecture.test_layers_depend_inwards_only()


@pytest.mark.parametrize('content', ['import os\n', 'VALUE = object()\n', 'print("side effect")\n'])
def test_root_initializer_cannot_hide_executable_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    application_fixture(tmp_path, monkeypatch, '__init__.py', content)
    with pytest.raises(AssertionError, match='root package initializer'):
        architecture.test_layers_depend_inwards_only()


def test_existing_root_entrypoint_remains_a_thin_bootstrap_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application_fixture(
        tmp_path,
        monkeypatch,
        'main.py',
        'from app.bootstrap.container import create_app\napp = create_app()\n',
    )
    architecture.test_layers_depend_inwards_only()


@pytest.mark.parametrize(
    'content',
    [
        'from app.bootstrap.container import create_app\napp = create_app()\nVALUE = 1\n',
        'from app.domain.catalog import Product\n',
        'import os\n',
    ],
)
def test_root_entrypoint_exception_cannot_hide_other_logic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    application_fixture(tmp_path, monkeypatch, 'main.py', content)
    with pytest.raises(AssertionError, match='root entrypoint'):
        architecture.test_layers_depend_inwards_only()


def test_known_layer_initializers_keep_their_own_import_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    application_fixture(
        tmp_path,
        monkeypatch,
        'adapters/observability/__init__.py',
        'from .telemetry import RuntimeTelemetry\n',
    )
    architecture.test_layers_depend_inwards_only()
