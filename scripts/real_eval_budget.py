"""Independent conservative envelope for one explicitly authorized local evaluation.

Unknown usage, cancellation and failure retain the full allocation. Known usage is
settled at conservative rates including Fast and regional premiums. This is an evaluation helper, not a billing setting.
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncGenerator, Iterator
from contextlib import contextmanager
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any

import httpx2 as httpx
import openai
from openai import AsyncOpenAI

from app.adapters.openai_provider import OpenAIResponsesProvider
from app.ai.provider import ModelChunk, ModelRequest, UsageChunk
from app.domain.errors import FailureCode, RejectedError

MODEL = 'gpt-6-luna'
ATTEMPT_MICRO = 11000
MAX_ATTEMPTS = 400
CAP_MICRO = 1000000


class Envelope:
    def __init__(self, path: Path, cap_micro: int = CAP_MICRO, *, max_attempts: int | None = None) -> None:
        if not 0 < cap_micro <= CAP_MICRO:
            raise ValueError('evaluation cap must be positive and at most 1 USD')
        attempt_limit = MAX_ATTEMPTS if max_attempts is None else max_attempts
        if type(attempt_limit) is not int or not 1 <= attempt_limit <= 650:
            raise ValueError('evaluation attempt limit must be an integer between 1 and 650')
        self.cap_micro = cap_micro
        self._max_attempts = attempt_limit
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = path
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('BEGIN IMMEDIATE')
            db.execute(
                'CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY, reserved INTEGER NOT NULL, settled INTEGER NOT NULL DEFAULT 0)'
            )
            db.execute('CREATE TABLE IF NOT EXISTS status (reason TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS limits (cap INTEGER NOT NULL)')
            saved = db.execute('SELECT cap FROM limits LIMIT 1').fetchone()
            if saved is not None and saved[0] != cap_micro:
                raise ValueError('existing evaluation cap cannot be changed')
            if saved is None:
                db.execute('INSERT INTO limits (cap) VALUES (?)', (cap_micro,))
            # Independent metadata leaves the legacy ledger and monetary cap untouched.
            # Adding it to an old ledger requires an explicit owner-authorized procedure;
            # configuring this helper never grants permission to read keys or make calls.
            db.execute(
                'CREATE TABLE IF NOT EXISTS attempt_limits '
                '(id INTEGER PRIMARY KEY CHECK (id=1), max_attempts INTEGER NOT NULL '
                "CHECK (typeof(max_attempts)='integer' AND max_attempts BETWEEN 1 AND 650))"
            )
            saved_attempt_limit = db.execute('SELECT max_attempts FROM attempt_limits WHERE id=1').fetchone()
            if saved_attempt_limit is not None and saved_attempt_limit[0] != attempt_limit:
                raise ValueError('existing evaluation attempt limit cannot be changed')
            if saved_attempt_limit is None:
                db.execute('INSERT INTO attempt_limits (id,max_attempts) VALUES (1,?)', (attempt_limit,))
        path.chmod(0o600)

    @property
    def max_attempts(self) -> int:
        """The persisted, immutable attempt ceiling; independent of the monetary cap."""
        return self._max_attempts

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db
        finally:
            db.close()

    def snapshot(self) -> dict[str, Any]:
        with self.connect() as db:
            count, reserved = db.execute(
                'SELECT count(*), coalesce(sum(reserved),0) FROM attempts'
            ).fetchone()
            stopped = db.execute('SELECT reason FROM status LIMIT 1').fetchone()
        return {
            'attempts': count,
            'reserved_micro_usd': reserved,
            'stop_reason': stopped[0] if stopped else None,
        }

    def stop(self, reason: str) -> None:
        with self.connect() as db:
            db.execute('INSERT INTO status (reason) VALUES (?)', (reason,))

    def settle(self, attempt: int, inputs: int, outputs: int) -> None:
        if (
            type(inputs) is not int
            or type(outputs) is not int
            or not (0 <= inputs <= 24000 and 0 <= outputs <= 4000)
        ):
            with self.connect() as db:
                db.execute(
                    'UPDATE attempts SET reserved=max(reserved,?) WHERE id=?', (ATTEMPT_MICRO, attempt)
                )
            self.stop('usage_exceeds_bound')
            return
        amount = int(
            (Decimal(inputs) * Decimal('0.275') + Decimal(outputs) * Decimal('1.1')).to_integral_value(
                rounding=ROUND_CEILING
            )
        )
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT reserved, settled FROM attempts WHERE id=?', (attempt,)).fetchone()
            if row is None:
                raise ValueError('unknown evaluation attempt')
            if row[1]:
                db.execute('UPDATE attempts SET reserved=max(reserved,?) WHERE id=?', (amount, attempt))
                db.execute('INSERT INTO status (reason) VALUES (?)', ('duplicate_usage',))
            else:
                db.execute('UPDATE attempts SET reserved=?, settled=1 WHERE id=?', (amount, attempt))

    def reserve(self) -> int:
        attempt = None
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            stopped = db.execute('SELECT reason FROM status LIMIT 1').fetchone()
            count, used = db.execute('SELECT count(*), coalesce(sum(reserved),0) FROM attempts').fetchone()
            if not stopped and count < self.max_attempts and used + ATTEMPT_MICRO <= self.cap_micro:
                cursor = db.execute('INSERT INTO attempts (reserved) VALUES (?)', (ATTEMPT_MICRO,))
                attempt = cursor.lastrowid
            elif not stopped:
                db.execute('INSERT INTO status (reason) VALUES (?)', ('budget_or_attempt_limit',))
        if attempt is None:
            raise RejectedError(FailureCode.BUDGET_EXHAUSTED)
        return attempt


def bound_bytes(request: ModelRequest) -> int:
    return request.size_bytes()


class BoundedProvider:
    def __init__(
        self, key: str, envelope: Envelope, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._key = key
        self.envelope = envelope
        self.transport = transport
        self.receipts: list[dict[str, Any]] = []

    @property
    def model(self) -> str:
        return MODEL

    async def stream(self, request: ModelRequest) -> AsyncGenerator[ModelChunk]:
        byte_bound = bound_bytes(request)
        if not 0 < request.max_output_tokens <= 4000 or byte_bound > 24000:
            self.envelope.stop('request_bound')
            raise RejectedError(FailureCode.INVALID_REQUEST)
        attempt = self.envelope.reserve()
        receipt: dict[str, Any] = {'attempt': attempt, 'input_byte_bound': byte_bound, 'usage': None}
        self.receipts.append(receipt)

        async def check_wire(wire: httpx.Request) -> None:
            if len(wire.content) > 24000:
                self.envelope.stop('wire_bound')
                raise RejectedError(FailureCode.INVALID_REQUEST)

        # Explicit URL, no proxy/environment trust, standard tier, no SDK or adapter retries.
        async with (
            httpx.AsyncClient(
                transport=self.transport, trust_env=False, timeout=30, event_hooks={'request': [check_wire]}
            ) as http,
            AsyncOpenAI(
                api_key=self._key,
                base_url='https://api.openai.com/v1',
                http_client=http,
                timeout=30,
                max_retries=0,
            ) as client,
        ):
            provider = OpenAIResponsesProvider(client, MODEL, 'medium', 0)
            try:
                async for chunk in provider.stream(request):
                    if isinstance(chunk, UsageChunk):
                        usage = chunk.usage
                        receipt['usage'] = {
                            'input': usage.input_tokens,
                            'output': usage.output_tokens,
                            'cached': usage.cached_input_tokens,
                            'cache_write': usage.cache_write_tokens,
                            'reasoning': usage.reasoning_tokens,
                        }
                        self.envelope.settle(attempt, usage.input_tokens, usage.output_tokens)
                    yield chunk
            except RejectedError as error:
                # The adapter chains original SDK errors without exposing bodies/keys.
                cause = error.__cause__
                if isinstance(
                    cause,
                    (
                        openai.AuthenticationError,
                        openai.PermissionDeniedError,
                        openai.NotFoundError,
                        openai.BadRequestError,
                    ),
                ):
                    self.envelope.stop(type(cause).__name__)
                raise
