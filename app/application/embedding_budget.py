"""Embedding charges share the generation ledger and hard application budget."""

from __future__ import annotations

import re
import secrets
from decimal import Decimal

from app.application.ports import Clock, Ledger
from app.domain.budget import BudgetPolicy, Pricing, Usage, cost_micro, worst_case_micro
from app.domain.errors import FailureCode, RejectedError
from app.domain.knowledge import EmbeddingPurpose

_OPERATION = re.compile(r'embedding:(?:index|query):[a-f0-9]{32}\Z')


class SharedEmbeddingAccounting:
    """Reserve before network I/O; unknown usage remains charged conservatively.

    The adapter bounds actual token usage by its reserved UTF-8 input bytes. Identifiers
    carry no visitor or content information and cannot address a generation reservation.
    """

    def __init__(
        self, ledger: Ledger, clock: Clock, budget: BudgetPolicy, input_per_million: Decimal
    ) -> None:
        self._ledger = ledger
        self._clock = clock
        self._budget = budget
        self._pricing = Pricing(input_per_million, input_per_million, input_per_million, Decimal(0))

    async def reserve(self, max_input_tokens: int, purpose: EmbeddingPurpose) -> str:
        if type(max_input_tokens) is not int or max_input_tokens <= 0:
            raise ValueError('embedding reservation requires a positive token bound')
        if not isinstance(purpose, EmbeddingPurpose):
            raise TypeError('unknown embedding purpose')
        operation_id = f'embedding:{purpose.value}:{secrets.token_hex(16)}'
        now = self._clock.now()
        reservation = worst_case_micro(max_input_tokens, 0, self._pricing)
        accepted = await self._ledger.reserve(
            operation_id, reservation, now.strftime('%Y-%m'), now.strftime('%Y-%m-%d'), self._budget.allows
        )
        if not accepted:
            raise RejectedError(FailureCode.BUDGET_EXHAUSTED)
        return operation_id

    async def settle(self, operation_id: str, input_tokens: int) -> None:
        self._validate_operation(operation_id)
        if type(input_tokens) is not int or input_tokens < 0:
            raise ValueError('embedding usage requires a nonnegative token count')
        usage = Usage(input_tokens, 0)
        await self._ledger.settle(
            operation_id, cost_micro(usage, self._pricing), usage, 'text-embedding-3-small'
        )

    async def mark_unreported(self, operation_id: str) -> None:
        self._validate_operation(operation_id)
        await self._ledger.mark_unreported(operation_id)

    @staticmethod
    def _validate_operation(operation_id: str) -> None:
        if not _OPERATION.fullmatch(operation_id):
            raise ValueError('not an embedding operation')
