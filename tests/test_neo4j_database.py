import asyncio
from unittest.mock import MagicMock

import pytest
from neo4j._async.work import session as sdk_session
from neo4j.exceptions import Neo4jError

from app.adapters.neo4j.database import Neo4jDatabase


class Driver:
    def __init__(self):
        self.verified = 0
        self.closed = 0
        self.error = None

    async def verify_connectivity(self):
        self.verified += 1
        if self.error:
            raise self.error

    async def close(self):
        self.closed += 1


def test_driver_is_bounded_nonretrying_and_owned_close_happens_once(monkeypatch) -> None:
    driver = Driver()
    observed = []

    def create(uri, **kwargs):
        observed.append((uri, kwargs))
        return driver

    monkeypatch.setattr('app.adapters.neo4j.database.AsyncGraphDatabase.driver', create)
    database = Neo4jDatabase('bolt://127.0.0.1:17689', 'neo4j', 'synthetic-fixture-password')
    assert driver.verified == 0  # Factory construction never touches a socket.

    async def run():
        await database.open()
        await database.open()
        await asyncio.gather(database.close(), database.close())

    asyncio.run(run())
    assert driver.verified == 1 and driver.closed == 1
    options = observed[0][1]
    assert options['max_connection_pool_size'] == 4
    assert options['max_transaction_retry_time'] == 0
    assert options['disable_auto_commit_retries'] is True
    assert options['telemetry_disabled'] is True
    assert options['connection_timeout'] == options['connection_acquisition_timeout'] == 3


@pytest.mark.parametrize('error', [OSError('synthetic offline'), asyncio.CancelledError()])
def test_failed_or_cancelled_acquisition_closes_the_owned_driver(monkeypatch, error) -> None:
    driver = Driver()
    driver.error = error
    monkeypatch.setattr(
        'app.adapters.neo4j.database.AsyncGraphDatabase.driver', lambda *args, **kwargs: driver
    )
    database = Neo4jDatabase('bolt://127.0.0.1:17689', 'neo4j', 'synthetic-fixture-password')

    async def run():
        with pytest.raises(type(error)):
            await database.open()
        await database.close()

    asyncio.run(run())
    assert driver.closed == 1


@pytest.mark.parametrize(
    'uri',
    [
        'http://remote.invalid',
        'bolt://user:secret@remote.invalid',
        'bolt://remote.invalid?secret=value',
        'bolt://remote.invalid#secret',
    ],
)
def test_unsafe_graph_uri_is_rejected_before_constructing_driver(monkeypatch, uri) -> None:
    def unexpected_driver(*args, **kwargs):
        raise AssertionError('unsafe connection must never construct a driver')

    monkeypatch.setattr('app.adapters.neo4j.database.AsyncGraphDatabase.driver', unexpected_driver)
    with pytest.raises(ValueError, match='explicit private credentials'):
        Neo4jDatabase(uri, 'neo4j', 'synthetic-fixture-password')


@pytest.mark.parametrize(('disable_retries', 'expected_attempts'), [(True, 1), (False, 2)])
def test_real_sdk_implicit_idempotent_error_attempts_are_bounded(
    monkeypatch, caplog, disable_retries, expected_attempts
) -> None:
    """Exercise the real locked SDK run loop; only its transport/result is replaced offline."""
    attempts = []
    error = Neo4jError._hydrate_gql(
        gql_status='50N42',
        description='Synthetic offline idempotent failure',
        message='Synthetic offline idempotent failure',
        neo4j_code='Neo.TransientError.General.DatabaseUnavailable',
        diagnostic_record={'_idempotent': True},
    )

    class OfflineResult:
        _attach_failed = True

        def __init__(self, *args):
            pass

        async def _run(self, *args):
            attempts.append(1)
            raise error

    monkeypatch.setattr(sdk_session, 'AsyncResult', OfflineResult)

    async def run():
        database = Neo4jDatabase('bolt://127.0.0.1:17689', 'neo4j', 'synthetic-fixture-password')
        assert database.driver._pool.pool_config.telemetry_disabled is True
        # The false override is a positive control for SDK6.2+'s independent implicit retry.
        session = (
            database.driver.session()
            if disable_retries
            else database.driver.session(disable_auto_commit_retries=False)
        )
        assert session._config.disable_auto_commit_retries is disable_retries
        assert session._config.max_transaction_retry_time == 0
        session._connection = MagicMock()
        try:
            with pytest.raises(Neo4jError) as raised:
                await session.run('RETURN 1')
            assert raised.value is error
        finally:
            # The offline stand-ins own no Bolt connection/result to consume or release.
            session._auto_result = None
            session._connection = None
            await session.close()
            await database.close()

    asyncio.run(run())
    assert len(attempts) == expected_attempts
    assert 'synthetic-fixture-password' not in caplog.text
