"""Pure regression of effective-setting admission; no Neo4j, Docker or provider is contacted."""

from unittest.mock import MagicMock

import pytest
from neo4j.exceptions import ClientError, Neo4jError

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
        disable_auto_commit_retries=True,
        telemetry_disabled=True,
        connection_timeout=3,
        connection_acquisition_timeout=3,
        max_connection_pool_size=1,
    )
    factory.return_value.__enter__.return_value.session.assert_called_once_with(database='system')
    query = session.run.call_args.args[0]
    assert query.text == ("SHOW SETTINGS 'dbms.usage_report.enabled' YIELD name, value RETURN name, value")
    assert query.timeout == 3


def test_smoke_flags_reach_real_sdk_pool_and_session_configuration(monkeypatch):
    actual_factory = smoke.GraphDatabase.driver
    observed = []

    def create(*args, **kwargs):
        driver = actual_factory(*args, **kwargs)
        assert driver._pool.pool_config.telemetry_disabled is True
        session = driver.session(database='system')
        assert session._config.disable_auto_commit_retries is True
        assert session._config.max_transaction_retry_time == 0
        session.close()
        result_session = MagicMock()
        result_session.__enter__.return_value.run.return_value.data.return_value = [
            {'name': 'dbms.usage_report.enabled', 'value': 'false'}
        ]
        monkeypatch.setattr(driver, 'session', lambda **options: result_session)
        observed.append(driver)
        return driver

    monkeypatch.setattr(smoke.GraphDatabase, 'driver', create)
    fixture = smoke.GraphFixture.__new__(smoke.GraphFixture)
    fixture.password = 'synthetic-fixture-password'
    fixture.usage_report_checks = []
    fixture.assert_usage_reporting_disabled()
    assert len(observed) == 1
    assert observed[0]._closed is True


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


class StartupClock:
    def __init__(self):
        self.now = 0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def client_error(code):
    error = Neo4jError._hydrate_gql(
        gql_status='50N42',
        description='Synthetic offline startup error',
        message='Synthetic offline startup error',
        neo4j_code=code,
    )
    assert isinstance(error, ClientError)
    return error


def ready_fixture(monkeypatch):
    fixture, factory, session = fixture_with_rows(
        monkeypatch, [{'name': 'dbms.usage_report.enabled', 'value': 'false'}]
    )
    fixture.container = 'synthetic-fixture-container'
    clock = StartupClock()
    monkeypatch.setattr(smoke, 'monotonic', clock.monotonic)
    monkeypatch.setattr(smoke.time, 'sleep', clock.sleep)
    monkeypatch.setattr(smoke, 'command', MagicMock(return_value='running healthy'))
    return fixture, factory, session, clock


def test_cold_show_timeout_then_false_requires_fresh_successful_proof(monkeypatch):
    fixture, factory, session, clock = ready_fixture(monkeypatch)
    timeout = client_error('Neo.ClientError.Transaction.TransactionTimedOutClientConfiguration')
    result = session.run.return_value

    def execute(query):
        assert query.timeout == 3
        clock.now += 3
        if session.run.call_count == 1:
            raise timeout
        return result

    session.run.side_effect = execute
    assert fixture.tcp_liveness() == 7
    assert clock.sleeps == [1]
    assert factory.call_count == session.run.call_count == 2
    assert fixture.usage_report_checks == [[{'name': 'dbms.usage_report.enabled', 'value': 'false'}]]
    for call in factory.call_args_list:
        assert call.kwargs['disable_auto_commit_retries'] is True
        assert call.kwargs['telemetry_disabled'] is True
        assert call.kwargs['max_transaction_retry_time'] == 0
        assert call.kwargs['connection_timeout'] == call.kwargs['connection_acquisition_timeout'] == 3
    for call in session.run.call_args_list:
        assert call.args[0].timeout == 3
        assert (
            call.args[0].text
            == "SHOW SETTINGS 'dbms.usage_report.enabled' YIELD name, value RETURN name, value"
        )


def test_always_cold_show_timeout_exhausts_existing_startup_window_without_admission(monkeypatch):
    fixture, factory, session, clock = ready_fixture(monkeypatch)
    timeout = client_error('Neo.ClientError.Transaction.TransactionTimedOutClientConfiguration')

    def execute(query):
        assert query.timeout == 3
        clock.now += 3
        raise timeout

    session.run.side_effect = execute
    with pytest.raises(RuntimeError, match='TCP liveness deadline exceeded'):
        fixture.tcp_liveness()
    assert clock.now == 120
    assert factory.call_count == session.run.call_count == 30
    assert clock.sleeps == [1] * 30
    assert fixture.usage_report_checks == []


def test_different_client_error_fails_immediately_without_polling(monkeypatch):
    fixture, factory, session, clock = ready_fixture(monkeypatch)
    failure = client_error('Neo.ClientError.Statement.SyntaxError')
    session.run.side_effect = failure
    with pytest.raises(ClientError) as raised:
        fixture.tcp_liveness()
    assert raised.value is failure
    assert factory.call_count == session.run.call_count == 1
    assert clock.sleeps == []


def test_untyped_error_with_matching_code_is_not_a_readiness_timeout(monkeypatch):
    fixture, factory, session, clock = ready_fixture(monkeypatch)
    failure = RuntimeError('Synthetic non-Neo4j failure')
    failure.code = 'Neo.ClientError.Transaction.TransactionTimedOutClientConfiguration'
    session.run.side_effect = failure
    with pytest.raises(RuntimeError) as raised:
        fixture.tcp_liveness()
    assert raised.value is failure
    assert factory.call_count == session.run.call_count == 1
    assert clock.sleeps == []


def test_normal_false_admits_once_without_readiness_polling(monkeypatch):
    fixture, factory, session, clock = ready_fixture(monkeypatch)
    assert fixture.tcp_liveness() == 0
    assert factory.call_count == session.run.call_count == 1
    assert clock.sleeps == []


def test_cold_timeout_does_not_allow_a_later_enabled_setting(monkeypatch):
    fixture, factory, session, clock = ready_fixture(monkeypatch)
    enabled = [{'name': 'dbms.usage_report.enabled', 'value': 'true'}]
    result = session.run.return_value
    result.data.return_value = enabled
    session.run.side_effect = [
        client_error('Neo.ClientError.Transaction.TransactionTimedOutClientConfiguration'),
        result,
    ]
    with pytest.raises(RuntimeError, match='usage reporting is not explicitly false'):
        fixture.tcp_liveness()
    assert factory.call_count == session.run.call_count == 2
    assert clock.sleeps == [1]
    assert fixture.usage_report_checks == [enabled]


def test_inspect_consuming_startup_budget_does_not_dispatch_another_show(monkeypatch):
    fixture, factory, session, clock = ready_fixture(monkeypatch)

    def inspect(arguments):
        clock.now = 120
        return 'running healthy'

    monkeypatch.setattr(smoke, 'command', inspect)
    with pytest.raises(RuntimeError, match='TCP liveness deadline exceeded'):
        fixture.tcp_liveness()
    factory.assert_not_called()
    session.run.assert_not_called()
    assert clock.sleeps == []
