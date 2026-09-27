"""Anonymous session ownership: an opaque random secret in an HttpOnly cookie, stored only as a
digest, plus a CSRF token the page keeps in memory for mutations.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from app.application.ports import Clock, MessageStore, RateLimiter, SessionStore
from app.domain.conversation import Message, Session
from app.domain.errors import FailureCode, RejectedError


def digest(secret: str) -> bytes:
    return hashlib.sha256(secret.encode()).digest()


@dataclass(frozen=True, slots=True)
class OpenedSession:
    session: Session
    secret: str | None
    """Set only when a new session was created and the cookie must be (re)issued with it."""
    history: list[Message]


@dataclass(frozen=True, slots=True)
class SessionLimits:
    retention: timedelta
    bootstraps_per_hour: int
    history_restore: int


class SessionService:
    def __init__(
        self,
        sessions: SessionStore,
        messages: MessageStore,
        rate_limiter: RateLimiter,
        clock: Clock,
        limits: SessionLimits,
    ) -> None:
        self._sessions = sessions
        self._messages = messages
        self._rate = rate_limiter
        self._clock = clock
        self._limits = limits

    async def resolve(self, secret: str | None) -> Session | None:
        if not secret or len(secret) > 128:
            return None
        return await self._sessions.find(digest(secret), self._clock.now())

    async def open(self, secret: str | None, client_key: str) -> OpenedSession:
        """Restore the caller's live session, or create one (rate limited per client)."""
        existing = await self.resolve(secret)
        now = self._clock.now()
        if existing is not None:
            expires = now + self._limits.retention
            await self._sessions.touch(existing.id, now, expires)
            history = await self._messages.history(existing.id, self._limits.history_restore)
            refreshed = Session(existing.id, existing.csrf_token, existing.created_at, now, expires)
            return OpenedSession(refreshed, secret, history)
        allowed = await self._rate.hit(f'bootstrap:{client_key}', 3600, self._limits.bootstraps_per_hour, now)
        if not allowed:
            raise RejectedError(FailureCode.RATE_LIMITED)
        new_secret = secrets.token_urlsafe(48)
        session = Session(
            id=secrets.token_urlsafe(16),
            csrf_token=secrets.token_urlsafe(32),
            created_at=now,
            last_active_at=now,
            expires_at=now + self._limits.retention,
        )
        await self._sessions.create(session, digest(new_secret))
        return OpenedSession(session, new_secret, [])

    async def require(self, secret: str | None, csrf_token: str | None) -> Session:
        session = await self.resolve(secret)
        if session is None:
            raise RejectedError(FailureCode.SESSION_EXPIRED)
        if not csrf_token or not secrets.compare_digest(csrf_token, session.csrf_token):
            raise RejectedError(FailureCode.CSRF_FAILED)
        return session

    async def touch(self, session: Session) -> None:
        now = self._clock.now()
        await self._sessions.touch(session.id, now, now + self._limits.retention)

    async def delete(self, session: Session) -> None:
        await self._sessions.delete(session.id)

    async def purge_expired(self) -> int:
        return await self._sessions.purge_expired(self._clock.now())
