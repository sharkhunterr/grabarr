"""Async SQLAlchemy session factory.

``engine`` and ``async_sessionmaker`` are created lazily so unit tests
can override them before the real DB is touched.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from grabarr.core.config import get_settings

__all__ = [
    "close_engine",
    "get_engine",
    "get_sessionmaker",
    "reset_engine",
    "session_scope",
]


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _database_url() -> str:
    """Build the SQLite URL from :func:`grabarr.core.config.get_settings`."""
    settings = get_settings()
    data_dir = Path(settings.server.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{data_dir}/grabarr.db"


def get_engine() -> AsyncEngine:
    """Return the process-wide ``AsyncEngine``, creating on first call.

    Enables SQLite WAL mode + busy_timeout=5s + 10s connection timeout
    so concurrent requests from Prowlarr + the background health monitor
    + cleanup sweeper don't trip ``OperationalError: database is locked``.
    """
    global _engine
    if _engine is None:
        from sqlalchemy import event

        _engine = create_async_engine(
            _database_url(),
            pool_pre_ping=True,
            future=True,
            connect_args={"timeout": 10},
        )

        # Run PRAGMAs on every new connection via SQLAlchemy's sync event
        # (aiosqlite wraps sync sqlite3 under the hood).
        sync_engine = _engine.sync_engine

        @event.listens_for(sync_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            try:
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA synchronous=NORMAL")
                cur.execute("PRAGMA busy_timeout=5000")
                cur.execute("PRAGMA foreign_keys=ON")
            finally:
                cur.close()

    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Commit-on-exit, rollback-on-exception session context."""
    sm = get_sessionmaker()
    async with sm() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_engine() -> None:
    """Dispose the engine (called on app shutdown)."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None


def reset_engine() -> None:
    """Test-only: clear the cached engine/sessionmaker."""
    global _engine, _sessionmaker
    _engine = None
    _sessionmaker = None
