"""Real isolated SQLite transactions: shared generation/index/query accounting."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.adapters.sqlite.database import Database
from app.adapters.sqlite.ledger import SqliteLedger
from app.application.embedding_budget import SharedEmbeddingAccounting
from app.domain.budget import BudgetPolicy, Usage
from app.domain.errors import FailureCode, RejectedError
from app.domain.knowledge import EmbeddingPurpose


class Clock:
    def now(self) -> datetime:
        return datetime(2026, 10, 17, tzinfo=UTC)


def test_generation_index_and_query_share_one_atomic_budget() -> None:
    async def scenario() -> None:
        db = Database(':memory:')
        await db.open()
        try:
            ledger = SqliteLedger(db)
            policy = BudgetPolicy(100, Decimal(0), 100)
            accounting = SharedEmbeddingAccounting(ledger, Clock(), policy, Decimal('0.02'))
            assert await ledger.reserve('generation', 80, '2026-10', '2026-10-17', policy.allows)
            outcomes = await asyncio.gather(
                accounting.reserve(1000, EmbeddingPurpose.INDEX),
                accounting.reserve(1000, EmbeddingPurpose.QUERY),
                return_exceptions=True,
            )
            accepted = [item for item in outcomes if isinstance(item, str)]
            rejected = [item for item in outcomes if isinstance(item, RejectedError)]
            assert len(accepted) == len(rejected) == 1
            assert rejected[0].code is FailureCode.BUDGET_EXHAUSTED
            assert await ledger.spent('2026-10', '2026-10-17') == (100, 100)
            await accounting.mark_unreported(accepted[0])
            assert await ledger.spent('2026-10', '2026-10-17') == (100, 100)
            # A late known report replaces the estimate, never erases another operation.
            await accounting.settle(accepted[0], 100)
            assert await ledger.spent('2026-10', '2026-10-17') == (82, 82)
        finally:
            await db.close()

    asyncio.run(scenario())


def test_api_recovery_preserves_live_indexer_and_index_recovery_preserves_cost() -> None:
    async def scenario() -> None:
        db = Database(':memory:')
        await db.open()
        try:
            ledger = SqliteLedger(db)
            policy = BudgetPolicy(1000, Decimal(0), 1000)
            accounting = SharedEmbeddingAccounting(ledger, Clock(), policy, Decimal('0.02'))
            index = await accounting.reserve(1000, EmbeddingPurpose.INDEX)
            query = await accounting.reserve(1000, EmbeddingPurpose.QUERY)
            assert await ledger.reserve('generation', 50, '2026-10', '2026-10-17', policy.allows)
            assert await ledger.abandon_pending() == 2
            statuses = await db.read(
                lambda c: {row['run_id']: row['status'] for row in c.execute('SELECT * FROM spend_ledger')}
            )
            assert statuses == {index: 'pending', query: 'unreported', 'generation': 'unreported'}
            assert await ledger.spent('2026-10', '2026-10-17') == (90, 90)
            assert await ledger.abandon_index_pending() == 1
            assert await ledger.abandon_index_pending() == 0
            assert await ledger.spent('2026-10', '2026-10-17') == (90, 90)
            await accounting.settle(index, 200)
            await accounting.settle(query, 300)
            await ledger.settle('generation', 9, Usage(9, 0), 'fixture')
            assert await ledger.spent('2026-10', '2026-10-17') == (19, 19)
        finally:
            await db.close()

    asyncio.run(scenario())


@pytest.mark.parametrize('tokens', [-1, 0, True])
def test_invalid_reservations_cannot_reach_ledger(tokens: int) -> None:
    async def scenario() -> None:
        ledger = SqliteLedger(Database(':memory:'))
        accounting = SharedEmbeddingAccounting(
            ledger, Clock(), BudgetPolicy(100, Decimal(0), 100), Decimal('0.02')
        )
        with pytest.raises(ValueError, match='positive token bound'):
            await accounting.reserve(tokens, EmbeddingPurpose.QUERY)

    asyncio.run(scenario())


def test_embedding_adapter_cannot_settle_generation_identifiers() -> None:
    async def scenario() -> None:
        accounting = SharedEmbeddingAccounting(
            SqliteLedger(Database(':memory:')),
            Clock(),
            BudgetPolicy(100, Decimal(0), 100),
            Decimal('0.02'),
        )
        with pytest.raises(ValueError, match='not an embedding operation'):
            await accounting.settle('generation', 0)
        with pytest.raises(ValueError, match='not an embedding operation'):
            await accounting.mark_unreported('generation')

    asyncio.run(scenario())
