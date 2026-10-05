"""Session, message and run stores."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from app.adapters.sqlite.database import Database
from app.application.ports import RunRecord, RunState
from app.domain.conversation import (
    AnswerDetails,
    ImageRef,
    LinkRef,
    Message,
    Notice,
    PriceRef,
    ProductRef,
    ResourceRef,
    Role,
    Session,
    SourceRef,
)
from app.domain.errors import FailureCode, RejectedError


def ts(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec='microseconds')


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _session(row: sqlite3.Row) -> Session:
    return Session(
        id=row['id'],
        csrf_token=row['csrf_token'],
        created_at=parse_ts(row['created_at']),
        last_active_at=parse_ts(row['last_active_at']),
        expires_at=parse_ts(row['expires_at']),
    )


class SqliteSessionStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, session: Session, secret_digest: bytes) -> None:
        await self._db.write(
            lambda c: c.execute(
                'INSERT INTO sessions (id, secret_digest, csrf_token, created_at, last_active_at, expires_at)'
                ' VALUES (?, ?, ?, ?, ?, ?)',
                (
                    session.id,
                    secret_digest,
                    session.csrf_token,
                    ts(session.created_at),
                    ts(session.last_active_at),
                    ts(session.expires_at),
                ),
            )
        )

    async def find(self, secret_digest: bytes, now: datetime) -> Session | None:
        row = await self._db.read(
            lambda c: c.execute(
                'SELECT * FROM sessions WHERE secret_digest = ? AND expires_at > ?', (secret_digest, ts(now))
            ).fetchone()
        )
        return _session(row) if row else None

    async def touch(self, session_id: str, now: datetime, expires_at: datetime) -> None:
        await self._db.write(
            lambda c: c.execute(
                'UPDATE sessions SET last_active_at = ?, expires_at = ? WHERE id = ?',
                (ts(now), ts(expires_at), session_id),
            )
        )

    async def delete(self, session_id: str) -> None:
        await self._db.write(lambda c: c.execute('DELETE FROM sessions WHERE id = ?', (session_id,)))

    async def purge_expired(self, now: datetime) -> int:
        def work(c: sqlite3.Connection) -> int:
            return c.execute('DELETE FROM sessions WHERE expires_at <= ?', (ts(now),)).rowcount

        return await self._db.write(work)


def details_to_json(details: AnswerDetails) -> str:
    return json.dumps(asdict(details), ensure_ascii=False, default=_encode)


def _encode(value: object) -> str:
    if isinstance(value, datetime):
        return ts(value)
    raise TypeError(type(value).__name__)


def _image(raw: dict[str, Any] | None) -> ImageRef | None:
    return ImageRef(**raw) if raw else None


def _product(raw: dict[str, Any]) -> ProductRef:
    price = raw['price']
    return ProductRef(
        **{
            **raw,
            'image': _image(raw['image']),
            'price': PriceRef(**{**price, 'verified_at': parse_ts(price['verified_at'])}) if price else None,
        }
    )


def details_from_json(raw: str) -> AnswerDetails:
    data: dict[str, Any] = json.loads(raw)
    return AnswerDetails(
        products=tuple(_product(item) for item in data['products']),
        resources=tuple(
            ResourceRef(**{**item, 'image': _image(item['image'])}) for item in data['resources']
        ),
        links=tuple(LinkRef(**item) for item in data['links']),
        sources=tuple(SourceRef(**item) for item in data['sources']),
        follow_ups=tuple(data['follow_ups']),
        notices=tuple(Notice(n) for n in data['notices']),
        language=data.get('language', 'es'),
    )


def _message(row: sqlite3.Row) -> Message:
    return Message(
        id=row['id'],
        role=Role(row['role']),
        content=row['content'],
        created_at=parse_ts(row['created_at']),
        details=details_from_json(row['details']),
    )


class SqliteMessageStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def append(self, session_id: str, message: Message) -> None:
        await self._db.write(
            lambda c: c.execute(
                'INSERT INTO messages (id, session_id, role, content, details, created_at) VALUES (?, ?, ?, ?, ?, ?)',
                (
                    message.id,
                    session_id,
                    message.role.value,
                    message.content,
                    details_to_json(message.details),
                    ts(message.created_at),
                ),
            )
        )

    async def history(self, session_id: str, limit: int) -> list[Message]:
        rows = await self._db.read(
            lambda c: c.execute(
                'SELECT * FROM (SELECT * FROM messages WHERE session_id = ? ORDER BY seq DESC LIMIT ?)'
                ' ORDER BY seq',
                (session_id, limit),
            ).fetchall()
        )
        return [_message(row) for row in rows]


class SqliteRunStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def claim(
        self, run_id: str, session_id: str, idempotency_key: str, request_hash: str, now: datetime
    ) -> RunRecord:
        def work(c: sqlite3.Connection) -> RunRecord:
            row = c.execute(
                'SELECT * FROM runs WHERE session_id = ? AND idempotency_key = ?',
                (session_id, idempotency_key),
            ).fetchone()
            if row is not None:
                return RunRecord(
                    row['id'],
                    session_id,
                    row['request_hash'],
                    RunState(row['state']),
                    row['assistant_message_id'],
                )
            try:
                c.execute(
                    'INSERT INTO runs (id, session_id, idempotency_key, request_hash, state, created_at)'
                    " VALUES (?, ?, ?, ?, 'active', ?)",
                    (run_id, session_id, idempotency_key, request_hash, ts(now)),
                )
            except sqlite3.IntegrityError as error:
                raise RejectedError(FailureCode.RUN_IN_PROGRESS) from error
            return RunRecord(run_id, session_id, request_hash, RunState.ACTIVE, None)

        return await self._db.write(work)

    async def finish(self, run_id: str, state: RunState, assistant_message_id: str | None) -> None:
        await self._db.write(
            lambda c: c.execute(
                "UPDATE runs SET state = ?, assistant_message_id = ? WHERE id = ? AND state = 'active'",
                (state.value, assistant_message_id, run_id),
            )
        )

    async def message(self, session_id: str, message_id: str) -> Message | None:
        row = await self._db.read(
            lambda c: c.execute(
                'SELECT * FROM messages WHERE session_id = ? AND id = ?', (session_id, message_id)
            ).fetchone()
        )
        return _message(row) if row else None

    async def abandon_active(self) -> int:
        def work(c: sqlite3.Connection) -> int:
            return c.execute("UPDATE runs SET state = 'failed' WHERE state = 'active'").rowcount

        return await self._db.write(work)
