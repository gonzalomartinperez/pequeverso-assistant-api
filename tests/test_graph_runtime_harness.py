"""A failing diagnostic/cleanup command must not strand another owned fixture resource."""

import json
import subprocess
from pathlib import Path

import pytest

from scripts import smoke_graph_runtime as harness


@pytest.mark.parametrize('failure', ['logs', 'stop', 'inspect', 'remove', 'receipt'])
def test_cleanup_continues_every_owned_resource_after_independent_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    calls: list[list[str]] = []
    created = [
        ('network', 'own-net'),
        ('volume', 'own-data'),
        ('container', 'own-first'),
        ('container', 'own-second'),
    ]

    def run(arguments: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        if arguments[1] == failure and arguments[-1] == 'own-first':
            raise subprocess.TimeoutExpired(arguments, 1)
        if failure == 'remove' and arguments[1:3] == ['container', 'rm'] and arguments[-1] == 'own-first':
            raise OSError('private-canary-must-not-appear-in-receipt')
        return subprocess.CompletedProcess(arguments, 0, stdout='0 false', stderr='')

    def capture() -> None:
        if failure == 'logs':
            raise OSError('private-canary-must-not-appear-in-receipt')

    write = Path.write_text

    def write_text(
        path: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        if failure == 'receipt' and path.name == 'owned-services.json':
            raise OSError('private-canary-must-not-appear-in-receipt')
        return write(path, data, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(subprocess, 'run', run)
    monkeypatch.setattr(Path, 'write_text', write_text)
    with pytest.raises(RuntimeError, match='did not complete safely'):
        harness.teardown_services(created, tmp_path, {}, capture)
    for name in ('own-first', 'own-second'):
        assert ['docker', 'stop', '--time', '30', name] in calls
        assert ['docker', 'inspect', '--format', '{{.State.ExitCode}} {{.State.OOMKilled}}', name] in calls
        assert ['docker', 'container', 'rm', '-f', name] in calls
    assert ['docker', 'volume', 'rm', 'own-data'] in calls
    assert ['docker', 'network', 'rm', 'own-net'] in calls
    assert all(argument[-1].startswith('own-') for argument in calls)
    if failure != 'receipt':
        raw = (tmp_path / 'owned-services.json').read_text()
        assert 'private-canary' not in raw
        assert json.loads(raw)['cleanup_failures']
