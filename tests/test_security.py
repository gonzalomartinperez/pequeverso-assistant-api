"""Log redaction and proxy-aware client identification."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path

from starlette.requests import Request

from app.bootstrap.logging import SafeJsonFormatter
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
