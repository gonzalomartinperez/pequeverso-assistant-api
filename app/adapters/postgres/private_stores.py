"""Native PostgreSQL session/history/idempotency stores, isolated from public knowledge."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from psycopg.errors import UniqueViolation

from app.adapters.postgres.database import PostgresDatabase, Row
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


def _encode(value: object) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec='microseconds')
    raise TypeError(type(value).__name__)


def details_to_json(details: AnswerDetails) -> str:
    return json.dumps(asdict(details), ensure_ascii=False, default=_encode)


def _image(raw: dict[str, Any] | None) -> ImageRef | None:
    return ImageRef(**raw) if raw else None


def details_from_json(raw: str) -> AnswerDetails:
    data: dict[str, Any] = json.loads(raw)
    products: list[ProductRef] = []
    for item in data['products']:
        price = item['price']
        products.append(
            ProductRef(
                **{
                    **item,
                    'image': _image(item['image']),
                    'price': PriceRef(
                        **{**price, 'verified_at': datetime.fromisoformat(price['verified_at'])}
                    )
                    if price
                    else None,
                }
            )
        )
    return AnswerDetails(
        products=tuple(products),
        resources=tuple(
            ResourceRef(**{**item, 'image': _image(item['image'])}) for item in data['resources']
        ),
        links=tuple(LinkRef(**item) for item in data['links']),
        sources=tuple(SourceRef(**item) for item in data['sources']),
        follow_ups=tuple(data['follow_ups']),
        notices=tuple(Notice(n) for n in data['notices']),
        language=data.get('language', 'es'),
    )


def message_from_row(row: Row) -> Message:
    return Message(
        row['id'], Role(row['role']), row['content'], row['created_at'], details_from_json(row['details'])
    )


class PostgresSessionStore:
    def __init__(self, db: PostgresDatabase) -> None:
        self._db = db

    async def create(self, session: Session, secret_digest: bytes) -> None:
        async with self._db.pool.connection() as conn:
            await conn.execute(
                'INSERT INTO assistant_private.sessions'
                '(id,secret_digest,csrf_token,created_at,last_active_at,expires_at) VALUES(%s,%s,%s,%s,%s,%s)',
                (
                    session.id,
                    secret_digest,
                    session.csrf_token,
                    session.created_at,
                    session.last_active_at,
                    session.expires_at,
                ),
            )

    async def find(self, secret_digest: bytes, now: datetime) -> Session | None:
        async with self._db.pool.connection() as conn:
            row = await (
                await conn.execute(
                    'SELECT * FROM assistant_private.sessions WHERE secret_digest=%s AND expires_at>%s',
                    (secret_digest, now),
                )
            ).fetchone()
        return (
            Session(row['id'], row['csrf_token'], row['created_at'], row['last_active_at'], row['expires_at'])
            if row
            else None
        )

    async def touch(self, session_id: str, now: datetime, expires_at: datetime) -> None:
        async with self._db.pool.connection() as conn:
            await conn.execute(
                'UPDATE assistant_private.sessions SET last_active_at=%s,expires_at=%s WHERE id=%s',
                (now, expires_at, session_id),
            )

    async def delete(self, session_id: str) -> None:
        async with self._db.pool.connection() as conn:
            await conn.execute('DELETE FROM assistant_private.sessions WHERE id=%s', (session_id,))

    async def purge_expired(self, now: datetime) -> int:
        async with self._db.pool.connection() as conn:
            return (
                await conn.execute('DELETE FROM assistant_private.sessions WHERE expires_at<=%s', (now,))
            ).rowcount


class PostgresMessageStore:
    def __init__(self, db: PostgresDatabase) -> None:
        self._db = db

    async def append(self, session_id: str, message: Message) -> None:
        async with self._db.pool.connection() as conn:
            await conn.execute(
                'INSERT INTO assistant_private.messages(id,session_id,role,content,details,created_at)'
                ' VALUES(%s,%s,%s,%s,%s,%s)',
                (
                    message.id,
                    session_id,
                    message.role.value,
                    message.content,
                    details_to_json(message.details),
                    message.created_at,
                ),
            )

    async def history(self, session_id: str, limit: int) -> list[Message]:
        if type(limit) is not int or not 0 <= limit <= 500:
            raise ValueError('history limit must be between zero and500')
        async with self._db.pool.connection() as conn:
            rows = await (
                await conn.execute(
                    'SELECT * FROM (SELECT * FROM assistant_private.messages WHERE session_id=%s'
                    ' ORDER BY seq DESC LIMIT %s) recent ORDER BY seq',
                    (session_id, limit),
                )
            ).fetchall()
        return [message_from_row(row) for row in rows]


class PostgresRunStore:
    def __init__(self, db: PostgresDatabase) -> None:
        self._db = db

    async def claim(
        self,
        run_id: str,
        session_id: str,
        idempotency_key: str,
        request_hash: str,
        now: datetime,
    ) -> RunRecord:
        try:
            async with self._db.pool.connection() as conn:
                row = await (
                    await conn.execute(
                        'INSERT INTO assistant_private.runs(id,session_id,idempotency_key,request_hash,state,created_at)'
                        " VALUES(%s,%s,%s,%s,'active',%s) ON CONFLICT(session_id,idempotency_key) DO NOTHING RETURNING *",
                        (run_id, session_id, idempotency_key, request_hash, now),
                    )
                ).fetchone()
                if row is None:
                    row = await (
                        await conn.execute(
                            'SELECT * FROM assistant_private.runs WHERE session_id=%s AND idempotency_key=%s',
                            (session_id, idempotency_key),
                        )
                    ).fetchone()
                if row is None:
                    raise RejectedError(FailureCode.RUN_IN_PROGRESS)
                return RunRecord(
                    row['id'],
                    session_id,
                    row['request_hash'],
                    RunState(row['state']),
                    row['assistant_message_id'],
                )
        except UniqueViolation as error:
            raise RejectedError(FailureCode.RUN_IN_PROGRESS) from error

    async def finish(self, run_id: str, state: RunState, assistant_message_id: str | None) -> None:
        async with self._db.pool.connection() as conn:
            await conn.execute(
                "UPDATE assistant_private.runs SET state=%s,assistant_message_id=%s WHERE id=%s AND state='active'",
                (state.value, assistant_message_id, run_id),
            )

    async def message(self, session_id: str, message_id: str) -> Message | None:
        async with self._db.pool.connection() as conn:
            row = await (
                await conn.execute(
                    'SELECT * FROM assistant_private.messages WHERE session_id=%s AND id=%s',
                    (session_id, message_id),
                )
            ).fetchone()
        return message_from_row(row) if row else None

    async def abandon_active(self) -> int:
        async with self._db.pool.connection() as conn:
            return (
                await conn.execute("UPDATE assistant_private.runs SET state='failed' WHERE state='active'")
            ).rowcount
