import asyncio

import pytest

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
