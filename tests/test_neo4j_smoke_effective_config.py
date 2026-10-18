"""Pure regression of effective-setting admission; no Neo4j, Docker or provider is contacted."""

from unittest.mock import MagicMock

import pytest

from scripts import smoke_knowledge_neo4j as smoke


def fixture_with_rows(monkeypatch, rows):
    fixture = smoke.GraphFixture.__new__(smoke.GraphFixture)
    fixture.password = 'synthetic-fixture-password'
    fixture.usage_report_checks = []
    factory = MagicMock()
    session = factory.return_value.__enter__.return_value.session.return_value.__enter__.return_value
    session.run.return_value.data.return_value = rows
    monkeypatch.setattr(smoke.GraphDatabase, 'driver', factory)
    return fixture, factory, session


def test_effective_usage_setting_uses_direct_bolt_system_database_and_no_retry(monkeypatch):
    rows = [{'name': 'dbms.usage_report.enabled', 'value': 'false'}]
    fixture, factory, session = fixture_with_rows(monkeypatch, rows)
    fixture.assert_usage_reporting_disabled()
    assert fixture.usage_report_checks == [rows]
    factory.assert_called_once_with(
        'bolt://127.0.0.1:17689',
        auth=('neo4j', fixture.password),
        max_transaction_retry_time=0,
        connection_timeout=3,
        connection_acquisition_timeout=3,
        max_connection_pool_size=1,
    )
    factory.return_value.__enter__.return_value.session.assert_called_once_with(database='system')
    query = session.run.call_args.args[0]
    assert query.text == ("SHOW SETTINGS 'dbms.usage_report.enabled' YIELD name, value RETURN name, value")
    assert query.timeout == 3


@pytest.mark.parametrize(
    'rows',
    [
        [],
        [{'name': 'dbms.usage_report.enabled', 'value': 'true'}],
        [{'name': 'dbms.usage_report.enabled', 'value': None}],
        [{'name': 'dbms.usage_report.enabled', 'value': False}],
        [{'name': 'another.setting', 'value': 'false'}],
        [{'name': 'dbms.usage_report.enabled', 'value': 'false'}] * 2,
    ],
)
def test_missing_enabled_wrong_or_duplicate_effective_setting_fails_closed(monkeypatch, rows):
    fixture, _, _ = fixture_with_rows(monkeypatch, rows)
    with pytest.raises(RuntimeError, match='usage reporting is not explicitly false'):
        fixture.assert_usage_reporting_disabled()
    assert fixture.usage_report_checks == [rows]


def test_healthy_tcp_admission_checks_effective_setting_on_every_start(monkeypatch):
    fixture, factory, _ = fixture_with_rows(
        monkeypatch, [{'name': 'dbms.usage_report.enabled', 'value': 'false'}]
    )
    fixture.container = 'synthetic-fixture-container'
    monkeypatch.setattr(smoke, 'command', lambda arguments: 'running healthy')
    fixture.tcp_liveness()
    fixture.tcp_liveness()
    assert factory.call_count == 2
    assert len(fixture.usage_report_checks) == 2


def test_healthy_tcp_cannot_admit_an_enabled_usage_setting(monkeypatch):
    fixture, factory, _ = fixture_with_rows(
        monkeypatch, [{'name': 'dbms.usage_report.enabled', 'value': 'true'}]
    )
    fixture.container = 'synthetic-fixture-container'
    command = MagicMock(return_value='running healthy')
    monkeypatch.setattr(smoke, 'command', command)
    with pytest.raises(RuntimeError, match='usage reporting is not explicitly false'):
        fixture.tcp_liveness()
    assert command.call_count == 1
    assert factory.call_count == 1
