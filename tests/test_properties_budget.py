"""Reservation accounting under generated ledger interleavings."""

import asyncio
from decimal import Decimal

from hypothesis import example, given, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, precondition, rule

from app.adapters.sqlite.database import Database
from app.adapters.sqlite.ledger import SqliteLedger
from app.domain.budget import BudgetPolicy, Usage


class BudgetMachine(RuleBasedStateMachine):
    """Row 5: ledger reservations remain bounded across stateful transitions."""

    def __init__(self, cap=1000):
        super().__init__()
        self.loop = asyncio.Runner()
        self.db = Database(":memory:")
        self.loop.run(self.db.open())
        self.ledger = SqliteLedger(self.db)
        self.policy = BudgetPolicy(cap * 2, Decimal("0.1"), cap)
        self.pending = {}
        self.accounted = 0
        self.serial = 0

    @initialize(cap=st.integers(1, 5000))
    def configure_cap(self, cap):
        self.policy = BudgetPolicy(cap * 2, Decimal("0.1"), cap)

    @rule(amount=st.integers(1, 2000))
    def reserve(self, amount):
        self.serial += 1
        run_id = f"run-{self.serial}"
        accepted = self.loop.run(
            self.ledger.reserve(run_id, amount, "2026-09", "2026-09-28", self.policy.allows)
        )
        assert accepted == (self.accounted + amount <= self.policy.daily_cutoff_micro)
        if accepted:
            self.pending[run_id] = amount
            self.accounted += amount

    @precondition(lambda self: bool(self.pending))
    @rule(index=st.integers(0, 100), fraction=st.integers(0, 100))
    def settle(self, index, fraction):
        run_id = list(self.pending)[index % len(self.pending)]
        reserved = self.pending.pop(run_id)
        # Usage cannot exceed the worst-case reservation in this port's contract.
        actual = reserved * fraction // 100
        self.loop.run(self.ledger.settle(run_id, actual, Usage(1, 1), "fixture"))
        self.accounted += actual - reserved

    @precondition(lambda self: bool(self.pending))
    @rule(index=st.integers(0, 100))
    def release(self, index):
        # Ending without usage releases the active run, but retains its spend estimate.
        run_id = list(self.pending)[index % len(self.pending)]
        self.loop.run(self.ledger.mark_unreported(run_id))

    @invariant()
    def accounting_stays_under_cap(self):
        month, day = self.loop.run(self.ledger.spent("2026-09", "2026-09-28"))
        assert month == day == self.accounted
        assert 0 <= day <= self.policy.daily_cutoff_micro
        assert month <= self.policy.monthly_cutoff_micro

    def teardown(self):
        self.loop.run(self.db.close())
        self.loop.close()


TestBudgetInterleavings = BudgetMachine.TestCase
TestBudgetInterleavings.settings = settings(stateful_step_count=20)


@given(cap=st.integers(1, 5000), amount=st.integers(1, 2000))
@example(cap=100, amount=100)
def test_budget_regression(cap, amount):
    """Row 5: exact-cap reservation, retained unreported usage and settlement regression."""
    machine = BudgetMachine(cap)
    try:
        machine.reserve(amount)
        machine.reserve(amount)
        if machine.pending:
            machine.release(0)
            machine.settle(0, 0)
        machine.reserve(amount)
        machine.accounting_stays_under_cap()
    finally:
        machine.teardown()
