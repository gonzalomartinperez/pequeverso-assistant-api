"""Log redaction and proxy-aware client identification."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.routing import iter_route_contexts
from starlette.requests import Request

from app.bootstrap.logging import SafeJsonFormatter, configure_logging
from app.presentation.http import client_ip
from tests.support import ScriptedProvider, answer_json, ask, client, open_session

SECRET_QUESTION = 'Mi hija Sofía Gómez va al Colegio San Martín, ¿qué me recomiendas?'


@pytest.mark.parametrize('logger_name', ['third.party', 'openai', 'app.unregistered'])
def test_structured_external_logs_never_cross_the_application_allowlist(logger_name: str) -> None:
    marker = 'SYNTHETIC_PRIVATE_MARKER_NOT_A_KEY'
    record = logging.LogRecord(
        logger_name,
        logging.WARNING,
        'synthetic',
        1,
        json.dumps({'operation': 'run', 'outcome': 'completed', 'message': marker, 'api_key': marker}),
        (),
        None,
    )
    output = SafeJsonFormatter().format(record)
    assert marker not in output
    assert json.loads(output)['operation'] == 'unstructured_event'


def test_owned_json_logs_accept_only_safe_event_fields_and_values() -> None:
    marker = 'SYNTHETIC_PRIVATE_MARKER_NOT_A_KEY'
    record = logging.LogRecord(
        'app.request',
        logging.INFO,
        'synthetic',
        1,
        json.dumps(
            {
                'operation': 'request',
                'method': 'GET',
                'route': '/api/v1/session',
                'status': 200,
                'duration_ms': 12,
                'request_id': marker,
                'message': marker,
                'api_key': marker,
                'ts': marker,
            }
        ),
        (),
        None,
    )
    output = SafeJsonFormatter().format(record)
    assert marker not in output
    payload = json.loads(output)
    assert payload['operation'] == 'request'
    assert payload['route'] == '/api/v1/session' and payload['status'] == 200
    assert payload['duration_ms'] == 12 and payload['method'] == 'GET'
    assert 'request_id' not in payload


@pytest.mark.parametrize('field', ['method', 'route', 'status', 'duration_ms'])
def test_owned_log_fields_cannot_smuggle_arbitrary_strings(field: str) -> None:
    marker = 'SYNTHETIC_PRIVATE_MARKER_NOT_A_KEY'
    values: dict[str, object] = {
        'operation': 'request',
        'method': 'GET',
        'route': '/api/v1/session',
        'status': 200,
        'duration_ms': 12,
    }
    values[field] = marker
    record = logging.LogRecord('app.request', logging.INFO, 'synthetic', 1, json.dumps(values), (), None)
    assert marker not in SafeJsonFormatter().format(record)


def test_owned_unknown_operation_is_reduced_to_safe_metadata() -> None:
    marker = 'SYNTHETIC_PRIVATE_MARKER_NOT_A_KEY'
    record = logging.LogRecord(
        'app.application.chat',
        logging.WARNING,
        'synthetic',
        1,
        json.dumps({'operation': marker, 'message': marker}),
        (),
        None,
    )
    output = SafeJsonFormatter().format(record)
    assert marker not in output and json.loads(output)['operation'] == 'unstructured_event'


def test_provider_details_are_untrusted_even_with_an_owned_logger() -> None:
    marker = 'SYNTHETIC_PRIVATE_MARKER_NOT_A_KEY'
    record = logging.LogRecord(
        'app.adapters.providers.openai_provider',
        logging.WARNING,
        'synthetic',
        1,
        json.dumps({'operation': 'provider_stream', 'outcome': 'response.incomplete', 'reason': marker}),
        (),
        None,
    )
    output = SafeJsonFormatter().format(record)
    assert marker not in output
    assert json.loads(output)['outcome'] == 'response.incomplete'


@pytest.mark.parametrize('event', ['telemetry_export', 'telemetry_shutdown', 'telemetry_run_window'])
def test_legitimate_telemetry_events_remain_visible(event: str) -> None:
    outcome = 'unavailable' if event == 'telemetry_run_window' else 'failed'
    record = logging.LogRecord(
        'app.adapters.observability.telemetry',
        logging.WARNING,
        'synthetic',
        1,
        json.dumps({'operation': event, 'outcome': outcome}),
        (),
        None,
    )
    payload = json.loads(SafeJsonFormatter().format(record))
    assert payload['operation'] == event and payload['outcome'] == outcome


def test_logger_and_exception_names_cannot_be_used_as_private_payloads() -> None:
    marker = 'SYNTHETIC_PRIVATE_MARKER_NOT_A_KEY'
    error = type(marker, (Exception,), {})('another synthetic private value')
    record = logging.LogRecord(marker, logging.ERROR, 'synthetic', 1, '{}', (), (type(error), error, None))
    output = SafeJsonFormatter().format(record)
    assert marker not in output and 'another synthetic private value' not in output
    assert json.loads(output)['exception'] == 'Exception'


def test_external_log_messages_are_not_evaluated(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden() -> str:
        raise AssertionError('external getMessage must not run')

    record = logging.LogRecord('third.party', logging.WARNING, 'synthetic', 1, 'unused', (), None)
    monkeypatch.setattr(record, 'getMessage', forbidden)
    assert json.loads(SafeJsonFormatter().format(record))['operation'] == 'unstructured_event'


@pytest.mark.parametrize('logger_name', ['third.party', 'app.request'])
def test_deep_json_does_not_escape_the_formatter_or_dump_private_content(
    logger_name: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    marker = 'SYNTHETIC_PRIVATE_MARKER_NOT_A_KEY'
    payload = '[' * 10000 + '"' + marker + '"' + ']' * 10000
    record = logging.LogRecord(logger_name, logging.WARNING, 'synthetic', 1, payload, (), None)
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(SafeJsonFormatter())
    handler.emit(record)
    captured = capsys.readouterr()
    assert captured.err == '' and marker not in captured.out + output.getvalue()
    assert json.loads(output.getvalue())['operation'] == 'unstructured_event'


def test_json_parser_recursion_failure_has_no_raw_logging_fallback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def parser_failure(_: str) -> object:
        raise RecursionError('synthetic parser depth limit')

    marker = 'SYNTHETIC_PRIVATE_MARKER_NOT_A_KEY'
    record = logging.LogRecord('app.request', logging.WARNING, 'synthetic', 1, marker, (), None)
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(SafeJsonFormatter())
    with monkeypatch.context() as patch:
        patch.setattr(json, 'loads', parser_failure)
        handler.emit(record)
    captured = capsys.readouterr()
    assert captured.err == '' and marker not in captured.out + output.getvalue()
    assert json.loads(output.getvalue())['operation'] == 'unstructured_event'


def test_every_registered_route_template_retains_structured_request_metrics(tmp_path: Path) -> None:
    with client(tmp_path, observability_enabled=True, ops_read_token='l' * 40) as c:
        assert isinstance(c.app, FastAPI)
        templates = {context.path for context in iter_route_contexts(c.app.routes) if context.path}
        assert '/internal/v1/ops/telemetry' in templates
        assert '/api/v1/runs/{run_id}/cancel' in templates
        for route in templates:
            record = logging.LogRecord(
                'app.request',
                logging.INFO,
                'synthetic',
                1,
                json.dumps(
                    {
                        'operation': 'request',
                        'route': route,
                        'method': 'POST',
                        'status': 200,
                        'duration_ms': 1,
                    }
                ),
                (),
                None,
            )
            payload = json.loads(SafeJsonFormatter().format(record))
            assert payload['route'] == route and payload['status'] == 200


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
