"""Log redaction and proxy-aware client identification."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import pytest
from starlette.requests import Request

from app.bootstrap.logging import SafeJsonFormatter, configure_logging
from app.presentation.http import client_ip
from tests.support import ScriptedProvider, answer_json, ask, client, open_session

SECRET_QUESTION = 'Mi hija Sofía Gómez va al Colegio San Martín, ¿qué me recomiendas?'


def test_logs_never_contain_conversation_content_or_ips(tmp_path: Path) -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(SafeJsonFormatter())
    root = logging.getLogger()
    with client(tmp_path, ScriptedProvider(output=answer_json('Respuesta con Sofía.'))) as c:
        root.addHandler(handler)
        try:
            csrf = open_session(c)
            ask(c, csrf, SECRET_QUESTION)
            logging.getLogger('third.party').warning('leaking %s', SECRET_QUESTION)
        finally:
            root.removeHandler(handler)
    output = stream.getvalue()
    assert 'Sofía' not in output and 'Colegio' not in output and 'testclient' not in output
    lines = [json.loads(line) for line in output.splitlines()]
    assert any(line.get('operation') == 'run' and line.get('outcome') == 'completed' for line in lines)
    assert any(line.get('operation') == 'unstructured_event' for line in lines)


def test_uvicorn_error_handler_uses_safe_formatter_without_raw_exception(
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = logging.getLogger()
    error = logging.getLogger('uvicorn.error')
    parent = logging.getLogger('uvicorn')
    previous_root, previous_level = root.handlers[:], root.level
    previous_error, previous_propagate = error.handlers[:], error.propagate
    previous_parent, parent_propagate = parent.handlers[:], parent.propagate
    try:
        # Uvicorn installs a separate stderr handler before lifespan startup.
        error.handlers[:] = [logging.StreamHandler()]
        error.propagate = False
        # The default Uvicorn config also stops propagation at its parent logger.
        parent.handlers[:] = [logging.StreamHandler()]
        parent.propagate = False
        configure_logging()
        assert error.handlers == [] and error.propagate
        assert parent.handlers == [] and parent.propagate
        try:
            raise RuntimeError('synthetic-provider-secret-private-question')
        except RuntimeError:
            error.exception('unsafe synthetic-provider-secret-private-question')
        captured = capsys.readouterr()
        assert captured.err == ''
        assert 'synthetic-provider-secret-private-question' not in captured.out
        assert 'Traceback' not in captured.out
        record = json.loads(captured.out)
        assert record['logger'] == 'uvicorn.error'
        assert record['level'] == 'error' and record['exception'] == 'RuntimeError'
        assert record['operation'] == 'unstructured_event'
    finally:
        root.handlers[:] = previous_root
        root.setLevel(previous_level)
        error.handlers[:] = previous_error
        error.propagate = previous_propagate
        parent.handlers[:] = previous_parent
        parent.propagate = parent_propagate


def _request(peer: str, forwarded: str | None) -> Request:
    headers = [(b'x-forwarded-for', forwarded.encode())] if forwarded else []
    return Request({'type': 'http', 'client': (peer, 1234), 'headers': headers, 'method': 'GET', 'path': '/'})


def test_forwarded_for_is_trusted_only_from_configured_proxies() -> None:
    import ipaddress

    proxies = (ipaddress.ip_network('10.0.0.0/8'),)
    assert client_ip(_request('203.0.113.9', '1.2.3.4'), proxies) == '203.0.113.9'
    assert client_ip(_request('10.0.0.2', '198.51.100.7'), proxies) == '198.51.100.7'
    assert client_ip(_request('10.0.0.2', '6.6.6.6, 198.51.100.7, 10.0.0.3'), proxies) == '198.51.100.7'
    assert client_ip(_request('10.0.0.2', 'not-an-ip'), proxies) == '10.0.0.2'
    assert client_ip(_request('10.0.0.2', ', '.join(['1.1.1.1'] * 6)), proxies) == '10.0.0.2'
